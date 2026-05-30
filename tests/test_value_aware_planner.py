"""Value-aware multi-GW planner: real bank + sell-value drives buying power."""

import numpy as np

from fpl_engine.optimise.squad import BUDGET, Candidate, SquadOptimizer, selling_price
from fpl_engine.optimise.transfer import PlayerH, TransferPlanner

GK, DEF, MID, FWD = 1, 2, 3, 4


def _balanced_pool(horizon=2, seed=0):
    """A pool that admits a £100m 2/5/5/3 squad at 50/each + a high-price target."""
    rng = np.random.default_rng(seed)
    pool: list[PlayerH] = []
    cid = 0

    def add(pos, n, base, price=50, team_off=0):
        nonlocal cid
        for _ in range(n):
            cid += 1
            xp = [max(round(float(base + rng.normal(scale=0.5)), 3), 0.0)
                  for _ in range(horizon)]
            pool.append(PlayerH(cid, pos, price, ((cid + team_off) % 6) + 1,
                                xp, name=f"p{cid}"))

    add(GK, 3, 3.0)
    add(DEF, 8, 4.0)
    add(MID, 8, 5.0)
    add(FWD, 5, 5.0)
    return pool


def _initial(pool):
    cands = [Candidate(p.id, p.position, p.price, p.team_id, p.xp[0], name=p.name)
             for p in pool]
    sol = SquadOptimizer().solve(cands)
    assert sol.feasible
    return {p.id for p in sol.picks}


def test_legacy_mode_matches_value_aware_when_no_appreciation():
    """When bank+purchase reflect "all bought at current price, no rises",
    the value-flow constraint is equivalent to the static £100m cap."""
    pool = _balanced_pool(horizon=2)
    initial = _initial(pool)
    purchase = {p.id: p.price for p in pool if p.id in initial}
    bank = BUDGET - sum(p.price for p in pool if p.id in initial)
    planner = TransferPlanner(bench_weight=0.0)

    legacy = planner.plan(initial, pool, initial_ft=1, horizon=2)
    value = planner.plan(initial, pool, initial_ft=1, horizon=2,
                         bank=bank, purchase=purchase)
    assert value.feasible and legacy.feasible
    assert abs(value.net_xp - legacy.net_xp) < 1e-3


def test_value_aware_keeps_holding_appreciated_squad_legacy_must_sell():
    """As the squad appreciates past the £100m static cap, legacy is forced to
    sell winners just to fit the cap (with -4 hits if FT runs out). Value-aware
    sees the real budget and can choose the optimal "hold" plan."""
    pool = _balanced_pool(horizon=1)
    initial = _initial(pool)

    # Push all 15 initial players up by 25 each -> squad sum = 750 + 375 = 1125,
    # over the static cap. Sell value per held player = 50 + 12 = 62.
    for p in pool:
        if p.id in initial:
            p.price = 75
    purchase = {pid: 50 for pid in initial}
    bank = 0
    # Real team value: 0 + 15 * 62 = 930. The squad fits the real budget.

    planner = TransferPlanner(bench_weight=0.0)
    legacy_hold = planner.plan(initial, pool, initial_ft=1, horizon=1,
                               lock_squad=True)
    assert not legacy_hold.feasible   # static cap rejects the appreciated hold

    value_hold = planner.plan(initial, pool, initial_ft=1, horizon=1,
                              lock_squad=True, bank=bank, purchase=purchase)
    assert value_hold.feasible
    assert set(value_hold.gws[0].squad) == initial


def test_value_aware_blocks_target_when_real_budget_insufficient():
    """Same risen-MID setup but the target costs more than the appreciation
    funds. The static cap would (wrongly) permit it; value-aware blocks."""
    pool = _balanced_pool(horizon=1)
    initial = _initial(pool)
    swap_out = next(p.id for p in pool if p.id in initial and p.position == FWD)
    for p in pool:
        if p.id == swap_out:
            p.price = 90  # FWD originally 50, now 90 -> sell value 70
    purchase = {pid: 50 for pid in initial}
    bank = 0

    target = PlayerH(900, FWD, 100, 99, [50.0], name="target")  # needs 100, only 70 to spend
    pool = pool + [target]

    planner = TransferPlanner(bench_weight=0.0)
    value = planner.plan(initial, pool, initial_ft=1, horizon=1,
                         bank=bank, purchase=purchase)
    assert value.feasible
    # Target dominates the objective but is unaffordable under real budget.
    assert 900 not in value.gws[0].squad


def test_value_aware_acquires_target_without_paying_to_fit_cap():
    """Squad appreciated past the static cap. Legacy CAN technically fit by
    selling enough held players to drop below £100m, but pays -4 hits for each
    forced sale beyond the FT. Value-aware sees the real budget, so it acquires
    a high-xP target with one free transfer and zero hits."""
    pool = _balanced_pool(horizon=1)
    initial = _initial(pool)
    for p in pool:
        if p.id in initial:
            p.price = 75   # all appreciated 50 -> 75, sell value 62
    purchase = {pid: 50 for pid in initial}
    bank = 0

    target = PlayerH(900, MID, 60, 99, [20.0], name="target")
    pool = pool + [target]

    planner = TransferPlanner(bench_weight=0.0)
    legacy = planner.plan(initial, pool, initial_ft=1, horizon=1)
    value = planner.plan(initial, pool, initial_ft=1, horizon=1,
                         bank=bank, purchase=purchase)
    assert legacy.feasible and value.feasible
    # Value-aware: 1 free transfer in, no forced sales -> 0 hits, target on.
    assert value.gws[0].hit == 0
    assert 900 in value.gws[0].squad
    # Legacy: forced into multiple sales to fit the cap -> takes hits.
    assert legacy.total_hits > 0
    assert value.net_xp > legacy.net_xp


def test_value_aware_drop_reduces_spending_power():
    """Mass depreciation: every held player drops 50 -> 40. FPL's rule sells
    drops at current (lower) price, so the squad's selling power shrank.
    Legacy (static cap) would over-estimate this; value-aware uses real cash."""
    pool = _balanced_pool(horizon=1)
    initial = _initial(pool)
    for p in pool:           # depreciate every pool player to 40
        p.price = 40
    purchase = {pid: 50 for pid in initial}
    bank = 0
    # Real spending power on any single transfer: 0 + 40 (sale) - target_price.
    # A 55-priced target is unaffordable regardless of which player we drop --
    # ALL sales are 40 (no positive surplus anywhere in the squad).
    target = PlayerH(900, MID, 55, 99, [20.0], name="target")
    pool = pool + [target]

    planner = TransferPlanner(bench_weight=0.0)
    value = planner.plan(initial, pool, initial_ft=1, horizon=1,
                         bank=bank, purchase=purchase)
    assert value.feasible
    assert 900 not in value.gws[0].squad   # mass drop killed all upgrades


def test_selling_price_rule_drives_the_constraint():
    """Sanity check the FPL rule the constraint relies on: half-the-rise on
    rises, current (lower) price on drops."""
    assert selling_price(50, 50) == 50
    assert selling_price(50, 90) == 70    # +40 -> +20
    assert selling_price(50, 91) == 70    # +41 -> floor(20.5) = 20
    assert selling_price(80, 70) == 70    # drop -> current
