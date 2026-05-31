"""Distributional captaincy: the Monte-Carlo sampler is mean-consistent with the
linear expectation, exposes a sane ceiling/floor, and the DB loader gates a
no-show to ~0."""

from datetime import datetime, timezone

from sqlalchemy import insert

from fpl_engine.db.models import player_availability, training_rows
from fpl_engine.model.captaincy import CaptainDist, captain_distributions, simulate
from fpl_engine.model.components import ExpectedComponents, build_components, expected_points
from fpl_engine.model.minutes import MinutesPrediction
from fpl_engine.model.scoring import CURRENT, FWD, GK

NAILED = MinutesPrediction(1.0, 0.95, 90.0, 1.0)


def _fwd(e_goals=0.5, e_assists=0.2, e_bonus=0.6):
    return build_components(FWD, {"expected_goals__mean_3": e_goals,
                                  "expected_assists__mean_3": e_assists,
                                  "bonus__mean_3": e_bonus, "minutes__mean_3": 90.0},
                            NAILED, CURRENT)


def test_mc_ev_tracks_linear_expectation():
    c = _fwd()
    xp, _ = expected_points(c, CURRENT)
    d = simulate(c, CURRENT, seed=1)
    # The MC mean should agree with the linear xP (it differs only by the small
    # non-linear correction from floor/step terms), not drift wildly.
    assert abs(d.ev - xp) < 0.5
    assert d.n == 4000


def test_distribution_is_ordered_and_bounded():
    d = simulate(_fwd(e_goals=0.7), CURRENT, seed=2)
    assert d.floor <= d.median <= d.ceiling
    assert 0.0 <= d.haul <= 1.0 and 0.0 <= d.blank <= 1.0
    assert d.std > 0.0


def test_more_attacking_returns_lift_ev_and_ceiling():
    lo = simulate(_fwd(e_goals=0.2, e_assists=0.1), CURRENT, seed=3)
    hi = simulate(_fwd(e_goals=0.9, e_assists=0.4), CURRENT, seed=3)
    assert hi.ev > lo.ev
    assert hi.ceiling >= lo.ceiling
    assert hi.haul > lo.haul


def test_reproducible_for_a_fixed_seed():
    a = simulate(_fwd(), CURRENT, seed=7)
    b = simulate(_fwd(), CURRENT, seed=7)
    assert a == b


def test_rotation_risk_does_not_double_discount_appearance():
    # The component rates already fold in expected minutes; the sampler must not
    # re-apply the appearance discount, so a rotation player's MC EV must still
    # track the linear xP (regression guard for the conditional-on-appear fix).
    rot = MinutesPrediction(0.55, 0.4, 55.0, 0.7)
    c = build_components(FWD, {"expected_goals__mean_3": 0.45,
                               "expected_assists__mean_3": 0.2, "bonus__mean_3": 0.5},
                         rot, CURRENT)
    xp, _ = expected_points(c, CURRENT)
    d = simulate(c, CURRENT, seed=11)
    assert abs(d.ev - xp) < 0.3
    assert d.floor == 0.0  # a real chance of a no-show


def test_no_show_collapses_to_zero():
    dnp = ExpectedComponents(element_type=FWD, p_appear=0.0, p60=0.0, e_minutes=0.0,
                             e_goals=0.6, e_assists=0.3, e_bonus=0.5)
    d = simulate(dnp, CURRENT, seed=4)
    assert d.ev == 0.0 and d.ceiling == 0.0 and d.haul == 0.0


def test_keeper_save_points_contribute():
    gk = ExpectedComponents(element_type=GK, p_appear=1.0, p60=0.98, e_minutes=90.0,
                            e_saves=4.5, e_conceded=1.2)
    d = simulate(gk, CURRENT, seed=5)
    assert d.ev > 2.0  # appearance + saves + occasional clean sheet


def test_loader_gates_injured_player(sm):
    feats = {"expected_goals__mean_3": 0.5, "expected_assists__mean_3": 0.2,
             "minutes__mean_3": 90.0, "starts__mean_3": 1.0, "bonus__mean_3": 0.7}
    with sm() as s:
        s.execute(insert(training_rows), [
            {"season": "2025-26", "player_key": 1, "gw": 20, "element_id": 101,
             "element_type": FWD, "hist_n": 5, "features": feats, "feature_version": "t"},
            {"season": "2025-26", "player_key": 2, "gw": 20, "element_id": 102,
             "element_type": FWD, "hist_n": 5, "features": feats, "feature_version": "t"},
        ])
        s.execute(insert(player_availability), [
            {"element_id": 102, "status": "i", "chance_next": 0,
             "captured_at": datetime(2026, 5, 1, tzinfo=timezone.utc)},
        ])
        s.commit()
    dists = captain_distributions("2025-26", 20, {101, 102}, sm=sm)
    assert set(dists) == {101, 102}
    assert all(isinstance(d, CaptainDist) for d in dists.values())
    assert dists[101].ev > dists[102].ev      # the fit player beats the injured one
    assert dists[102].ev == 0.0               # minutes gate zeroes the no-show
