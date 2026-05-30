"""FPL availability snapshots with flip detection (plan 5.4).

The FPL bootstrap mutates ``status`` / ``news`` / ``chance_of_playing`` in
place. To know *when* a player's availability changed (a red-flag appearing, a
return-to-training upgrade), we append a row to ``player_availability`` only
when the state differs from the last stored snapshot — so flips are detected
and timestamped without storing a row every poll.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import id_crosswalk, player_availability
from ..logging_setup import get_logger
from .fetch import FetchClient

log = get_logger(__name__)


def _int(v: Any) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _ts(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


# The availability state we track for change-detection.
_STATE = ("status", "news", "chance_this", "chance_next")


@dataclass
class AvailabilityResult:
    scanned: int
    flips: int


class AvailabilityIngestor:
    PROVIDER = "fpl"

    def __init__(self, fetch: FetchClient, sm: sessionmaker[Session] | None = None):
        self._fetch = fetch
        self._sm = sm or get_sessionmaker()

    def _latest_state(self, s: Session) -> dict[int, tuple]:
        """element_id -> last stored (status, news, chance_this, chance_next)."""
        # DISTINCT ON the most recent snapshot per element.
        rows = s.execute(
            select(player_availability.c.element_id, player_availability.c.status,
                   player_availability.c.news, player_availability.c.chance_this,
                   player_availability.c.chance_next, player_availability.c.captured_at)
            .order_by(player_availability.c.element_id,
                      player_availability.c.captured_at.desc())
            .distinct(player_availability.c.element_id)
        ).all()
        return {r.element_id: (r.status, r.news, r.chance_this, r.chance_next)
                for r in rows}

    def _fpl_key_map(self, s: Session) -> dict[str, int]:
        """Current-season FPL element_id (str) -> player_key, if resolved."""
        latest = s.execute(
            select(func.max(id_crosswalk.c.season)).where(id_crosswalk.c.source == "fpl")
        ).scalar_one_or_none()
        if latest is None:
            return {}
        rows = s.execute(
            select(id_crosswalk.c.source_id, id_crosswalk.c.player_key).where(
                id_crosswalk.c.source == "fpl", id_crosswalk.c.season == latest)
        ).all()
        return {r.source_id: r.player_key for r in rows}

    def snapshot_from_bootstrap(self) -> AvailabilityResult:
        res = self._fetch.get(self.PROVIDER, "/bootstrap-static/", cache_ttl=0)
        elements = res.payload.get("elements", []) if isinstance(res.payload, dict) else []
        with self._sm() as s:
            previous = self._latest_state(s)
            key_map = self._fpl_key_map(s)
            new_rows: list[dict] = []
            for e in elements:
                eid = _int(e.get("id"))
                if eid is None:
                    continue
                state = (e.get("status"), e.get("news"),
                         _int(e.get("chance_of_playing_this_round")),
                         _int(e.get("chance_of_playing_next_round")))
                if previous.get(eid) == state:
                    continue  # unchanged -> no new snapshot
                new_rows.append({
                    "element_id": eid,
                    "player_key": key_map.get(str(eid)),
                    "status": state[0], "news": state[1],
                    "news_added": _ts(e.get("news_added")),
                    "chance_this": state[2], "chance_next": state[3],
                    "source": "fpl",
                })
            if new_rows:
                s.execute(player_availability.insert(), new_rows)
                s.commit()
        log.info("availability snapshot", extra={"scanned": len(elements),
                                                 "flips": len(new_rows)})
        return AvailabilityResult(len(elements), len(new_rows))
