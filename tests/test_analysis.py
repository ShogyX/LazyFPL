"""Predictor correlation / complementarity analysis (DB-seeded)."""

import numpy as np

from fpl_engine.db.models import players, player_match_stats, training_rows
from fpl_engine.model.analysis import PredictorAnalysis
from fpl_engine.model.predictors import FeaturePredictor

GK, DEF, MID, FWD = 1, 2, 3, 4
SEASON = "2025-26"
GWS = [1, 2, 3, 4, 5]


def _seed(sm):
    rng = np.random.default_rng(0)
    players_rows, pms_rows, tr_rows = [], [], []
    pid = 0
    for pos, n in ((GK, 4), (DEF, 10), (MID, 10), (FWD, 6)):
        for _ in range(n):
            pid += 1
            players_rows.append({"id": pid, "element_type": pos, "team_id": (pid % 6) + 1,
                                 "now_cost": 50, "status": "a", "web_name": f"P{pid}"})
            for gw in GWS:
                actual = int(max(0, round((pid % 9) + rng.normal())))
                tr_rows.append({"season": SEASON, "player_key": pid, "gw": gw,
                                "element_id": pid, "element_type": pos, "hist_n": 5,
                                "features": {
                                    # 'good' tracks actual; 'copy' duplicates it
                                    # (redundant); 'noise' is independent.
                                    "good": float(actual), "copy": float(actual),
                                    "noise": float(rng.normal())},
                                "feature_version": "t"})
                pms_rows.append({"season": SEASON, "element_id": pid,
                                 "fixture_id": gw * 1000 + pid, "gw": gw,
                                 "player_key": pid, "element_type": pos, "value": 50,
                                 "minutes": 90, "total_points": actual})
    with sm() as s:
        s.execute(players.insert(), players_rows)
        s.execute(player_match_stats.insert(), pms_rows)
        s.execute(training_rows.insert(), tr_rows)
        s.commit()


def test_analysis_separates_signal_quality_and_redundancy(sm):
    _seed(sm)
    preds = {"good": FeaturePredictor("good", "good"),
             "copy": FeaturePredictor("copy", "copy"),
             "noise": FeaturePredictor("noise", "noise")}
    rep = PredictorAnalysis(sm=sm).analyse(SEASON, GWS, preds)

    assert rep.n_rows == 30 * len(GWS)
    # 'good' predicts points; 'noise' doesn't
    assert rep.overall_ic["good"] > 0.5
    assert abs(rep.overall_ic["noise"]) < 0.2
    # 'good' and 'copy' are redundant (near-perfect signal correlation)
    assert rep.signal_correlation["good"]["copy"] > 0.99
    # 'good' wins most GWs
    assert rep.fraction_best["good"] >= rep.fraction_best["noise"]
    # per-position IC populated for the four positions
    assert set(rep.per_position_ic["good"]) == {GK, DEF, MID, FWD}


def test_complementarity_pair_detected(sm):
    # two signals each good for a DIFFERENT half of players -> complementary
    rng = np.random.default_rng(1)
    players_rows, pms_rows, tr_rows = [], [], []
    for pid in range(1, 31):
        pos = GK if pid <= 4 else DEF if pid <= 14 else MID if pid <= 24 else FWD
        players_rows.append({"id": pid, "element_type": pos, "team_id": (pid % 6) + 1,
                             "now_cost": 50, "status": "a", "web_name": f"P{pid}"})
        first_half = pid <= 15
        for gw in GWS:
            actual = int(max(0, round((pid % 9) + rng.normal())))
            # sigA informative for first half only; sigB for second half only
            tr_rows.append({"season": SEASON, "player_key": pid, "gw": gw,
                            "element_id": pid, "element_type": pos, "hist_n": 5,
                            "features": {
                                "sigA": float(actual) if first_half else float(rng.normal()),
                                "sigB": float(actual) if not first_half else float(rng.normal()),
                            }, "feature_version": "t"})
            pms_rows.append({"season": SEASON, "element_id": pid,
                             "fixture_id": gw * 1000 + pid, "gw": gw, "player_key": pid,
                             "element_type": pos, "value": 50, "minutes": 90,
                             "total_points": actual})
    with sm() as s:
        s.execute(players.insert(), players_rows)
        s.execute(player_match_stats.insert(), pms_rows)
        s.execute(training_rows.insert(), tr_rows)
        s.commit()

    preds = {"sigA": FeaturePredictor("sigA", "sigA"),
             "sigB": FeaturePredictor("sigB", "sigB")}
    rep = PredictorAnalysis(sm=sm).analyse(SEASON, GWS, preds)
    # complementary signals: low signal correlation
    assert rep.signal_correlation["sigA"]["sigB"] < 0.5
