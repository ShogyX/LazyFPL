"""Official FPL API ingestor (Phase 1/5 slice).

Pulls bootstrap-static and fixtures through the shared fetch+snapshot layer,
then projects the current-state teams/players into the NORMALISED layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import players as players_t
from ..db.models import teams as teams_t
from ..logging_setup import get_logger
from .fetch import FetchClient

log = get_logger(__name__)


def _num(value: Any) -> Any:
    """Pass-through; FPL returns numeric strings for some fields."""
    return value


@dataclass
class BootstrapResult:
    snapshot_id: int | None
    deduped: bool
    teams: int
    players: int


class FplIngestor:
    PROVIDER = "fpl"

    def __init__(self, fetch: FetchClient, sm: sessionmaker[Session] | None = None):
        self._fetch = fetch
        self._sm = sm or get_sessionmaker()

    def ingest_bootstrap(self) -> BootstrapResult:
        res = self._fetch.get(self.PROVIDER, "/bootstrap-static/", cache_ttl=0)
        data = res.payload
        n_teams = self._upsert_teams(data.get("teams", []))
        n_players = self._upsert_players(data.get("elements", []))
        log.info(
            "fpl bootstrap ingested",
            extra={"snapshot_id": res.snapshot_id, "deduped": res.deduped,
                   "teams": n_teams, "players": n_players},
        )
        return BootstrapResult(res.snapshot_id, res.deduped, n_teams, n_players)

    def ingest_fixtures(self) -> int:
        """Snapshot the fixtures feed; returns the count of fixtures."""
        res = self._fetch.get(self.PROVIDER, "/fixtures/", cache_ttl=0)
        count = len(res.payload) if isinstance(res.payload, list) else 0
        log.info("fpl fixtures ingested", extra={"snapshot_id": res.snapshot_id, "count": count})
        return count

    def _upsert_teams(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        values = [
            {
                "id": r["id"],
                "code": r.get("code"),
                "name": r["name"],
                "short_name": r.get("short_name"),
                "strength": r.get("strength"),
                "strength_overall_home": r.get("strength_overall_home"),
                "strength_overall_away": r.get("strength_overall_away"),
                "strength_attack_home": r.get("strength_attack_home"),
                "strength_attack_away": r.get("strength_attack_away"),
                "strength_defence_home": r.get("strength_defence_home"),
                "strength_defence_away": r.get("strength_defence_away"),
            }
            for r in rows
        ]
        with self._sm() as s:
            stmt = insert(teams_t).values(values)
            update_cols = {c: stmt.excluded[c] for c in values[0] if c != "id"}
            update_cols["updated_at"] = func.now()
            s.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols))
            s.commit()
        return len(values)

    def _upsert_players(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        values = [
            {
                "id": r["id"],
                "code": r.get("code"),
                "web_name": r.get("web_name"),
                "first_name": r.get("first_name"),
                "second_name": r.get("second_name"),
                "team_id": r.get("team"),
                "element_type": r.get("element_type"),
                "now_cost": r.get("now_cost"),
                "status": r.get("status"),
                "selected_by_percent": _num(r.get("selected_by_percent")),
                "total_points": r.get("total_points"),
                "minutes": r.get("minutes"),
                "form": _num(r.get("form")),
                "ep_next": _num(r.get("ep_next")),
            }
            for r in rows
        ]
        with self._sm() as s:
            stmt = insert(players_t).values(values)
            update_cols = {c: stmt.excluded[c] for c in values[0] if c != "id"}
            update_cols["updated_at"] = func.now()
            s.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols))
            s.commit()
        return len(values)
