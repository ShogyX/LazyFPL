"""Value-aware single-GW transfer step (uses actual prices, not a flat cap).

Squad strength is constrained by a real, evolving budget: holding players whose
prices rose increases their selling value, which raises spending power. This MILP
gates transfers by the bank flow

    bank + Σ sell_value(out) − Σ current_price(in) ≥ 0

with ``sell_value`` per FPL's purchase + ½-rise rule. The affordable player range
therefore tracks the actual team value through the season (no price prediction).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

from .squad import GK, DEF, MID, FWD, SQUAD_QUOTA, XI_BOUNDS, selling_price

HIT_COST = 4
MAX_FT = 5


@dataclass
class GwPlayer:
    id: int
    position: int
    price: int          # this GW's actual price (tenths)
    team_id: int
    xp: float
    p_play: float = 1.0


@dataclass
class StepResult:
    status: str
    squad: list[int] = field(default_factory=list)
    xi: list[int] = field(default_factory=list)
    captain: int | None = None
    transfers_in: list[int] = field(default_factory=list)
    transfers_out: list[int] = field(default_factory=list)
    hit: int = 0
    bank: int = 0
    purchase: dict[int, int] = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return self.status == "Optimal"


def value_aware_gw(prior_squad: set[int], purchase: dict[int, int], bank: int,
                   players: list[GwPlayer], *, ft: int = 1, hit_cost: int = HIT_COST,
                   bench_weight: float = 0.1, ft_value: float = 0.0,
                   lock: bool = False) -> StepResult:
    """One GW's transfer decision under a real (bank + sell-value) budget.

    ``ft_value`` is the opportunity cost of *using* a free transfer (the value of
    banking it for a better future move). With ft_value>0 a transfer is only made
    when its xP gain exceeds it, which curbs noise-chasing churn. The total
    transfer penalty is ``ft_value * used_free + hit_cost * extra`` — kept linear
    as ``ft_value * transfers_in + (hit_cost - ft_value) * extra``.
    """
    idx = list(range(len(players)))
    c = players
    by_id = {c[i].id: i for i in idx}
    assert prior_squad <= set(by_id), "prior squad must be within the player set"
    ft_value = max(0.0, min(ft_value, float(hit_cost)))  # never reward taking hits

    sell = {i: (selling_price(purchase[c[i].id], c[i].price)
                if c[i].id in prior_squad else 0) for i in idx}
    prior = {i: (1 if c[i].id in prior_squad else 0) for i in idx}

    m = pulp.LpProblem("value_aware_gw", pulp.LpMaximize)
    own = {i: pulp.LpVariable(f"o_{i}", cat="Binary") for i in idx}
    start = {i: pulp.LpVariable(f"s_{i}", cat="Binary") for i in idx}
    cap = {i: pulp.LpVariable(f"c_{i}", cat="Binary") for i in idx}
    extra = pulp.LpVariable("extra", lowBound=0, cat="Integer")

    transfers_in = pulp.lpSum(own[i] for i in idx if not prior[i])

    m += (
        pulp.lpSum((start[i] + cap[i]) * c[i].xp for i in idx)
        + bench_weight * pulp.lpSum((own[i] - start[i]) * c[i].p_play * c[i].xp for i in idx)
        - ft_value * transfers_in
        - (hit_cost - ft_value) * extra
    )

    m += pulp.lpSum(own[i] for i in idx) == 15
    for pos, quota in SQUAD_QUOTA.items():
        m += pulp.lpSum(own[i] for i in idx if c[i].position == pos) == quota
    for team in {ci.team_id for ci in c}:
        m += pulp.lpSum(own[i] for i in idx if c[i].team_id == team) <= 3
    for i in idx:
        m += start[i] <= own[i]
        m += cap[i] <= start[i]
    m += pulp.lpSum(start[i] for i in idx) == 11
    for pos, (lo, hi) in XI_BOUNDS.items():
        in_pos = [start[i] for i in idx if c[i].position == pos]
        m += pulp.lpSum(in_pos) >= lo
        m += pulp.lpSum(in_pos) <= hi
    m += pulp.lpSum(cap[i] for i in idx) == 1

    # bank flow: sells (held & dropped) fund buys (newly owned), bank stays >= 0
    sells = pulp.lpSum((prior[i] - own[i]) * sell[i] for i in idx if prior[i])
    buys = pulp.lpSum(own[i] * c[i].price for i in idx if not prior[i])
    m += bank + sells - buys >= 0

    m += extra >= transfers_in - ft

    if lock:  # no-transfer hold: freeze the squad
        for i in idx:
            m += own[i] == prior[i]

    m.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[m.status]
    res = StepResult(status=status)
    if status != "Optimal":
        return res

    owned = [i for i in idx if own[i].value() > 0.5]
    res.squad = sorted(c[i].id for i in owned)
    res.xi = sorted(c[i].id for i in idx if start[i].value() > 0.5)
    res.captain = next((c[i].id for i in idx if cap[i].value() > 0.5), None)
    res.transfers_in = sorted(c[i].id for i in owned if not prior[i])
    res.transfers_out = sorted(c[i].id for i in idx
                               if prior[i] and own[i].value() <= 0.5)
    n_in = len(res.transfers_in)
    res.hit = hit_cost * max(0, n_in - ft)
    realized_sells = sum(sell[by_id[pid]] for pid in res.transfers_out)
    realized_buys = sum(c[by_id[pid]].price for pid in res.transfers_in)
    res.bank = bank + realized_sells - realized_buys
    res.purchase = {pid: (purchase[pid] if pid in prior_squad else c[by_id[pid]].price)
                    for pid in res.squad}
    return res
