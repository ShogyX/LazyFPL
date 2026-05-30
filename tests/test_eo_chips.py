"""Risk/EO overlay (8.4) + chip timing (8.3) — pure, no DB."""

from collections import Counter

from fpl_engine.optimise.chips import ChipPlanner, best_xi_value, half_of
from fpl_engine.optimise.squad import Candidate, SquadOptimizer
from fpl_engine.optimise.transfer import PlayerH

GK, DEF, MID, FWD = 1, 2, 3, 4


def _eo_pool():
    """Players where xP is uniform within a position but ownership varies, so
    the EO knob (not xP) decides who starts."""
    cands, cid = [], 0

    def add(pos, n):
        nonlocal cid
        for _ in range(n):
            cid += 1
            # ownership ramps with id; xp identical within position
            cands.append(Candidate(cid, pos, 50, (cid % 6) + 1, xp=5.0,
                                   ownership=float(cid), name=f"p{cid}"))

    add(GK, 3); add(DEF, 8); add(MID, 8); add(FWD, 5)
    return cands


def _avg_ownership(sol):
    starters = [p for p in sol.picks if p.is_start]
    # ownership isn't on Pick; map back by id via the pool in the test
    return starters


def test_eo_weight_shifts_template_vs_differential():
    pool = _eo_pool()
    own = {c.id: c.ownership for c in pool}

    template = SquadOptimizer(eo_weight=+1.0).solve(pool)
    differential = SquadOptimizer(eo_weight=-1.0).solve(pool)
    assert template.feasible and differential.feasible

    tmpl_own = sum(own[p.id] for p in template.picks if p.is_start)
    diff_own = sum(own[p.id] for p in differential.picks if p.is_start)
    # +ve weight -> higher-ownership XI (template); -ve -> lower (differential)
    assert tmpl_own > diff_own


def test_eo_zero_is_pure_xp_feasible():
    pool = _eo_pool()
    sol = SquadOptimizer(eo_weight=0.0).solve(pool)
    assert sol.feasible
    assert len([p for p in sol.picks if p.is_start]) == 11


def test_eo_overlay_never_breaks_constraints():
    # A large EO weight changes the objective but must still yield a legal squad.
    pool = _eo_pool()
    for eo in (-5.0, 5.0):
        sol = SquadOptimizer(eo_weight=eo).solve(pool)
        assert sol.feasible
        assert len(sol.picks) == 15
        assert Counter(p.position for p in sol.picks) == {GK: 2, DEF: 5, MID: 5, FWD: 3}
        assert sol.total_cost <= 1000
        assert max(Counter(p.team_id for p in sol.picks).values()) <= 3
        assert len([p for p in sol.picks if p.is_start]) == 11


# --- chips ---
def test_best_xi_value_picks_top_formation():
    # 2 GK, 5 DEF, 5 MID, 3 FWD with clear xp ordering
    players = ([(GK, 5), (GK, 1)]
               + [(DEF, x) for x in (6, 5, 4, 3, 2)]
               + [(MID, x) for x in (9, 8, 7, 6, 1)]
               + [(FWD, x) for x in (8, 7, 2)])
    xi_xp, cap_xp, bench_xp = best_xi_value(players)
    assert cap_xp == 9                       # best starter
    total = sum(xp for _, xp in players)
    assert abs((xi_xp + bench_xp) - total) < 1e-9   # bench = remainder
    assert xi_xp > bench_xp


def _chip_pool(horizon=3):
    cands, cid = [], 0

    def add(pos, n, xps):
        nonlocal cid
        for _ in range(n):
            cid += 1
            cands.append(PlayerH(cid, pos, 50, (cid % 6) + 1, list(xps), name=f"p{cid}"))

    # baseline players flat across GWs
    add(GK, 3, [3, 3, 3]); add(DEF, 8, [4, 4, 4])
    add(MID, 7, [5, 5, 5]); add(FWD, 5, [5, 5, 5])
    return cands


def test_chip_timing_targets_ceiling_and_windows():
    pool = _chip_pool(horizon=3)
    # a star whose captain ceiling spikes in GW index 1 (=> GW 2)
    star = PlayerH(999, MID, 50, 6, [5, 30, 5], name="star")
    pool.append(star)
    # roster = a valid 15 incl. the star
    from fpl_engine.optimise.squad import SquadOptimizer as SO
    init = SO().solve([Candidate(p.id, p.position, p.price, p.team_id, p.xp[1])
                       for p in pool])
    roster = {p.id for p in init.picks}
    assert 999 in roster

    gws = [1, 2, 3]
    recs = ChipPlanner().recommend(pool, roster, gws)
    # Triple Captain should target the ceiling GW (gw 2, the star's spike)
    assert recs["triple_captain"].gw == 2
    assert recs["triple_captain"].value >= 30
    assert all(r.half == 1 for r in recs.values())   # all GWs in first half


def test_chip_half_window_filter():
    pool = _chip_pool(horizon=2)
    roster = {p.id for p in __import__("fpl_engine.optimise.squad", fromlist=["SquadOptimizer"])
              .SquadOptimizer().solve(
                  [Candidate(p.id, p.position, p.price, p.team_id, p.xp[0]) for p in pool]).picks}
    # GW 20 and 21 are second-half; filtering to half 1 yields no recs
    recs_half2 = ChipPlanner().recommend(pool, roster, [20, 21], allowed_half=2)
    assert all(r.half == 2 for r in recs_half2.values())
    recs_half1_on_h2 = ChipPlanner().recommend(pool, roster, [20, 21], allowed_half=1)
    assert recs_half1_on_h2 == {}                    # nothing in half 1


def test_half_of():
    assert half_of(1) == 1 and half_of(19) == 1
    assert half_of(20) == 2 and half_of(38) == 2


def test_bench_boost_targets_high_bench_gw():
    # Make the whole squad's xP spike in GW index 2 (=> GW 3) so the bench
    # (the 4 non-starters) is most valuable there.
    pool, cid = [], 0

    def add(pos, n, xps):
        nonlocal cid
        for _ in range(n):
            cid += 1
            pool.append(PlayerH(cid, pos, 50, (cid % 6) + 1, list(xps), name=f"p{cid}"))

    add(GK, 3, [2, 2, 6]); add(DEF, 8, [3, 3, 7])
    add(MID, 8, [4, 4, 8]); add(FWD, 5, [4, 4, 8])
    init = SquadOptimizer().solve(
        [Candidate(p.id, p.position, p.price, p.team_id, p.xp[2]) for p in pool])
    roster = {p.id for p in init.picks}
    recs = ChipPlanner().recommend(pool, roster, [1, 2, 3])
    assert recs["bench_boost"].gw == 3      # bench worth most when everyone hauls


def test_free_hit_value_nonpositive_when_no_uplift():
    # Roster IS the one-week-optimal squad every GW -> a free hit cannot beat it,
    # so its uplift value should be <= 0 (signal: don't play it).
    pool, cid = [], 0

    def add(pos, n, base):
        nonlocal cid
        for _ in range(n):
            cid += 1
            pool.append(PlayerH(cid, pos, 50, (cid % 6) + 1, [base, base], name=f"p{cid}"))

    add(GK, 3, 3.0); add(DEF, 8, 4.0); add(MID, 8, 5.0); add(FWD, 5, 5.0)
    init = SquadOptimizer().solve(
        [Candidate(p.id, p.position, p.price, p.team_id, p.xp[0]) for p in pool])
    roster = {p.id for p in init.picks}
    recs = ChipPlanner().recommend(pool, roster, [1, 2])
    assert recs["free_hit"].value <= 1e-6
