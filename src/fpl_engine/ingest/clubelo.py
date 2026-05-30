"""ClubElo daily team Elo (free CSV API, plan 1.1).

``GET /{YYYY-MM-DD}`` returns every club's Elo on that date as CSV
(Rank,Club,Country,Level,Elo,From,To). We snapshot it raw and normalise the
English top-flight rows into ``normalised.team_elo``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import team_elo, teams as teams_t
from ..logging_setup import get_logger
from ..resolve.names import best_match, normalize_name
from .fetch import FetchClient
from .vaastav import parse_csv

log = get_logger(__name__)

# ClubElo club name (normalised) -> the FPL team name/short it actually denotes.
_CLUB_ALIASES = {
    "man united": "man utd",
    "forest": "nott m forest",  # normalize("Nott'm Forest") drops the apostrophe
    "tottenham": "spurs",
}


def _text(payload: Any) -> str:
    if isinstance(payload, dict) and "_text" in payload:
        return payload["_text"]
    return payload if isinstance(payload, str) else ""


def _num(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


class ClubEloIngestor:
    PROVIDER = "clubelo"

    def __init__(self, fetch: FetchClient, sm: sessionmaker[Session] | None = None):
        self._fetch = fetch
        self._sm = sm or get_sessionmaker()

    def ingest(self, on: date | None = None, country: str = "ENG") -> int:
        on = on or date.today()
        path = f"/{on.isoformat()}"
        res = self._fetch.get(self.PROVIDER, path)
        if res.status_code != 200:
            log.warning("clubelo fetch failed", extra={"status": res.status_code})
            return 0
        rows = parse_csv(_text(res.payload))
        with self._sm() as s:
            team_index = self._fpl_team_index(s)
            values = [
                {
                    "club": r.get("Club"),
                    "snapshot_date": on,
                    "elo": _num(r.get("Elo")),
                    "country": r.get("Country"),
                    "level": int(r["Level"]) if r.get("Level") not in (None, "") else None,
                    "fpl_team_id": self._match_team(r.get("Club"), team_index),
                }
                for r in rows
                if r.get("Country") == country and r.get("Club")
            ]
            if not values:
                return 0
            stmt = insert(team_elo).values(values)
            s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["club", "snapshot_date"],
                    set_={
                        "elo": stmt.excluded.elo,
                        "level": stmt.excluded.level,
                        "country": stmt.excluded.country,
                        "fpl_team_id": stmt.excluded.fpl_team_id,
                    },
                )
            )
            s.commit()
        mapped = sum(1 for v in values if v["fpl_team_id"] is not None)
        log.info("clubelo ingested", extra={"date": on.isoformat(),
                                             "clubs": len(values), "mapped": mapped})
        return len(values)

    @staticmethod
    def _fpl_team_index(s: Session) -> dict[str, int]:
        """Normalised FPL team name/short_name -> team id."""
        index: dict[str, int] = {}
        for tid, name, short in s.execute(
            select(teams_t.c.id, teams_t.c.name, teams_t.c.short_name)
        ).all():
            for label in (name, short):
                if label:
                    index[normalize_name(label)] = tid
        return index

    @staticmethod
    def _match_team(club: str | None, index: dict[str, int]) -> int | None:
        if not club or not index:
            return None
        key = normalize_name(club)
        key = _CLUB_ALIASES.get(key, key)
        if key in index:
            return index[key]
        match, _score = best_match(key, [(n, i) for n, i in index.items()], threshold=0.8)
        return match  # None if no confident FPL team (e.g. non-PL club)
