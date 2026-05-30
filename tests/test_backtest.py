"""Predictor-driven backtester: strict causality (signal from the pre-GW panel,
scored on GW actuals) + head-to-head predictor comparison (seeded data)."""

import numpy as np
from sqlalchemy import select

from fpl_engine.backtest import Backtester
from fpl_engine.db.models import backtest_runs, players, player_match_stats, training_rows
from fpl_engine.model.predictors import FeaturePredictor

GK, DEF, MID, FWD = 1, 2, 3, 4
SEASON = "2025-26"
GWS = [1, 2, 3, 4]


def _seed(sm):
    """30 players; each has a fixed 'skill'. The panel feature 'skill' equals it
    (a causal signal), and actual points each GW also equal it, so a predictor
    keyed on 'skill' should pick high-scoring players, while one keyed on pure
    'noise' should not."""
    rng = np.random.default_rng(0)
    roster, pid = [], 0
    for pos, n in ((GK, 4), (DEF, 10), (MID, 10), (FWD, 6)):
        for _ in range(n):
            pid += 1
            roster.append((pid, pos))

    players_rows, pms_rows, tr_rows = [], [], []
    for pid, pos in roster:
        skill = float(pid % 9) + 1.0
        players_rows.append({"id": pid, "element_type": pos, "team_id": (pid % 6) + 1,
                             "now_cost": 50, "status": "a", "web_name": f"P{pid}",
                             "selected_by_percent": 5.0})
        for gw in GWS:
            pms_rows.append({"season": SEASON, "element_id": pid, "fixture_id": gw * 1000 + pid,
                             "gw": gw, "player_key": pid, "element_type": pos, "value": 50,
                             "minutes": 90, "total_points": int(skill)})
            tr_rows.append({"season": SEASON, "player_key": pid, "gw": gw,
                            "element_id": pid, "element_type": pos, "hist_n": 5,
                            "features": {"skill": skill, "noise": float(rng.normal())},
                            "feature_version": "t"})
    with sm() as s:
        s.execute(players.insert(), players_rows)
        s.execute(player_match_stats.insert(), pms_rows)
        s.execute(training_rows.insert(), tr_rows)
        s.commit()


def test_backtest_is_self_consistent_and_stored(sm):
    _seed(sm)
    res = Backtester(sm=sm).run(SEASON, GWS, FeaturePredictor("skill", "skill"))
    assert len(res.per_gw) == len(GWS)
    assert res.net_points == res.total_points - res.total_hits
    assert res.total_points == sum(g["points"] for g in res.per_gw)
    with sm() as s:
        row = s.execute(select(backtest_runs).where(
            backtest_runs.c.strategy == "skill")).one()
    assert row.net_points == res.net_points


def test_informative_signal_beats_noise(sm):
    _seed(sm)
    bt = Backtester(sm=sm)
    preds = {"skill": FeaturePredictor("skill", "skill"),
             "noise": FeaturePredictor("noise", "noise")}
    results = bt.compare(SEASON, GWS, preds)
    # the predictor that tracks true scoring must not be beaten by pure noise
    assert results["skill"].net_points >= results["noise"].net_points
    # compare also runs a no-transfer hold baseline
    assert "hold" in results


def test_signal_drives_selection_not_actual_peeking(sm):
    # 'skill' feature == actual points, so a skill-driven backtest should field
    # the highest-skill XI; an "inverse" predictor (prefers low skill) must score
    # strictly less — proving selection is driven by the SIGNAL, scored on actuals.
    from dataclasses import dataclass

    from fpl_engine.model.predictors import BasePredictor

    @dataclass
    class Negated(BasePredictor):
        name: str = "neg"
        def score(self, features, element_type):
            return -float(features.get("skill", 0.0))

    _seed(sm)
    bt = Backtester(sm=sm)
    good = bt.run(SEASON, GWS, FeaturePredictor("skill", "skill"))
    neg = bt.run(SEASON, GWS, Negated())
    assert good.net_points > neg.net_points   # picking high-skill beats low-skill


def test_position_skewed_signal_still_fields_legal_squad(sm):
    # A signal that scores GKs/DEFs 0 (like an attacking metric) must NOT make
    # the pool unable to field 2 GK / 5 DEF -> the per-position pool guarantees
    # a feasible squad and a non-zero score.
    _seed(sm)

    from dataclasses import dataclass

    from fpl_engine.model.predictors import BasePredictor

    @dataclass
    class AttackingOnly(BasePredictor):
        name: str = "attack"
        def score(self, features, element_type):
            return float(features.get("skill", 0.0)) if element_type in (3, 4) else 0.0

    res = Backtester(sm=sm).run(SEASON, GWS, AttackingOnly())
    assert len(res.per_gw) == len(GWS)   # squad initialised every GW
    assert res.total_points > 0          # not the degenerate 0 from a bad pool


def test_frames_separate_signal_from_actual(sm):
    # the panel feature (pre-GW signal) and the GW's actual points are distinct
    # fields from different tables — the backtester must never conflate them.
    with sm() as s:
        s.execute(players.insert(), [{"id": 999, "element_type": MID, "team_id": 1,
                                      "now_cost": 50, "status": "a", "web_name": "Z"}])
        s.execute(player_match_stats.insert(), [{
            "season": SEASON, "element_id": 999, "fixture_id": 7, "gw": 1,
            "player_key": 999, "element_type": MID, "value": 50, "minutes": 90,
            "total_points": 1}])
        s.execute(training_rows.insert(), [{
            "season": SEASON, "player_key": 999, "gw": 1, "element_id": 999,
            "element_type": MID, "hist_n": 5, "features": {"skill": 9.0},
            "feature_version": "t"}])
        s.commit()
    frames = Backtester(sm=sm)._frames(SEASON, [1])
    assert frames[1][999].features["skill"] == 9.0   # pre-GW signal
    assert frames[1][999].actual == 1                # GW outcome (different)


def test_skipped_gws_recorded_for_equal_comparison(sm):
    # GW 99 has no data -> recorded as skipped so every predictor spans the same
    # GW set (fair head-to-head); per_gw length == GWs requested.
    _seed(sm)
    res = Backtester(sm=sm).run(SEASON, [1, 2, 99], FeaturePredictor("skill", "skill"))
    assert len(res.per_gw) == 3
    skipped = [g for g in res.per_gw if g.get("skipped")]
    assert skipped and skipped[0]["gw"] == 99 and skipped[0]["points"] == 0


def test_ensemble_beats_complementary_components(sm):
    # Two signals are each informative for only HALF the players (complementary);
    # a rank-blend that sees both should field a better squad than either alone.
    import numpy as np
    from fpl_engine.model.predictors import FeaturePredictor, RankBlend

    rng = np.random.default_rng(3)
    players_rows, pms_rows, tr_rows = [], [], []
    pid = 0
    for pos, n in ((GK, 4), (DEF, 10), (MID, 10), (FWD, 6)):
        for _ in range(n):
            pid += 1
            skill = float((pid * 7) % 17)          # spread across both halves
            first_half = pid <= 15
            players_rows.append({"id": pid, "element_type": pos, "team_id": (pid % 6) + 1,
                                 "now_cost": 50, "status": "a", "web_name": f"P{pid}"})
            for gw in GWS:
                tr_rows.append({"season": SEASON, "player_key": pid, "gw": gw,
                                "element_id": pid, "element_type": pos, "hist_n": 5,
                                "features": {
                                    "sigA": skill if first_half else float(rng.normal()),
                                    "sigB": skill if not first_half else float(rng.normal()),
                                }, "feature_version": "t"})
                pms_rows.append({"season": SEASON, "element_id": pid,
                                 "fixture_id": gw * 1000 + pid, "gw": gw, "player_key": pid,
                                 "element_type": pos, "value": 50, "minutes": 90,
                                 "total_points": int(skill)})
    with sm() as s:
        s.execute(players.insert(), players_rows)
        s.execute(player_match_stats.insert(), pms_rows)
        s.execute(training_rows.insert(), tr_rows)
        s.commit()

    bt = Backtester(sm=sm)
    A = FeaturePredictor("A", "sigA")
    B = FeaturePredictor("B", "sigB")
    blend = RankBlend("blend", [(A, 1.0), (B, 1.0)])
    a, b, ab = (bt.run(SEASON, GWS, A), bt.run(SEASON, GWS, B), bt.run(SEASON, GWS, blend))
    # the blend (seeing both halves) is at least as good as either partial signal
    assert ab.net_points >= max(a.net_points, b.net_points)
    # and strictly better than the worse one (it captures the stronger signal)
    assert ab.net_points > min(a.net_points, b.net_points)


def test_squad_value_grows_with_rising_prices(sm):
    # prices rise every GW; the engine should track sell value + bank so the
    # squad value (and thus spending power) climbs above the initial 100.0m.
    import numpy as np
    from fpl_engine.model.predictors import FeaturePredictor

    rng = np.random.default_rng(0)
    players_rows, pms_rows, tr_rows = [], [], []
    pid = 0
    for pos, n in ((GK, 4), (DEF, 10), (MID, 10), (FWD, 6)):
        for _ in range(n):
            pid += 1
            skill = float(pid % 9) + 1.0
            players_rows.append({"id": pid, "element_type": pos, "team_id": (pid % 6) + 1,
                                 "now_cost": 50, "status": "a", "web_name": f"P{pid}"})
            for gw in GWS:
                tr_rows.append({"season": SEASON, "player_key": pid, "gw": gw,
                                "element_id": pid, "element_type": pos, "hist_n": 5,
                                "features": {"skill": skill}, "feature_version": "t"})
                # price climbs 2 (0.2m) every GW for everyone
                pms_rows.append({"season": SEASON, "element_id": pid,
                                 "fixture_id": gw * 1000 + pid, "gw": gw, "player_key": pid,
                                 "element_type": pos, "value": 50 + 2 * (gw - 1),
                                 "minutes": 90, "total_points": int(skill)})
    with sm() as s:
        s.execute(players.insert(), players_rows)
        s.execute(player_match_stats.insert(), pms_rows)
        s.execute(training_rows.insert(), tr_rows)
        s.commit()

    res = Backtester(sm=sm).run(SEASON, GWS, FeaturePredictor("skill", "skill"))
    played = [g for g in res.per_gw if not g.get("skipped")]
    values = [g["squad_value"] for g in played]
    assert values[0] == 1000                 # starts at the £100.0m cap
    assert values[-1] > values[0]            # value (spending power) grew


def test_double_gameweek_actuals_aggregate(sm):
    _seed(sm)
    with sm() as s:
        # give player 1 a second fixture in GW2
        s.execute(player_match_stats.insert(), [{
            "season": SEASON, "element_id": 1, "fixture_id": 2999, "gw": 2,
            "player_key": 1, "element_type": GK, "value": 50, "minutes": 90,
            "total_points": 7}])
        s.commit()
    frames = Backtester(sm=sm)._frames(SEASON, [2])
    base = int(1 % 9) + 1  # player 1's per-fixture points
    assert frames[2][1].actual == base + 7   # both fixtures summed


def test_double_gameweek_doubles_xp_and_sums_actual(sm):
    # One MID has TWO fixtures in GW1 (a double gameweek): the frame sums both
    # actual scores and counts 2 fixtures, and the pooled xP is scaled x2.
    from fpl_engine.backtest.engine import Backtester
    from fpl_engine.model.predictors import FeaturePredictor
    with sm() as s:
        s.execute(players.insert(), [
            {"id": 1, "element_type": MID, "team_id": 1, "now_cost": 50,
             "status": "a", "web_name": "Dgw", "selected_by_percent": 5.0}])
        s.execute(player_match_stats.insert(), [
            {"season": "2025-26", "element_id": 1, "fixture_id": 1001, "gw": 1,
             "player_key": 1, "element_type": MID, "value": 50, "minutes": 90,
             "total_points": 6},
            {"season": "2025-26", "element_id": 1, "fixture_id": 1002, "gw": 1,
             "player_key": 1, "element_type": MID, "value": 50, "minutes": 90,
             "total_points": 5}])
        # training_rows is keyed per (season, player_key, gw): one row, signal=4.0
        s.execute(training_rows.insert(), [
            {"season": "2025-26", "player_key": 1, "gw": 1, "element_id": 1,
             "element_type": MID, "hist_n": 5, "features": {"sig": 4.0},
             "feature_version": "t"}])
        s.commit()

    bt = Backtester(sm=sm)
    frames = bt._frames("2025-26", [1])
    assert frames[1][1].fixtures == 2
    assert frames[1][1].actual == 11        # 6 + 5 summed across both fixtures

    pool, actual = bt._pool(frames[1], set(), {}, FeaturePredictor("sig", "sig"))
    p = next(pp for pp in pool if pp.id == 1)
    assert p.xp[0] == 8.0                    # 4.0 signal x 2 fixtures
    assert actual[1] == 11


def test_opponent_factors_are_causal_and_normalised(sm):
    from datetime import datetime, timezone
    from fpl_engine.backtest.engine import Backtester
    from fpl_engine.db.models import team_match_stats
    with sm() as s:
        # team 1 leaks goals (concedes 3/match), team 2 is tight (concedes 0).
        s.execute(team_match_stats.insert(), [
            {"season": "2025-26", "fixture_id": g * 10 + 1, "team_id": 1, "gw": g,
             "was_home": True, "goals_for": 1, "goals_against": 3} for g in range(1, 5)] + [
            {"season": "2025-26", "fixture_id": g * 10 + 2, "team_id": 2, "gw": g,
             "was_home": False, "goals_for": 1, "goals_against": 0} for g in range(1, 5)])
        s.commit()
    fac = Backtester(sm=sm)._opponent_factors("2025-26")
    # GW1 uses ONLY the shrinkage prior (no prior matches) -> ~1.0 for both teams.
    assert abs(fac[(1, 1)][1] - 1.0) < 1e-9
    # by GW4, team 1's defensive-leak factor exceeds team 2's (trailing concessions).
    assert fac[(4, 1)][1] > fac[(4, 2)][1]
    assert fac[(4, 1)][1] > 1.0 and fac[(4, 2)][1] < 1.0


def test_free_hit_chip_measured_and_added(sm):
    from fpl_engine.backtest.engine import Backtester
    from fpl_engine.model.predictors import FeaturePredictor
    _seed(sm)
    res = Backtester(sm=sm, free_hit=True).run(SEASON, GWS, FeaturePredictor("skill", "skill"))
    # per-GW free-hit value is measured, and the chip bonus includes a free_hit entry
    assert all("fh_uplift" in g for g in res.per_gw if "skipped" not in g)
    assert "free_hit" in res.chips
    assert res.net_with_chips >= res.net_points        # chips never reduce the total
