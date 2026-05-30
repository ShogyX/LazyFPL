"""Squad/XI MILP: constraints provably respected, objective maximised (no DB)."""

from collections import Counter

from fpl_engine.optimise.squad import BUDGET, SquadOptimizer, Candidate

GK, DEF, MID, FWD = 1, 2, 3, 4


def _pool() -> list[Candidate]:
    cands: list[Candidate] = []
    cid = 0

    def add(pos, n, base_xp):
        nonlocal cid
        for k in range(n):
            cid += 1
            cands.append(Candidate(
                id=cid, position=pos, price=50, team_id=(cid % 6) + 1,
                xp=base_xp - k * 0.3, p_play=1.0, name=f"p{cid}"))

    add(GK, 3, 4.0)
    add(DEF, 8, 6.0)
    add(MID, 8, 8.0)
    add(FWD, 5, 7.0)
    return cands


def test_squad_respects_all_constraints():
    sol = SquadOptimizer().solve(_pool())
    assert sol.feasible
    assert len(sol.picks) == 15

    pos_counts = Counter(p.position for p in sol.picks)
    assert pos_counts == {GK: 2, DEF: 5, MID: 5, FWD: 3}

    assert sol.total_cost <= BUDGET
    team_counts = Counter(p.team_id for p in sol.picks)
    assert max(team_counts.values()) <= 3

    starters = [p for p in sol.picks if p.is_start]
    assert len(starters) == 11
    sc = Counter(p.position for p in starters)
    assert sc[GK] == 1
    assert 3 <= sc[DEF] <= 5
    assert 2 <= sc[MID] <= 5
    assert 1 <= sc[FWD] <= 3


def test_captain_is_highest_xp_starter():
    sol = SquadOptimizer().solve(_pool())
    starters = [p for p in sol.picks if p.is_start]
    caps = [p for p in sol.picks if p.is_captain]
    vices = [p for p in sol.picks if p.is_vice]
    assert len(caps) == 1 and len(vices) == 1
    captain = caps[0]
    assert captain.is_start
    assert captain.xp == max(p.xp for p in starters)
    assert vices[0].id != captain.id
    # xi_xp counts the captain twice (objective doubles the captain).
    expected = sum(p.xp for p in starters) + captain.xp
    assert abs(sol.xi_xp - expected) < 1e-6


def test_budget_binds():
    # Force a tight budget: 15 players at 50 = 750; cap at 740 -> infeasible.
    pool = _pool()
    sol = SquadOptimizer(budget=740).solve(pool)
    assert not sol.feasible  # cannot field 15 within 740 at price 50 each


def test_max_three_per_club_enforced():
    # 5 high-xP midfielders sit on team 1 (tempting a stack), but enough MIDs
    # exist elsewhere to fill the quota under the max-3-per-club cap.
    cands = []
    cid = 0
    def add(pos, n, base, team_of):
        nonlocal cid
        for k in range(n):
            cid += 1
            cands.append(Candidate(id=cid, position=pos, price=50,
                                   team_id=team_of(k), xp=base - k * 0.1, name=f"p{cid}"))
    add(GK, 3, 4.0, lambda k: 2 + (k % 3))           # teams 2-4
    add(DEF, 8, 6.0, lambda k: 2 + (k % 5))          # teams 2-6
    add(MID, 9, 9.0, lambda k: 1 if k < 5 else 2 + (k % 4))  # 5 on team 1
    add(FWD, 5, 7.0, lambda k: 2 + (k % 5))          # teams 2-6
    sol = SquadOptimizer().solve(cands)
    assert sol.feasible
    team1 = [p for p in sol.picks if p.team_id == 1]
    assert len(team1) <= 3
