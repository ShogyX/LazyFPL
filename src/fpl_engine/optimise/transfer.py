"""Multi-GW transfer planner (plan 8.2 / C.2b).

Given the current squad and a per-GW expected-points matrix, choose a transfer
path over a configurable horizon (default 6) that maximises cumulative
starting-XI xP (captain ×2) **net of −4 hits**, respecting free-transfer accrual
(bankable to 5), squad composition, budget, max-3-per-club and a valid XI each
GW.

Budget has two modes, selected at ``plan`` time:

* **Static cap** (legacy): per-GW ``Σ own·current_price ≤ BUDGET``. Treats every
  player at current price and assumes the squad always fits in £100m.
* **Value-aware** (when ``bank`` is supplied): per-GW bank-flow constraint
  ``bank + Σ sell_value(sold-from-initial) − Σ current_price(newly-bought) ≥ 0``
  using FPL's purchase + ½-rise selling rule. The effective spending power grows
  with held-player appreciation and shrinks when they drop, so the affordable
  player range tracks the real team value through the season. Held players
  default to ``current_price`` as purchase when missing from ``purchase`` (i.e.,
  no value gain assumed).

Solved as one MILP with CBC. Free-transfer dynamics:
    ft[0] = initial_ft;  used[t] <= min(ft[t], transfers[t]);
    extra[t] = transfers[t] - used[t];  hit[t] = 4 * extra[t];
    ft[t+1] = min(5, ft[t] - used[t] + 1)   (encoded as an upper bound the
    maximiser saturates, since more banked FT only ever helps).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

from .squad import SQUAD_QUOTA, XI_BOUNDS, BUDGET, GK, DEF, MID, FWD, selling_price

HIT_COST = 4
MAX_FT = 5


@dataclass
class PlayerH:
    id: int
    position: int
    price: int
    team_id: int
    xp: list[float]          # expected points per horizon GW
    p_play: float = 1.0
    name: str = ""
    ownership: float = 0.0   # selected_by_percent, for the EO overlay


@dataclass
class GwPlan:
    gw_index: int
    squad: list[int]
    xi: list[int]
    captain: int | None
    transfers_in: list[int]
    transfers_out: list[int]
    hit: int
    ft_available: int
    xi_xp: float


@dataclass
class TransferPlan:
    status: str
    horizon: int
    gws: list[GwPlan] = field(default_factory=list)
    gross_xp: float = 0.0
    total_hits: int = 0
    net_xp: float = 0.0

    @property
    def feasible(self) -> bool:
        return self.status == "Optimal"


class TransferPlanner:
    def __init__(self, budget: int = BUDGET, bench_weight: float = 0.1,
                 hit_cost: int = HIT_COST, eo_weight: float = 0.0,
                 decay_base: float = 1.0, ft_value: float = 0.0):
        self.budget = budget
        self.bench_weight = bench_weight
        self.hit_cost = hit_cost
        self.eo_weight = eo_weight  # +ve template / -ve differential; 0 = pure xP
        # Future-GW EV discount (decay_base**t): near GWs are more certain, so the
        # plan commits to them and keeps later GWs flexible. 1.0 = no discount.
        self.decay_base = decay_base
        # Opportunity cost of using a free transfer (see value_step.value_aware_gw).
        self.ft_value = max(0.0, min(ft_value, float(hit_cost)))

    def plan(self, initial_squad: set[int], candidates: list[PlayerH],
             initial_ft: int = 1, horizon: int = 6,
             lock_squad: bool = False,
             bank: int | None = None,
             purchase: dict[int, int] | None = None) -> TransferPlan:
        # min() over xp lengths so c[i].xp[t] can never index out of range on a
        # ragged pool (the loader pads uniformly, so this is normally == horizon).
        H = min(horizon, min(len(c.xp) for c in candidates))
        idx = list(range(len(candidates)))
        c = candidates
        ids = {c[i].id for i in idx}
        assert initial_squad <= ids, "initial squad must be within the candidate pool"

        # Value-aware mode: real bank + per-GW bank-flow constraint. Within the
        # planning horizon prices are static (no prediction), so only the held
        # squad's appreciation/depreciation affects spending power -- new buys
        # round-trip at current price (net zero) and drop out of the constraint.
        value_aware = bank is not None
        purchase = purchase or {}
        sell_v = {
            i: selling_price(purchase.get(c[i].id, c[i].price), c[i].price)
            for i in idx if c[i].id in initial_squad
        }

        m = pulp.LpProblem("fpl_transfer_plan", pulp.LpMaximize)
        own = {(i, t): pulp.LpVariable(f"o_{i}_{t}", cat="Binary") for i in idx for t in range(H)}
        start = {(i, t): pulp.LpVariable(f"s_{i}_{t}", cat="Binary") for i in idx for t in range(H)}
        cap = {(i, t): pulp.LpVariable(f"c_{i}_{t}", cat="Binary") for i in idx for t in range(H)}
        tin = {(i, t): pulp.LpVariable(f"i_{i}_{t}", cat="Binary") for i in idx for t in range(H)}

        ft = {0: float(initial_ft)}
        for t in range(1, H):
            ft[t] = pulp.LpVariable(f"ft_{t}", lowBound=0, upBound=MAX_FT, cat="Integer")
        used = {t: pulp.LpVariable(f"u_{t}", lowBound=0, upBound=MAX_FT, cat="Integer")
                for t in range(H)}
        extra = {t: pulp.LpVariable(f"x_{t}", lowBound=0, cat="Integer") for t in range(H)}

        def prev_own(i, t):
            if t == 0:
                return 1 if c[i].id in initial_squad else 0
            return own[(i, t - 1)]

        # objective: decayed (XI xP + captain + discounted bench + EO), minus the
        # transfer penalty (ft_value per used free transfer + hit_cost per extra).
        d = [self.decay_base ** t for t in range(H)]
        m += (
            pulp.lpSum(d[t] * (start[(i, t)] + cap[(i, t)]) * c[i].xp[t]
                       for i in idx for t in range(H))
            + self.bench_weight * pulp.lpSum(
                d[t] * (own[(i, t)] - start[(i, t)]) * c[i].p_play * c[i].xp[t]
                for i in idx for t in range(H))
            + self.eo_weight * pulp.lpSum(
                d[t] * start[(i, t)] * c[i].ownership for i in idx for t in range(H))
            - self.ft_value * pulp.lpSum(d[t] * tin[(i, t)] for i in idx for t in range(H))
            - (self.hit_cost - self.ft_value) * pulp.lpSum(d[t] * extra[t] for t in range(H))
        )

        teams = {ci.team_id for ci in c}
        for t in range(H):
            m += pulp.lpSum(own[(i, t)] for i in idx) == 15
            for pos, quota in SQUAD_QUOTA.items():
                m += pulp.lpSum(own[(i, t)] for i in idx if c[i].position == pos) == quota
            if value_aware:
                sells_t = pulp.lpSum((1 - own[(i, t)]) * sell_v[i] for i in sell_v)
                buys_t = pulp.lpSum(own[(i, t)] * c[i].price
                                    for i in idx if c[i].id not in initial_squad)
                m += bank + sells_t - buys_t >= 0
            else:
                m += pulp.lpSum(own[(i, t)] * c[i].price for i in idx) <= self.budget
            for team in teams:
                m += pulp.lpSum(own[(i, t)] for i in idx if c[i].team_id == team) <= 3

            for i in idx:
                m += start[(i, t)] <= own[(i, t)]
                m += cap[(i, t)] <= start[(i, t)]
            m += pulp.lpSum(start[(i, t)] for i in idx) == 11
            for pos, (lo, hi) in XI_BOUNDS.items():
                in_pos = [start[(i, t)] for i in idx if c[i].position == pos]
                m += pulp.lpSum(in_pos) >= lo
                m += pulp.lpSum(in_pos) <= hi
            m += pulp.lpSum(cap[(i, t)] for i in idx) == 1

            # transfer-in indicator: newly owned this GW
            for i in idx:
                p = prev_own(i, t)
                m += tin[(i, t)] >= own[(i, t)] - p
                m += tin[(i, t)] <= own[(i, t)]
                m += tin[(i, t)] <= 1 - p
            transfers_t = pulp.lpSum(tin[(i, t)] for i in idx)
            m += used[t] <= ft[t]
            m += used[t] <= transfers_t
            m += extra[t] >= transfers_t - used[t]
            if t + 1 < H:
                m += ft[t + 1] <= ft[t] - used[t] + 1   # saturated by maximiser
                m += ft[t + 1] <= MAX_FT

        if lock_squad:  # no-transfer hold baseline: freeze the squad every GW
            for i in idx:
                fixed = 1 if c[i].id in initial_squad else 0
                for t in range(H):
                    m += own[(i, t)] == fixed

        m.solve(pulp.PULP_CBC_CMD(msg=0))
        return self._extract(m, c, idx, H, own, start, cap, tin, initial_squad, initial_ft)

    def _extract(self, m, c, idx, H, own, start, cap, tin, initial_squad, initial_ft):
        status = pulp.LpStatus[m.status]
        plan = TransferPlan(status=status, horizon=H)
        if status != "Optimal":
            return plan

        gross = 0.0
        hits_total = 0
        prev_squad: set[int] = set(initial_squad)
        ft_cur = int(initial_ft)
        for t in range(H):
            squad = {c[i].id for i in idx if own[(i, t)].value() > 0.5}
            captain = next((c[i].id for i in idx if cap[(i, t)].value() > 0.5), None)
            ins = sorted(c[i].id for i in idx if tin[(i, t)].value() > 0.5)
            outs = sorted(prev_squad - squad)

            # FT/hits recomputed deterministically from the realised path (the
            # LP's ft/extra vars are only pinned when banking is beneficial).
            n_transfers = len(ins)
            used = min(n_transfers, ft_cur)
            hit = self.hit_cost * max(0, n_transfers - ft_cur)
            ft_available = ft_cur
            ft_cur = min(MAX_FT, ft_cur - used + 1)

            xi_ids = [c[i].id for i in idx if start[(i, t)].value() > 0.5]
            xi_xp = sum(c[i].xp[t] for i in idx if start[(i, t)].value() > 0.5)
            cap_bonus = next((c[i].xp[t] for i in idx if c[i].id == captain), 0.0) \
                if captain is not None else 0.0
            gross += xi_xp + cap_bonus
            hits_total += hit
            plan.gws.append(GwPlan(
                gw_index=t, squad=sorted(squad), xi=sorted(xi_ids), captain=captain,
                transfers_in=ins, transfers_out=outs, hit=hit,
                ft_available=ft_available, xi_xp=round(xi_xp + cap_bonus, 4)))
            prev_squad = squad

        plan.gross_xp = round(gross, 4)
        plan.total_hits = hits_total
        plan.net_xp = round(gross - hits_total, 4)
        return plan


def rolling_greedy(planner: TransferPlanner, initial_squad: set[int],
                   candidates: list[PlayerH], initial_ft: int = 1,
                   horizon: int = 6) -> tuple[float, list[GwPlan]]:
    """Myopic one-week-at-a-time baseline: re-optimise each GW for that GW only,
    carrying the squad and free-transfer count forward. Returns net XI xP."""
    H = min(horizon, max(len(c.xp) for c in candidates))
    squad = set(initial_squad)
    ft = initial_ft
    net = 0.0
    gws: list[GwPlan] = []
    for g in range(H):
        sub = [PlayerH(c.id, c.position, c.price, c.team_id, [c.xp[g]], c.p_play, c.name)
               for c in candidates]
        sol = planner.plan(squad, sub, initial_ft=ft, horizon=1)
        if not sol.feasible:
            break
        gw = sol.gws[0]
        net += gw.xi_xp - gw.hit
        transfers = len(gw.transfers_in)
        used = min(transfers, ft)
        ft = min(MAX_FT, ft - used + 1)
        squad = set(gw.squad)
        gws.append(gw)
    return round(net, 4), gws
