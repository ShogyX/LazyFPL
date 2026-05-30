"""Injury/suspension awareness in the optimiser candidate loaders."""

from sqlalchemy import insert

from fpl_engine.db.models import players, predictions_player_gw
from fpl_engine.optimise.loader import load_candidates, load_horizon_candidates

GK, DEF, MID, FWD = 1, 2, 3, 4
SEASON = "2025-26"


def _seed(sm):
    prows = [
        {"id": 1, "web_name": "Fit", "team_id": 1, "element_type": MID,
         "now_cost": 80, "status": "a", "selected_by_percent": 30.0},
        {"id": 2, "web_name": "Injured", "team_id": 2, "element_type": MID,
         "now_cost": 90, "status": "i", "selected_by_percent": 20.0},
        {"id": 3, "web_name": "Doubtful", "team_id": 3, "element_type": MID,
         "now_cost": 70, "status": "d", "selected_by_percent": 15.0},
        {"id": 4, "web_name": "Suspended", "team_id": 4, "element_type": FWD,
         "now_cost": 85, "status": "s", "selected_by_percent": 10.0},
    ]
    xp = {1: 8.0, 2: 9.0, 3: 6.0, 4: 7.0}
    pred = []
    for gw in (24, 25):
        for pid in (1, 2, 3, 4):
            pred.append({"model_version": "vt", "season": SEASON, "gw": gw,
                         "player_key": 9000 + pid, "element_id": pid,
                         "element_type": prows[pid - 1]["element_type"],
                         "xp_next1": xp[pid], "pred_minutes": 85})
    with sm() as s:
        s.execute(insert(players), prows)
        s.execute(insert(predictions_player_gw), pred)
        s.commit()


def test_load_candidates_drops_injured_and_suspended(sm):
    _seed(sm)
    cands = {c.id: c for c in load_candidates(SEASON, 24, model_version="vt", sm=sm)}
    assert set(cands) == {1, 3}          # injured(2) + suspended(4) dropped
    assert cands[1].xp == 8.0            # available -> full xP
    assert cands[3].xp == 3.0            # doubtful -> 0.5 x 6.0


def test_load_candidates_gate_off_keeps_all(sm):
    _seed(sm)
    cands = load_candidates(SEASON, 24, model_version="vt", sm=sm, only_available=False)
    assert {c.id for c in cands} == {1, 2, 3, 4}   # no gate -> raw pool


def test_horizon_excludes_unheld_unavailable(sm):
    _seed(sm)
    pool = {p.id: p for p in load_horizon_candidates(
        SEASON, [24, 25], model_version="vt", sm=sm)}
    assert 2 not in pool and 4 not in pool   # injured/suspended, not held -> gone
    assert pool[1].xp == [8.0, 8.0]
    assert pool[3].xp == [3.0, 3.0]          # doubtful halved every GW


def test_horizon_keeps_held_injured_at_zero_xp(sm):
    _seed(sm)
    pool = {p.id: p for p in load_horizon_candidates(
        SEASON, [24, 25], model_version="vt", sm=sm, include_ids={2})}
    # Held injured player stays (sellable) but with zeroed xP so it's dropped.
    assert 2 in pool
    assert pool[2].xp == [0.0, 0.0]
