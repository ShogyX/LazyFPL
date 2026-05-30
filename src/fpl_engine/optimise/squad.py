"""Squad / starting-XI selection MILP (plan 8.1 / C.2a).

Maximise starting-XI expected points (captain ×2) subject to the 2025/26 rules:
15 = 2 GK / 5 DEF / 5 MID / 3 FWD, £100.0m budget, max 3 per club, a valid XI
formation, and one captain. Bench is discounted by P(play)×xP (auto-sub value).
Solved with CBC via PuLP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

GK, DEF, MID, FWD = 1, 2, 3, 4
SQUAD_QUOTA = {GK: 2, DEF: 5, MID: 5, FWD: 3}
# Valid starting-XI bounds per position (1 GK; 3-5 DEF; 2-5 MID; 1-3 FWD).
XI_BOUNDS = {GK: (1, 1), DEF: (3, 5), MID: (2, 5), FWD: (1, 3)}
BUDGET = 1000  # £100.0m in FPL tenths


def selling_price(purchase: int, current: int) -> int:
    """FPL sell value (tenths): purchase + floor(half the rise); if the price
    has dropped, you sell at the current (lower) price."""
    if current <= purchase:
        return current
    return purchase + (current - purchase) // 2


@dataclass
class Candidate:
    id: int                # FPL element id
    position: int          # 1 GK .. 4 FWD
    price: int             # now_cost (tenths)
    team_id: int
    xp: float              # expected points for the GW
    p_play: float = 1.0    # P(meaningful minutes), for bench discount
    name: str = ""
    player_key: int | None = None
    ownership: float = 0.0  # selected_by_percent, for the EO overlay


@dataclass
class Pick:
    id: int
    name: str
    position: int
    price: int
    team_id: int
    xp: float
    is_start: bool
    is_captain: bool
    is_vice: bool


@dataclass
class SquadSolution:
    status: str
    picks: list[Pick] = field(default_factory=list)
    total_cost: int = 0
    xi_xp: float = 0.0          # starting XI xP incl. captain doubling
    formation: dict[int, int] = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return self.status == "Optimal"


class SquadOptimizer:
    def __init__(self, budget: int = BUDGET, bench_weight: float = 0.1,
                 eo_weight: float = 0.0):
        self.budget = budget
        self.bench_weight = bench_weight
        # EO overlay: +ve protects rank (favour owned/template), -ve chases rank
        # (favour differentials). 0 = pure xP.
        self.eo_weight = eo_weight

    def solve(self, candidates: list[Candidate]) -> SquadSolution:
        idx = list(range(len(candidates)))
        c = candidates
        prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)

        squad = {i: pulp.LpVariable(f"sq_{i}", cat="Binary") for i in idx}
        start = {i: pulp.LpVariable(f"st_{i}", cat="Binary") for i in idx}
        cap = {i: pulp.LpVariable(f"cp_{i}", cat="Binary") for i in idx}

        # Objective: XI xP + captain (extra xP) + discounted bench + EO overlay.
        prob += (
            pulp.lpSum(start[i] * c[i].xp for i in idx)
            + pulp.lpSum(cap[i] * c[i].xp for i in idx)
            + self.bench_weight * pulp.lpSum(
                (squad[i] - start[i]) * c[i].p_play * c[i].xp for i in idx)
            + self.eo_weight * pulp.lpSum(start[i] * c[i].ownership for i in idx)
        )

        # Squad composition.
        prob += pulp.lpSum(squad[i] for i in idx) == 15
        for pos, quota in SQUAD_QUOTA.items():
            prob += pulp.lpSum(squad[i] for i in idx if c[i].position == pos) == quota
        prob += pulp.lpSum(squad[i] * c[i].price for i in idx) <= self.budget
        for team in {ci.team_id for ci in c}:
            prob += pulp.lpSum(squad[i] for i in idx if c[i].team_id == team) <= 3

        # Starting XI.
        for i in idx:
            prob += start[i] <= squad[i]
            prob += cap[i] <= start[i]
        prob += pulp.lpSum(start[i] for i in idx) == 11
        for pos, (lo, hi) in XI_BOUNDS.items():
            in_pos = [start[i] for i in idx if c[i].position == pos]
            prob += pulp.lpSum(in_pos) >= lo
            prob += pulp.lpSum(in_pos) <= hi
        prob += pulp.lpSum(cap[i] for i in idx) == 1

        prob.solve(pulp.PULP_CBC_CMD(msg=0))
        return self._build_solution(prob, candidates, squad, start, cap)

    def _build_solution(self, prob, c, squad, start, cap) -> SquadSolution:
        status = pulp.LpStatus[prob.status]
        sol = SquadSolution(status=status)
        if status != "Optimal":
            return sol

        chosen = [i for i in range(len(c)) if squad[i].value() > 0.5]
        starters = {i for i in chosen if start[i].value() > 0.5}
        captain = next((i for i in chosen if cap[i].value() > 0.5), None)
        # Vice = highest-xP starter that is not the captain.
        vice = max((i for i in starters if i != captain),
                   key=lambda i: c[i].xp, default=None)

        for i in chosen:
            sol.picks.append(Pick(
                id=c[i].id, name=c[i].name, position=c[i].position, price=c[i].price,
                team_id=c[i].team_id, xp=c[i].xp, is_start=i in starters,
                is_captain=i == captain, is_vice=i == vice,
            ))
        sol.total_cost = sum(c[i].price for i in chosen)
        sol.xi_xp = round(
            sum(c[i].xp for i in starters) + (c[captain].xp if captain is not None else 0), 4)
        sol.formation = {
            pos: sum(1 for i in starters if c[i].position == pos)
            for pos in (GK, DEF, MID, FWD)
        }
        return sol
