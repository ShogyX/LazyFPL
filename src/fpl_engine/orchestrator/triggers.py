"""Continuous trigger logic (plan 9.3).

Each trigger detects a class of change and, when something material moved, fires
a ``recompute`` (predict -> optimise -> recommend). Detection is dependency-
injected (a fetch client + the availability ingestor) and the recompute is a
plain callable, so the decision logic is unit-testable without a scheduler.

* **price_change** (~01:30 UK) — bootstrap ``cost_change_event`` != 0.
* **news_lineup** — availability flips (status/news/chance) + new lineups.
* **post_match** — ``/event-status`` reports bonus confirmed (provisional -> final).

(Odds-steam triggers are out of scope while the odds layer is iced.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

from ..ingest.availability import AvailabilityIngestor
from ..ingest.fetch import FetchClient
from ..logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class TriggerOutcome:
    trigger: str
    changed: int
    recomputed: bool


class TriggerEngine:
    PROVIDER = "fpl"

    def __init__(self, fetch: FetchClient, recompute: Callable[[], Any], *,
                 availability: AvailabilityIngestor | None = None,
                 sm: sessionmaker[Session] | None = None):
        self._fetch = fetch
        self._recompute = recompute
        self._availability = availability or AvailabilityIngestor(fetch, sm=sm)

    def _fire(self, trigger: str, changed: int) -> TriggerOutcome:
        recomputed = False
        if changed > 0:
            self._recompute()
            recomputed = True
        log.info("trigger evaluated", extra={"trigger": trigger, "changed": changed,
                                             "recomputed": recomputed})
        return TriggerOutcome(trigger, changed, recomputed)

    def price_watch(self) -> TriggerOutcome:
        """Recompute when any player's price moved this event."""
        res = self._fetch.get(self.PROVIDER, "/bootstrap-static/", cache_ttl=0)
        elements = res.payload.get("elements", []) if isinstance(res.payload, dict) else []
        changed = sum(1 for e in elements if int(e.get("cost_change_event") or 0) != 0)
        return self._fire("price_change", changed)

    def news_lineup_watch(self) -> TriggerOutcome:
        """Recompute on availability flips (snapshots them as a side effect)."""
        flips = self._availability.snapshot_from_bootstrap().flips
        return self._fire("news_lineup", flips)

    def post_match_recompute(self) -> TriggerOutcome:
        """Recompute once bonus is confirmed (provisional -> final points)."""
        res = self._fetch.get(self.PROVIDER, "/event-status/", cache_ttl=0)
        statuses = res.payload.get("status", []) if isinstance(res.payload, dict) else []
        confirmed = sum(1 for s in statuses if s.get("bonus_added"))
        return self._fire("post_match", confirmed)
