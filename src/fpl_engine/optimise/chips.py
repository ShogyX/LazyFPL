"""Captaincy ceiling + chip timing (plan 8.3 / C.2).

Over a horizon's per-GW xP matrix, recommend when to play each chip:
  * Triple Captain — the GW with the highest captain xP (ceiling);
  * Bench Boost     — the GW with the highest bench xP (e.g. a double GW);
  * Free Hit        — the GW where a one-week free squad most exceeds the
                      current squad (e.g. a blank GW).

Chip windows (2025/26): two halves (GW1-19, GW20-38); the first set expires at
the GW19 deadline; each chip usable once per half. ``allowed_half`` filters the
candidate GWs accordingly.

This recommender suggests the best GW *per chip* within the horizon/half; it
does not coordinate chips against each other (FPL allows only one chip per GW),
so the operator schedules the final set. A non-positive ``value`` means the chip
is not worth playing in this horizon (e.g. Free Hit when no GW beats the roster).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..logging_setup import get_logger
from .squad import Candidate, SquadOptimizer
from .transfer import PlayerH

log = get_logger(__name__)

FIRST_SET_EXPIRY_GW = 19


def half_of(gw: int) -> int:
    return 1 if gw <= FIRST_SET_EXPIRY_GW else 2


def best_xi_value(players: list[tuple[int, float]]) -> tuple[float, float, float]:
    """Best XI from 15 (pos, xp) pairs -> (xi_xp, captain_xp, bench_xp)."""
    byp: dict[int, list[float]] = defaultdict(list)
    for pos, xp in players:
        byp[pos].append(xp)
    for pos in byp:
        byp[pos].sort(reverse=True)

    best_sum, best_started = None, None
    for d in range(3, 6):
        for mid in range(2, 6):
            for f in range(1, 4):
                if d + mid + f != 10:
                    continue
                if (len(byp[1]) < 1 or len(byp[2]) < d or len(byp[3]) < mid
                        or len(byp[4]) < f):
                    continue
                started = [byp[1][0]] + byp[2][:d] + byp[3][:mid] + byp[4][:f]
                total = sum(started)
                if best_sum is None or total > best_sum:
                    best_sum, best_started = total, started
    if best_started is None:
        return 0.0, 0.0, 0.0
    xi_xp = best_sum
    captain_xp = max(best_started)
    bench_xp = sum(xp for _, xp in players) - xi_xp
    return xi_xp, captain_xp, bench_xp


@dataclass
class ChipRec:
    chip: str
    gw: int
    half: int
    value: float


ALL_CHIPS = ("triple_captain", "bench_boost", "free_hit", "wildcard")
# Don't recommend a Wildcard before this GW — too little signal early (research:
# first WC is best ~GW7-12 once the player/fixture landscape is clearer).
WILDCARD_MIN_GW = 7


class ChipPlanner:
    def __init__(self, budget: int | None = None):
        self._opt = SquadOptimizer() if budget is None else SquadOptimizer(budget=budget)

    def grid(self, candidates: list[PlayerH], roster: set[int], gws: list[int],
             allowed_half: int | None = None, wc_window: int = 6,
             wc_min_gw: int = WILDCARD_MIN_GW) -> dict[str, dict[int, float]]:
        """Per-(chip, GW) expected-value uplift over the horizon.

        triple_captain = best captain xP; bench_boost = bench xP (peaks in a
        double GW); free_hit = optimal one-week XI minus the held XI; wildcard =
        the cumulative weekly uplift over the next ``wc_window`` GWs if you reset
        now (a squad-drift proxy — a Wildcard captures that gap persistently).
        """
        byid = {c.id: c for c in candidates}
        roster_players = [byid[i] for i in roster if i in byid]
        if len(roster_players) != 15:
            log.warning("chip roster not 15 players; bench/XI values approximate",
                        extra={"roster": len(roster), "in_pool": len(roster_players)})

        cap_g: dict[int, float] = {}
        bench_g: dict[int, float] = {}
        fh_g: dict[int, float] = {}
        for t, gw in enumerate(gws):
            if allowed_half is not None and half_of(gw) != allowed_half:
                continue
            rp = [(p.position, p.xp[t]) for p in roster_players]
            xi_xp, cap_xp, bench_xp = best_xi_value(rp)
            roster_total = xi_xp + cap_xp
            fh_cands = [Candidate(p.id, p.position, p.price, p.team_id, p.xp[t]) for p in candidates]
            fh = self._opt.solve(fh_cands)
            cap_g[gw] = round(cap_xp, 4)
            bench_g[gw] = round(bench_xp, 4)
            fh_g[gw] = round((fh.xi_xp - roster_total) if fh.feasible else 0.0, 4)

        wc_g: dict[int, float] = {}
        for k, gw in enumerate(gws):
            if gw < wc_min_gw or (allowed_half is not None and half_of(gw) != allowed_half):
                continue
            window = [fh_g.get(g, 0.0) for g in gws[k:k + wc_window]]
            wc_g[gw] = round(sum(max(0.0, u) for u in window), 4)

        return {"triple_captain": cap_g, "bench_boost": bench_g, "free_hit": fh_g, "wildcard": wc_g}

    def recommend(self, candidates: list[PlayerH], roster: set[int], gws: list[int],
                  allowed_half: int | None = None) -> dict[str, ChipRec]:
        """Best GW per chip, independent (one chip may collide with another)."""
        g = self.grid(candidates, roster, gws, allowed_half)
        out: dict[str, ChipRec] = {}
        for chip, vals in g.items():
            if vals:
                gw = max(vals, key=vals.get)
                out[chip] = ChipRec(chip=chip, gw=gw, half=half_of(gw), value=vals[gw])
        return out

    def plan(self, candidates: list[PlayerH], roster: set[int], gws: list[int],
             allowed_half: int | None = None, available: set[str] | None = None
             ) -> dict[str, ChipRec]:
        """Collision-free schedule: greedily assign the highest-value (chip, GW)
        pairs so no two chips land on the same gameweek and each chip is used
        once (FPL allows only one chip per GW)."""
        g = self.grid(candidates, roster, gws, allowed_half)
        avail = available if available is not None else set(ALL_CHIPS)
        choices = sorted(
            ((chip, gw, v) for chip in avail for gw, v in g.get(chip, {}).items() if v > 0),
            key=lambda x: -x[2])
        sched: dict[str, ChipRec] = {}
        used_gw: set[int] = set()
        for chip, gw, v in choices:
            if chip in sched or gw in used_gw:
                continue
            sched[chip] = ChipRec(chip=chip, gw=gw, half=half_of(gw), value=round(v, 4))
            used_gw.add(gw)
        return sched
