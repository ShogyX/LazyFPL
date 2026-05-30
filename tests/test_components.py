"""Component-wise xP: expected-points math, rate-building, DB predict_gw."""

from datetime import datetime, timezone

from sqlalchemy import insert, select

from fpl_engine.db.models import player_availability, predictions_player_gw, training_rows
from fpl_engine.model.components import (
    ComponentPredictor,
    ExpectedComponents,
    build_components,
    expected_points,
    recency_weighted_rate,
)
from fpl_engine.model.minutes import MinutesPrediction
from fpl_engine.model.scoring import CURRENT

GK, DEF, MID, FWD = 1, 2, 3, 4


def test_appearance_term_splits_short_and_long():
    c = ExpectedComponents(MID, p_appear=1.0, p60=0.8, e_minutes=80)
    _, b = expected_points(c)
    # 0.8 * 2 (long) + 0.2 * 1 (short)
    assert abs(b["appearance"] - (0.8 * 2 + 0.2 * 1)) < 1e-9


def test_forward_goals_dominate():
    c = ExpectedComponents(FWD, p_appear=1.0, p60=0.9, e_minutes=85, e_goals=0.5)
    xp, b = expected_points(c)
    assert abs(b["goals"] - 4 * 0.5) < 1e-9      # FWD goal = 4
    assert b["clean_sheet"] == 0.0                # FWD CS worth 0


def test_defender_clean_sheet_and_exact_conceded_penalty():
    from fpl_engine.model.components import _expected_conceded_penalty
    c = ExpectedComponents(DEF, p_appear=1.0, p60=0.9, e_minutes=88,
                           cs_prob=0.4, e_conceded=1.2)
    _, b = expected_points(c)
    assert abs(b["clean_sheet"] - 4 * 0.4) < 1e-9         # DEF CS = 4
    # exact E[-floor(C/2)] for Poisson(1.2); less harsh than the -0.6 linear approx
    assert -0.6 < b["conceded"] < 0.0
    assert abs(b["conceded"] - _expected_conceded_penalty(1.2, 2)) < 1e-3  # 4dp rounding


def test_exact_conceded_penalty_properties():
    from fpl_engine.model.components import _expected_conceded_penalty
    assert _expected_conceded_penalty(0.0, 2) == 0.0
    # monotonically more negative as concession rate rises
    seq = [_expected_conceded_penalty(lam, 2) for lam in (0.5, 1.0, 2.0, 3.0)]
    assert seq == sorted(seq, reverse=True)
    # always strictly less harsh than the linear -lam/2 approximation
    for lam in (0.5, 1.5, 2.5):
        assert _expected_conceded_penalty(lam, 2) > -(lam / 2)


def test_keeper_saves_term():
    c = ExpectedComponents(GK, p_appear=1.0, p60=1.0, e_minutes=90, e_saves=6.0)
    _, b = expected_points(c)
    assert abs(b["saves"] - 6.0 / 3) < 1e-9               # +1 per 3 saves


def test_dc_term_only_for_eligible_positions():
    mid = ExpectedComponents(MID, p_appear=1.0, p60=0.9, e_minutes=85, dc_prob=0.5)
    _, bm = expected_points(mid)
    assert abs(bm["dc"] - 2 * 0.5) < 1e-9
    gk = ExpectedComponents(GK, p_appear=1.0, p60=1.0, e_minutes=90, dc_prob=0.9)
    _, bg = expected_points(gk)
    assert "dc" not in bg                                  # GK ineligible


def test_recency_blend_leans_stable_when_data_thin():
    # Fresh form (1.0) very different from long-run (0.2); few observations ->
    # weight the stable prior (variance control early in a sample/season).
    feats = {"expected_goals__ewma_hl5": 1.0, "expected_goals__mean_38": 0.2,
             "expected_goals__n": 1.0}
    r = recency_weighted_rate(feats, "expected_goals", k=4.0)
    assert 0.2 < r < 0.45          # closer to stable 0.2 than fresh 1.0


def test_recency_blend_leans_fresh_when_data_rich():
    feats = {"expected_goals__ewma_hl5": 1.0, "expected_goals__mean_38": 0.2,
             "expected_goals__n": 40.0}
    r = recency_weighted_rate(feats, "expected_goals", k=4.0)
    assert r > 0.85                # rich recent data -> tracks fresh form


def test_recency_blend_is_monotonic_in_observations():
    def rate(n):
        return recency_weighted_rate(
            {"expected_goals__ewma_hl5": 1.0, "expected_goals__mean_38": 0.2,
             "expected_goals__n": float(n)}, "expected_goals", k=4.0)
    seq = [rate(n) for n in (0, 2, 5, 10, 40)]
    assert seq == sorted(seq)      # more recent data -> steadily more fresh weight
    assert abs(seq[0] - 0.2) < 1e-9   # n=0 -> pure stable prior


def test_recency_blend_falls_back_to_available_signal():
    assert recency_weighted_rate({"x__mean_3": 0.5}, "x") == 0.5   # fresh only
    assert recency_weighted_rate({"x__mean_38": 0.3}, "x") == 0.3  # stable only
    assert recency_weighted_rate({}, "x") == 0.0                   # nothing


def test_opponent_strength_scales_attack_and_clean_sheet():
    mins = MinutesPrediction(p_start=1.0, p60=0.95, e_minutes=90.0, p_appear=1.0)
    base = {"expected_goals__mean_3": 0.5, "goals_conceded__mean_3": 1.0}
    neutral = build_components(FWD, base, mins, CURRENT)
    leaky_opp = build_components(FWD, {**base, "opp_def": 1.4}, mins, CURRENT)
    assert leaky_opp.e_goals > neutral.e_goals          # weak defence -> more goals

    strong_att = build_components(DEF, {**base, "opp_att": 1.5}, mins, CURRENT)
    neutral_def = build_components(DEF, base, mins, CURRENT)
    assert strong_att.cs_prob < neutral_def.cs_prob     # strong attack -> lower CS
    assert strong_att.e_conceded > neutral_def.e_conceded


def test_opponent_factors_clamped():
    mins = MinutesPrediction(1.0, 0.95, 90.0, 1.0)
    feats = {"expected_goals__mean_3": 0.5, "opp_def": 99.0}   # absurd -> clamped to 1.6
    c = build_components(FWD, feats, mins, CURRENT)
    assert abs(c.e_goals - 0.5 * 1.6) < 1e-9


def test_build_components_projects_xg_onto_minutes():
    feats = {"expected_goals__mean_3": 0.6, "expected_assists__mean_3": 0.3,
             "minutes__mean_3": 90.0}
    mins = MinutesPrediction(p_start=1.0, p60=0.95, e_minutes=90.0, p_appear=1.0)
    c = build_components(FWD, feats, mins, CURRENT)
    # xG per match 0.6 over ~90 mins, projected onto 90 predicted mins.
    assert abs(c.e_goals - 0.6) < 1e-6
    assert abs(c.e_assists - 0.3) < 1e-6


def test_build_components_scales_down_for_sub_risk():
    feats = {"expected_goals__mean_3": 0.6, "minutes__mean_3": 90.0}
    nailed = build_components(FWD, feats,
                             MinutesPrediction(1.0, 0.95, 90.0, 1.0), CURRENT)
    sub = build_components(FWD, feats,
                          MinutesPrediction(0.0, 0.0, 12.0, 0.35), CURRENT)
    assert sub.e_goals < nailed.e_goals       # fewer projected minutes -> fewer goals


def test_clean_sheet_gated_by_60(sm):
    # higher concession -> lower CS prob
    low = build_components(DEF, {"goals_conceded__mean_3": 0.5},
                          MinutesPrediction(1.0, 0.9, 88.0, 1.0), CURRENT)
    high = build_components(DEF, {"goals_conceded__mean_3": 2.0},
                           MinutesPrediction(1.0, 0.9, 88.0, 1.0), CURRENT)
    assert low.cs_prob > high.cs_prob


def _seed(sm):
    feats = {"expected_goals__mean_3": 0.5, "expected_assists__mean_3": 0.2,
             "minutes__mean_3": 90.0, "starts__mean_3": 1.0, "bonus__mean_3": 0.7}
    with sm() as s:
        s.execute(insert(training_rows), [
            {"season": "2025-26", "player_key": 1, "gw": 20, "element_id": 101,
             "element_type": FWD, "hist_n": 5, "features": feats, "feature_version": "t"},
            {"season": "2025-26", "player_key": 2, "gw": 20, "element_id": 102,
             "element_type": FWD, "hist_n": 5, "features": feats, "feature_version": "t"},
        ])
        # player 102 is injured -> minutes 0 -> xP collapses to 0.
        s.execute(insert(player_availability), [
            {"element_id": 102, "status": "i", "chance_next": 0,
             "captured_at": datetime(2026, 5, 1, tzinfo=timezone.utc)},
        ])
        s.commit()


def test_predict_gw_writes_breakdown_and_gates_injured(sm):
    _seed(sm)
    res = ComponentPredictor(sm=sm, model_version="c1").predict_gw("2025-26", 20)
    assert res.n_players == 2

    with sm() as s:
        rows = {r.element_id: r for r in s.execute(
            select(predictions_player_gw).where(
                predictions_player_gw.c.model_version == "c1")).all()}
    fit = rows[101]
    assert float(fit.xp_next1) > 2.0
    assert fit.breakdown["goals"] > 0 and "appearance" in fit.breakdown
    injured = rows[102]
    assert float(injured.xp_next1) == 0.0     # minutes gate zeroes everything
    assert float(injured.pred_minutes) == 0.0
