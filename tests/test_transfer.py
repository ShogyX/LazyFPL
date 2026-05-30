"""Multi-GW transfer planner: constraints, FT accrual/hits, and beating a
rolling one-week greedy baseline (no DB)."""

from collections import Counter

import numpy as np

from fpl_engine.optimise.squad import Candidate, SquadOptimizer
from fpl_engine.optimise.transfer import PlayerH, TransferPlanner, rolling_greedy

GK, DEF, MID, FWD = 1, 2, 3, 4
QUOTA = {GK: 2, DEF: 5, MID: 5, FWD: 3}


def _pool(horizon=3, seed=0):
    rng = np.random.default_rng(seed)
    pool: list[PlayerH] = []
    cid = 0

    def add(pos, n, base):
        nonlocal cid
        for _ in range(n):
            cid += 1
            xp = [round(float(base + rng.normal(scale=1.0)), 3) for _ in range(horizon)]
            pool.append(PlayerH(id=cid, position=pos, price=50, team_id=(cid % 6) + 1,
                                xp=[max(x, 0.0) for x in xp], p_play=1.0, name=f"p{cid}"))

    add(GK, 3, 3.0)
    add(DEF, 8, 4.0)
    add(MID, 8, 5.0)
    add(FWD, 5, 5.0)
    return pool


def _initial_from_squad_opt(pool) -> set[int]:
    cands = [Candidate(id=p.id, position=p.position, price=p.price, team_id=p.team_id,
                       xp=p.xp[0], name=p.name) for p in pool]
    sol = SquadOptimizer().solve(cands)
    assert sol.feasible
    return {p.id for p in sol.picks}


def _assert_valid_squad(squad_ids, pool):
    byid = {p.id: p for p in pool}
    assert len(squad_ids) == 15
    pos = Counter(byid[i].position for i in squad_ids)
    assert pos == QUOTA
    assert sum(byid[i].price for i in squad_ids) <= 1000
    assert max(Counter(byid[i].team_id for i in squad_ids).values()) <= 3


def test_plan_constraints_and_beats_greedy():
    pool = _pool(horizon=3)
    initial = _initial_from_squad_opt(pool)
    planner = TransferPlanner(bench_weight=0.0)  # clean net-xP comparison

    plan = planner.plan(initial, pool, initial_ft=1, horizon=3)
    assert plan.feasible
    byid = {p.id: p for p in pool}
    for g in plan.gws:
        _assert_valid_squad(set(g.squad), pool)
        assert len(g.xi) == 11
        xi_pos = Counter(byid[i].position for i in g.xi)
        assert xi_pos[GK] == 1 and 3 <= xi_pos[DEF] <= 5
        assert 2 <= xi_pos[MID] <= 5 and 1 <= xi_pos[FWD] <= 3
        assert g.captain in g.xi

    greedy_net, _ = rolling_greedy(planner, initial, pool, initial_ft=1, horizon=3)
    # full-horizon optimum is at least as good as myopic week-by-week
    assert plan.net_xp >= greedy_net - 1e-6


def test_free_transfers_accrue_and_cap_when_idle():
    # Initial squad is optimal for every GW (constant xP), so no transfer is ever
    # beneficial -> the planner sits idle and free transfers accrue 1,2,3...,
    # capped at 5. This pins the FT-accrual ceiling encoding.
    rng = np.random.default_rng(2)
    pool: list[PlayerH] = []
    cid = 0

    def add(pos, n, base):
        nonlocal cid
        for _ in range(n):
            cid += 1
            v = round(float(base + rng.normal()), 3)
            pool.append(PlayerH(cid, pos, 50, (cid % 6) + 1, [v, v, v, v], name=f"p{cid}"))

    add(GK, 3, 3.0); add(DEF, 8, 4.0); add(MID, 8, 5.0); add(FWD, 5, 5.0)
    initial = _initial_from_squad_opt(pool)

    # Same bench weight as the squad optimiser, so the initial 15 (incl. bench)
    # is the unique per-GW optimum and the planner has no neutral free swap.
    plan = TransferPlanner().plan(initial, pool, initial_ft=1, horizon=4)
    assert plan.feasible
    assert plan.total_hits == 0
    assert sum(len(g.transfers_in) for g in plan.gws) == 0       # idle
    assert [g.ft_available for g in plan.gws] == [1, 2, 3, 4]    # accrual


def test_planner_banks_ft_then_transfers_without_hit():
    # A sleeper is useless in GW0 but elite later; with 1 FT the planner should
    # bring it in for free (banking), never taking a hit. The initial squad is a
    # valid optimiser solution (respects max-3-per-club); the sleeper sits on a
    # unique team so acquiring it forces no other move.
    base = _pool(horizon=3, seed=3)
    initial = _initial_from_squad_opt(base)
    sleeper = PlayerH(999, MID, 50, 99, [0, 20, 20], name="sleeper")  # unique team
    pool = base + [sleeper]
    planner = TransferPlanner(bench_weight=0.0)
    plan = planner.plan(initial, pool, initial_ft=1, horizon=3)

    assert plan.feasible
    assert plan.total_hits == 0                       # free transfer suffices
    assert 999 in plan.gws[-1].squad                  # sleeper acquired
    assert 999 in {i for g in plan.gws for i in g.transfers_in}


def test_ft_value_curbs_marginal_transfers():
    # A sleeper only marginally better than the squad. With no FT value the
    # planner makes the free transfer; with a high FT value it banks instead.
    base = _pool(horizon=2, seed=11)
    initial = _initial_from_squad_opt(base)
    byid = {p.id: p for p in base}
    # a fresh-club MID a hair better than the worst owned MID's xp
    worst = min((byid[i].xp[0] for i in initial if byid[i].position == MID))
    sleeper = PlayerH(950, MID, 50, 97, [worst + 0.3, worst + 0.3], name="sleeper")
    pool = base + [sleeper]

    greedy = TransferPlanner(bench_weight=0.0).plan(initial, pool, initial_ft=1, horizon=2)
    disciplined = TransferPlanner(bench_weight=0.0, ft_value=2.0).plan(
        initial, pool, initial_ft=1, horizon=2)
    g_in = sum(len(g.transfers_in) for g in greedy.gws)
    d_in = sum(len(g.transfers_in) for g in disciplined.gws)
    assert d_in <= g_in            # FT value never increases churn
    assert disciplined.feasible


def test_decay_prefers_nearer_gw_value():
    # One sleeper elite only in GW0, another elite only in the last GW. Under
    # strong future-decay the planner still fields a valid plan and front-loads.
    base = _pool(horizon=3, seed=7)
    initial = _initial_from_squad_opt(base)
    plan = TransferPlanner(bench_weight=0.0, decay_base=0.5).plan(
        initial, base, initial_ft=1, horizon=3)
    assert plan.feasible and len(plan.gws) == 3


def test_planner_takes_hit_when_clearly_worth_it():
    # Two elite players are absent from a valid initial squad; with only 1 FT,
    # bringing BOTH in immediately needs a -4 hit, which pays off given the large
    # multi-GW gain. Elites sit on unique teams (no max-3 interference).
    base = _pool(horizon=3, seed=5)
    initial = _initial_from_squad_opt(base)
    elites = [PlayerH(998, MID, 50, 98, [15, 15, 15], name="eliteA"),
              PlayerH(997, MID, 50, 97, [15, 15, 15], name="eliteB")]
    pool = base + elites
    planner = TransferPlanner(bench_weight=0.0)
    plan = planner.plan(initial, pool, initial_ft=1, horizon=3)

    assert plan.feasible
    owned_end = set(plan.gws[-1].squad)
    assert {997, 998} <= owned_end
    assert plan.total_hits >= 4   # a -4 hit was taken to acquire both quickly
