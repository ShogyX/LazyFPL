"""Minutes/availability model: estimator regimes + DB-backed predict_gw."""

from datetime import datetime, timezone

from sqlalchemy import insert

from fpl_engine.db.models import lineups, player_availability, training_rows
from fpl_engine.model.minutes import (
    MinutesModel,
    availability_multiplier,
    minutes_from_features,
    predict_one,
)

GK, DEF, MID, FWD = 1, 2, 3, 4


def test_availability_multiplier_gates():
    assert availability_multiplier("a", None) == 1.0
    assert availability_multiplier("i", None) == 0.0      # injured
    assert availability_multiplier("s", None) == 0.0      # suspended
    assert availability_multiplier("d", None) == 0.5      # doubtful, no %
    assert availability_multiplier("d", 25) == 0.25       # % overrides
    assert availability_multiplier("a", 75) == 0.75


def test_injured_player_zeroed():
    p = predict_one(starts_rate=1.0, recent_minutes=90, status="i")
    assert p.p_start == 0.0 and p.p60 == 0.0 and p.e_minutes == 0.0


def test_nailed_starter_high_minutes():
    p = predict_one(starts_rate=1.0, recent_minutes=89, status="a")
    assert p.p_start == 1.0
    assert p.e_minutes > 80 and p.p60 > 0.9


def test_confirmed_lineup_overrides_low_prior():
    # Trailing role looks like a rotation risk, but the XI is confirmed.
    p = predict_one(starts_rate=0.3, recent_minutes=25, status="a", lineup_role="start")
    assert p.p_start == 1.0
    assert p.e_minutes >= 60      # treated as a genuine starter


def test_benched_confirmation_collapses_start_prob():
    p = predict_one(starts_rate=0.9, recent_minutes=85, status="a", lineup_role="bench")
    assert p.p_start == 0.0
    # still a chance of sub minutes
    assert 0.0 < p.e_minutes < 15


def test_doubtful_scales_everything():
    fit = predict_one(starts_rate=1.0, recent_minutes=88, status="a")
    doubt = predict_one(starts_rate=1.0, recent_minutes=88, status="a", chance=50)
    assert abs(doubt.p_start - 0.5 * fit.p_start) < 1e-6
    assert doubt.e_minutes < fit.e_minutes


def test_rotation_risk_between_nailed_and_bench():
    p = predict_one(starts_rate=0.5, recent_minutes=45, status="a")
    assert 0.3 < p.p_start < 0.7


def _seed(sm):
    feats_nailed = {"starts__mean_3": 1.0, "minutes__mean_3": 90.0}
    feats_doubt = {"starts__mean_3": 1.0, "minutes__mean_3": 88.0}
    with sm() as s:
        s.execute(insert(training_rows), [
            {"season": "2025-26", "player_key": 1, "gw": 20, "element_id": 101,
             "element_type": MID, "hist_n": 5, "features": feats_nailed,
             "feature_version": "t"},
            {"season": "2025-26", "player_key": 2, "gw": 20, "element_id": 102,
             "element_type": FWD, "hist_n": 5, "features": feats_doubt,
             "feature_version": "t"},
        ])
        # Player 102 is doubtful (25%); player 101 fit.
        s.execute(insert(player_availability), [
            {"element_id": 102, "status": "d", "chance_next": 25,
             "captured_at": datetime(2026, 5, 1, tzinfo=timezone.utc)},
        ])
        # A confirmed lineup says player 101 starts.
        s.execute(insert(lineups), [
            {"source": "api_football", "fixture_ref": "f1", "player_ref": "p1",
             "player_key": 1, "role": "start", "confirmed": True,
             "captured_at": datetime(2026, 5, 2, tzinfo=timezone.utc)},
        ])
        s.commit()


def test_sub_on_rate_lifts_cameo_minutes_for_impact_subs():
    # Same low start rate, but an impact sub (plays nearly every non-start) should
    # get more expected minutes than a true bench-warmer (rarely plays).
    impact = predict_one(starts_rate=0.3, recent_minutes=30, status="a",
                         sub_on_rate=0.9)
    warmer = predict_one(starts_rate=0.3, recent_minutes=30, status="a",
                        sub_on_rate=0.05)
    assert impact.p_appear > warmer.p_appear
    assert impact.e_minutes > warmer.e_minutes
    assert impact.p_start == warmer.p_start          # start prob unchanged


def test_minutes_from_features_derives_sub_on_rate(sm):
    # played 0.9 but started 0.3 -> sub-on ~ (0.9-0.3)/(1-0.3) = 0.857: high cameo.
    hi = minutes_from_features({"starts__mean_5": 0.3, "minutes__mean_5": 30,
                                "played__mean_5": 0.9})
    lo = minutes_from_features({"starts__mean_5": 0.3, "minutes__mean_5": 30,
                                "played__mean_5": 0.32})
    assert hi.p_appear > lo.p_appear


def test_predict_gw_blends_db_signals(sm):
    _seed(sm)
    out = MinutesModel(sm=sm).predict_gw("2025-26", 20)
    assert set(out) == {101, 102}
    assert out[101].p_start == 1.0          # confirmed start
    assert out[102].p_start <= 0.25         # doubtful 25% gate
    assert out[102].e_minutes < out[101].e_minutes
