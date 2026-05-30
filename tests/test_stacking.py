"""Per-position stacking meta-learner: fit on base-predictor outputs vs points."""

import numpy as np
from sqlalchemy import insert

from fpl_engine.db.models import players, player_match_stats, training_rows
from fpl_engine.model.predictors import FeaturePredictor, Predictor
from fpl_engine.model.stacking import StackBlend, fit_stack

GK, DEF, MID, FWD = 1, 2, 3, 4
SEASON = "2025-26"
GWS = [1, 2, 3, 4, 5]


def _seed(sm):
    """'skill' feature == realised points (a true signal); 'noise' is random."""
    rng = np.random.default_rng(0)
    roster, pid = [], 0
    for pos, n in ((GK, 6), (DEF, 12), (MID, 12), (FWD, 8)):
        for _ in range(n):
            pid += 1
            roster.append((pid, pos))
    prows, pms, trs = [], [], []
    for pid, pos in roster:
        skill = float(pid % 9) + 1.0
        prows.append({"id": pid, "element_type": pos, "team_id": (pid % 6) + 1,
                      "now_cost": 50, "status": "a", "web_name": f"P{pid}",
                      "selected_by_percent": 5.0})
        for gw in GWS:
            pms.append({"season": SEASON, "element_id": pid, "fixture_id": gw * 1000 + pid,
                        "gw": gw, "player_key": pid, "element_type": pos, "value": 50,
                        "minutes": 90, "total_points": int(skill)})
            trs.append({"season": SEASON, "player_key": pid, "gw": gw, "element_id": pid,
                        "element_type": pos, "hist_n": 5,
                        "features": {"skill": skill, "noise": float(rng.normal())},
                        "feature_version": "t"})
    with sm() as s:
        s.execute(insert(players), prows)
        s.execute(insert(player_match_stats), pms)
        s.execute(insert(training_rows), trs)
        s.commit()


def test_fit_stack_learns_to_trust_signal_over_noise(sm):
    _seed(sm)
    base = {"skill": FeaturePredictor("skill", "skill"),
            "noise": FeaturePredictor("noise", "noise")}
    stack = fit_stack(base, SEASON, GWS, sm=sm)
    assert isinstance(stack, StackBlend) and isinstance(stack, Predictor)

    # For an attacking position, the skill coefficient should dominate noise.
    cell = stack.cells[MID]
    assert not cell.equal_weight
    skill_w = abs(cell.coef[cell.names.index("skill")])
    noise_w = abs(cell.coef[cell.names.index("noise")])
    assert skill_w > noise_w * 3

    # And the blended score ranks a high-skill player above a low-skill one.
    items = [(1, {"skill": 9.0, "noise": 0.5}, MID),
             (2, {"skill": 1.0, "noise": 0.9}, MID)]
    out = stack.score_frame(items)
    assert out[1] > out[2]


def test_fit_stack_falls_back_to_equal_weights_when_sparse(sm):
    # No data -> every position cell is the equal-weight fallback (no crash).
    base = {"a": FeaturePredictor("a", "skill"), "b": FeaturePredictor("b", "noise")}
    stack = fit_stack(base, SEASON, GWS, sm=sm)
    assert all(stack.cells[p].equal_weight for p in (GK, DEF, MID, FWD))
    out = stack.score_frame([(1, {"skill": 4.0, "noise": 2.0}, FWD)])
    assert out[1] == (4.0 + 2.0) / 2     # mean of base signals


def test_calibrate_aligns_single_predictor_per_position(sm):
    from fpl_engine.model.stacking import calibrate
    _seed(sm)
    cal = calibrate(FeaturePredictor("skill", "skill"), SEASON, GWS, sm=sm)
    # per-position cells fitted (not the equal-weight fallback)
    assert not cal.cells[MID].equal_weight
    # higher skill -> higher calibrated points, and output is on a points-like scale
    out = cal.score_frame([(1, {"skill": 9.0}, MID), (2, {"skill": 1.0}, MID)])
    assert out[1] > out[2]
    assert 0.0 < out[1] < 20.0          # realistic points magnitude after calibration


def test_feature_augmented_stack_includes_meta_features(sm):
    _seed(sm)
    stack = fit_stack({"skill": FeaturePredictor("skill", "skill")}, SEASON, GWS,
                      meta_features=("noise",), sm=sm)
    assert stack.meta_features == ("noise",)
    assert "skill" in stack.cells[MID].names and "noise" in stack.cells[MID].names
    # scores read the meta-feature from each item without error
    out = stack.score_frame([(1, {"skill": 9.0, "noise": 0.5}, MID),
                             (2, {"skill": 1.0, "noise": -0.5}, MID)])
    assert out[1] == out[1] and out[1] > out[2]   # finite; skill still dominates
