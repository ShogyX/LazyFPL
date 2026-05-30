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


class ChipPlanner:
    def __init__(self, budget: int | None = None):
        self._opt = SquadOptimizer() if budget is None else SquadOptimizer(budget=budget)

    def recommend(self, candidates: list[PlayerH], roster: set[int], gws: list[int],
                  allowed_half: int | None = None) -> dict[str, ChipRec]:
        byid = {c.id: c for c in candidates}
        roster_players = [byid[i] for i in roster if i in byid]
        if len(roster_players) != 15:
            log.warning("chip roster not 15 players; bench/XI values approximate",
                        extra={"roster": len(roster), "in_pool": len(roster_players)})

        best: dict[str, ChipRec] = {}
        for t, gw in enumerate(gws):
            if allowed_half is not None and half_of(gw) != allowed_half:
                continue
            if gw > FIRST_SET_EXPIRY_GW and allowed_half == 1:
                continue  # first-set chips cannot be played after GW19

            rp = [(p.position, p.xp[t]) for p in roster_players]
            xi_xp, cap_xp, bench_xp = best_xi_value(rp)
            roster_total = xi_xp + cap_xp  # XI incl. captain doubling

            fh_cands = [Candidate(p.id, p.position, p.price, p.team_id, p.xp[t])
                        for p in candidates]
            fh = self._opt.solve(fh_cands)
            fh_uplift = (fh.xi_xp - roster_total) if fh.feasible else 0.0

            self._update(best, "triple_captain", gw, cap_xp)
            self._update(best, "bench_boost", gw, bench_xp)
            self._update(best, "free_hit", gw, fh_uplift)
        return best

    @staticmethod
    def _update(best: dict, chip: str, gw: int, value: float) -> None:
        if chip not in best or value > best[chip].value:
            best[chip] = ChipRec(chip=chip, gw=gw, half=half_of(gw), value=round(value, 4))
