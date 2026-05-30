"""Elite-manager cohort enumeration + effective ownership (plan 5.2).

Enumerate the top of the global "Overall" classic league (id 314) to build a
cohort of elite entries, capture each one's per-GW picks, then aggregate
*elite* effective ownership (EO) — owned% + captaincy weight — which differs
from the bootstrap's *global* ownership and is the signal the EO overlay wants.

Every call goes through the budget-gated fetch layer; ``max_managers`` bounds
the cohort so a sweep stays within the FPL self-rate-limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import elite_managers, elite_ownership, elite_picks
from ..logging_setup import get_logger
from .fetch import FetchClient

log = get_logger(__name__)

OVERALL_LEAGUE = 314  # FPL global "Overall" classic league
PAGE_SIZE = 50        # FPL standings page size


@dataclass
class CohortResult:
    league: int
    managers: int


@dataclass
class OwnershipResult:
    event: int
    n_managers: int
    elements: int


class EliteCohortIngestor:
    PROVIDER = "fpl"

    def __init__(self, fetch: FetchClient, sm: sessionmaker[Session] | None = None):
        self._fetch = fetch
        self._sm = sm or get_sessionmaker()

    def enumerate_cohort(self, *, max_managers: int = 500,
                         league: int = OVERALL_LEAGUE) -> CohortResult:
        """Page the league standings to collect the top ``max_managers`` entries."""
        rows: list[dict] = []
        page = 1
        while len(rows) < max_managers:
            res = self._fetch.get(
                self.PROVIDER, f"/leagues-classic/{league}/standings/",
                params={"page_standings": page})
            if res.status_code != 200 or not isinstance(res.payload, dict):
                break
            standings = (res.payload.get("standings") or {})
            results = standings.get("results") or []
            if not results:
                break
            for r in results:
                if r.get("entry") is None:
                    continue
                rows.append({
                    "entry_id": r["entry"], "player_name": r.get("player_name"),
                    "rank": r.get("rank"), "total_points": r.get("total"),
                    "source_league": league,
                })
                if len(rows) >= max_managers:
                    break
            if not standings.get("has_next"):
                break
            page += 1

        if rows:
            with self._sm() as s:
                stmt = insert(elite_managers).values(rows)
                s.execute(stmt.on_conflict_do_update(
                    index_elements=["entry_id"],
                    set_={c: stmt.excluded[c] for c in
                          ("player_name", "rank", "total_points", "source_league")}))
                s.commit()
        log.info("elite cohort enumerated", extra={"league": league, "managers": len(rows)})
        return CohortResult(league, len(rows))

    def _cohort_ids(self, s: Session) -> list[int]:
        return [r[0] for r in s.execute(select(elite_managers.c.entry_id)).all()]

    def ingest_picks(self, event: int) -> int:
        """Pull each cohort member's picks for ``event`` into elite_picks."""
        with self._sm() as s:
            ids = self._cohort_ids(s)
        rows: list[dict] = []
        for entry_id in ids:
            res = self._fetch.get(
                self.PROVIDER, f"/entry/{entry_id}/event/{event}/picks/")
            if res.status_code != 200 or not isinstance(res.payload, dict):
                continue
            for p in res.payload.get("picks", []):
                if p.get("element") is None:
                    continue
                rows.append({
                    "entry_id": entry_id, "event": event, "element_id": p["element"],
                    "multiplier": p.get("multiplier"),
                    "is_captain": p.get("is_captain"),
                })
        if rows:
            with self._sm() as s:
                stmt = insert(elite_picks).values(rows)
                s.execute(stmt.on_conflict_do_nothing(
                    index_elements=["entry_id", "event", "element_id", "captured_at"]))
                s.commit()
        log.info("elite picks ingested", extra={"event": event, "rows": len(rows)})
        return len(rows)

    def aggregate_ownership(self, event: int) -> OwnershipResult:
        """Compute elite EO from the latest picks snapshot for ``event``.

        EO = owned_fraction + captaincy_fraction (captain's extra multiplier), the
        standard rank-impact weight. Captained counts picks with multiplier >= 2.
        """
        ep = elite_picks.c
        with self._sm() as s:
            # Latest captured_at per (entry, event) to avoid double-counting polls.
            latest = (
                select(ep.entry_id, func.max(ep.captured_at).label("c"))
                .where(ep.event == event).group_by(ep.entry_id).subquery()
            )
            picks = s.execute(
                select(ep.element_id, ep.entry_id, ep.is_captain, ep.multiplier)
                .join(latest, (ep.entry_id == latest.c.entry_id)
                      & (ep.captured_at == latest.c.c))
                .where(ep.event == event)
            ).all()
            n_managers = len({p.entry_id for p in picks})
            if n_managers == 0:
                return OwnershipResult(event, 0, 0)

            owned: dict[int, int] = {}
            captained: dict[int, int] = {}
            for p in picks:
                owned[p.element_id] = owned.get(p.element_id, 0) + 1
                if p.is_captain or (p.multiplier or 0) >= 2:
                    captained[p.element_id] = captained.get(p.element_id, 0) + 1

            rows = []
            for eid, n_own in owned.items():
                n_cap = captained.get(eid, 0)
                rows.append({
                    "event": event, "element_id": eid, "n_managers": n_managers,
                    "owned": n_own, "captained": n_cap,
                    "owned_pct": round(n_own / n_managers, 6),
                    "captaincy_pct": round(n_cap / n_managers, 6),
                    "eo": round((n_own + n_cap) / n_managers, 6),
                })
            stmt = insert(elite_ownership).values(rows)
            s.execute(stmt.on_conflict_do_nothing(
                index_elements=["event", "element_id", "captured_at"]))
            s.commit()
        log.info("elite ownership aggregated",
                 extra={"event": event, "managers": n_managers, "elements": len(rows)})
        return OwnershipResult(event, n_managers, len(rows))


def latest_elite_eo(event: int, sm: sessionmaker[Session] | None = None) -> dict[int, float]:
    """element_id -> elite EO (%) for the latest aggregate of ``event`` (empty if none)."""
    sm = sm or get_sessionmaker()
    eo = elite_ownership.c
    with sm() as s:
        latest = s.execute(
            select(func.max(eo.captured_at)).where(eo.event == event)
        ).scalar_one_or_none()
        if latest is None:
            return {}
        rows = s.execute(
            select(eo.element_id, eo.eo).where(eo.event == event, eo.captured_at == latest)
        ).all()
    # Stored as a fraction; the overlay uses percent like selected_by_percent.
    return {r.element_id: float(r.eo) * 100.0 for r in rows}
