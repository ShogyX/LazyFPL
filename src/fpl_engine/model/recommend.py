"""Recommendation generation (plan 9.2).

Runs the multi-GW transfer planner from the *current tracked roster* and
compares it to a no-transfer hold baseline, producing the upcoming-deadline
transfer + captain recommendation with rationale (component xP, EV uplift,
hit). Stored in ``serving.recommendations``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import recommendations
from ..logging_setup import get_logger
from ..optimise import TransferPlanner, load_horizon_candidates

log = get_logger(__name__)


@dataclass
class Recommendation:
    entry_id: int | None
    season: str
    target_event: int
    kind: str
    ev: float
    confidence: float
    rationale: dict


class RecommendationEngine:
    def __init__(self, sm: sessionmaker[Session] | None = None,
                 model_version: str = "v1"):
        self._sm = sm or get_sessionmaker()
        self.model_version = model_version

    def generate(self, season: str, from_gw: int, roster: set[int], *,
                 horizon: int = 6, initial_ft: int = 1,
                 entry_id: int | None = None,
                 candidates=None,
                 bank: int | None = None,
                 purchase: dict[int, int] | None = None,
                 eo_override: dict[int, float] | None = None,
                 eo_weight: float = 0.0) -> Recommendation:
        gws = list(range(from_gw, from_gw + horizon))
        cands = candidates if candidates is not None else load_horizon_candidates(
            season, gws, model_version=self.model_version, include_ids=roster,
            eo_override=eo_override)
        pool_ids = {c.id for c in cands}
        roster = {r for r in roster if r in pool_ids}
        if len(roster) != 15:
            raise ValueError(
                f"roster must be 15 players present in the candidate pool "
                f"(got {len(roster)}); some picks lack predictions/prices")

        names = {c.id: c.name for c in cands}
        xp0 = {c.id: c.xp[0] for c in cands}
        # eo_weight > 0 protects template (favours high elite-EO); < 0 chases
        # differentials. 0 = pure xP (elite EO loaded but inert).
        planner = TransferPlanner(eo_weight=eo_weight)
        plan = planner.plan(roster, cands, initial_ft=initial_ft, horizon=horizon,
                            bank=bank, purchase=purchase)
        if not plan.feasible:
            raise ValueError("no feasible plan for roster (check budget/constraints)")
        hold = planner.plan(roster, cands, initial_ft=initial_ft, horizon=horizon,
                            lock_squad=True, bank=bank, purchase=purchase)
        # A real entry's roster can be infeasible under static prices / max-3
        # (e.g. after price drift) -> the locked hold is unsolvable; in that case
        # report no uplift rather than a spurious plan.net_xp - 0 delta.
        if hold.feasible:
            hold_net = hold.net_xp
            uplift = round(plan.net_xp - hold_net, 4)
        else:
            log.warning("hold baseline infeasible; uplift unavailable",
                        extra={"entry_id": entry_id, "season": season, "event": from_gw})
            hold_net = None
            uplift = None

        gw0 = plan.gws[0]
        cap_id = gw0.captain
        kind = "transfer" if gw0.transfers_in else "captain"
        rationale = {
            "horizon": plan.horizon,
            "transfers_in": [{"id": i, "name": names.get(i, i), "xp_next": round(xp0.get(i, 0), 3)}
                             for i in gw0.transfers_in],
            "transfers_out": [{"id": i, "name": names.get(i, i)} for i in gw0.transfers_out],
            "captain": {"id": cap_id, "name": names.get(cap_id, cap_id),
                        "xp_next": round(xp0.get(cap_id, 0), 3)},
            "gw0_hit": gw0.hit,
            "plan_net_xp": plan.net_xp,
            "hold_net_xp": hold_net,
            "uplift": uplift,
        }
        # Heuristic confidence proxy: per-GW EV uplift squashed into [0,1]. This
        # is NOT a statistical confidence; a variance-based measure is future work.
        ev = uplift if uplift is not None else 0.0
        confidence = round(min(1.0, max(0.0, ev / max(horizon, 1) / 2.0)), 3)

        rec = Recommendation(entry_id, season, from_gw, kind, ev, confidence, rationale)
        self._store(rec)
        log.info("recommendation generated", extra={
            "entry_id": entry_id, "season": season, "event": from_gw, "kind": kind,
            "uplift": uplift, "captain": rationale["captain"]["name"]})
        return rec

    def _store(self, rec: Recommendation) -> None:
        with self._sm() as s:
            s.execute(insert(recommendations).values(
                model_version=self.model_version, entry_id=rec.entry_id,
                season=rec.season, target_event=rec.target_event, kind=rec.kind,
                ev=rec.ev, confidence=rec.confidence, rationale=rec.rationale))
            s.commit()
