"""Recommendation generation: planner-from-roster vs hold baseline, stored."""

import numpy as np
from sqlalchemy import select

from fpl_engine.db.models import recommendations
from fpl_engine.model.recommend import RecommendationEngine
from fpl_engine.optimise.squad import Candidate, SquadOptimizer
from fpl_engine.optimise.transfer import PlayerH

GK, DEF, MID, FWD = 1, 2, 3, 4


def _pool(horizon=4, seed=0):
    rng = np.random.default_rng(seed)
    pool, cid = [], 0

    def add(pos, n, base):
        nonlocal cid
        for _ in range(n):
            cid += 1
            xp = [max(round(float(base + rng.normal()), 3), 0.0) for _ in range(horizon)]
            pool.append(PlayerH(cid, pos, 50, (cid % 6) + 1, xp, name=f"p{cid}"))

    add(GK, 3, 3.0); add(DEF, 8, 4.0); add(MID, 8, 5.0); add(FWD, 5, 5.0)
    return pool


def _roster(pool) -> set[int]:
    cands = [Candidate(p.id, p.position, p.price, p.team_id, p.xp[0], name=p.name)
             for p in pool]
    sol = SquadOptimizer().solve(cands)
    return {p.id for p in sol.picks}


def test_recommendation_generated_and_stored(sm):
    pool = _pool()
    roster = _roster(pool)
    engine = RecommendationEngine(sm=sm, model_version="vt")
    rec = engine.generate("2025-26", 24, roster, horizon=4, candidates=pool, entry_id=7)

    assert rec.kind in ("transfer", "captain")
    assert rec.rationale["captain"]["name"]
    # plan is at least as good as holding the roster
    assert rec.rationale["plan_net_xp"] >= rec.rationale["hold_net_xp"] - 1e-6
    assert rec.ev >= -1e-6

    with sm() as s:
        row = s.execute(select(recommendations).where(
            recommendations.c.entry_id == 7)).one()
    assert row.kind == rec.kind
    assert row.target_event == 24
    assert row.rationale["captain"]["name"] == rec.rationale["captain"]["name"]


def test_hold_infeasible_roster_yields_no_uplift(sm):
    # Roster has a valid 2/5/5/3 composition but 4 players from team 1, which
    # breaches max-3-per-club -> the locked "hold" is infeasible. The engine must
    # report uplift=None (the plan can fix it via a transfer; the hold cannot).
    def P(pid, pos, team):
        return PlayerH(pid, pos, 50, team, [5.0, 5.0, 5.0, 5.0], name=f"p{pid}")

    pool = (
        [P(1, GK, 1), P(2, GK, 2), P(3, GK, 3)]
        + [P(10, DEF, 1)] + [P(11 + k, DEF, (k % 5) + 2) for k in range(7)]
        + [P(20, MID, 1)] + [P(21 + k, MID, (k % 5) + 2) for k in range(7)]
        + [P(30, FWD, 1)] + [P(31 + k, FWD, (k % 5) + 2) for k in range(4)]
    )
    # 4 team-1 members (1,10,20,30) -> breaches max-3 when held.
    roster = {1, 2, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32}
    rec = RecommendationEngine(sm=sm, model_version="vt").generate(
        "2025-26", 24, roster, horizon=4, candidates=pool, entry_id=9)

    assert rec.rationale["hold_net_xp"] is None
    assert rec.rationale["uplift"] is None
    assert rec.ev == 0.0


def test_recommendation_rejects_invalid_roster(sm):
    pool = _pool()
    engine = RecommendationEngine(sm=sm, model_version="vt")
    try:
        engine.generate("2025-26", 24, {1, 2, 3}, horizon=4, candidates=pool)
        assert False, "expected ValueError for sub-15 roster"
    except ValueError as e:
        assert "15" in str(e)
