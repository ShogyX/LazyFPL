"""API-Football free-tier ingestor: lineups, injuries, referees (plan 5.4).

The free tier (100 req/day) is the structured lineup + injury feed. Each call
goes through the shared budget-gated fetch layer; the API key is sent as the
``x-apisports-key`` header (loaded from settings, never logged).

API-Football carries its own team/player ids; we keep those as ``*_ref`` and
additionally resolve to FPL ``team_id`` / ``player_key`` by name (best-effort,
nullable) so downstream joins work while raw refs remain for audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from ..db.engine import get_sessionmaker
from ..db.models import (
    injuries as injuries_t,
    lineups as lineups_t,
    match_officials,
    player_identity,
    teams as teams_t,
)
from ..logging_setup import get_logger
from ..resolve.names import best_match, normalize_name, resolve_team
from .fetch import FetchClient

log = get_logger(__name__)

EPL_LEAGUE_ID = 39  # API-Football's Premier League id


def _response_list(payload: Any) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("response"), list):
        return payload["response"]
    return []


class ApiFootballIngestor:
    PROVIDER = "api_football"

    def __init__(self, fetch: FetchClient, sm: sessionmaker[Session] | None = None):
        self._fetch = fetch
        self._sm = sm or get_sessionmaker()

    # -- auth --
    def _headers(self) -> dict[str, str]:
        key = get_settings().api_football_key
        return {"x-apisports-key": key.get_secret_value()} if key else {}

    def _get(self, path: str, params: dict[str, Any]):
        return self._fetch.get(self.PROVIDER, path, params=params,
                               extra_headers=self._headers())

    # -- resolvers --
    @staticmethod
    def _team_index(s: Session) -> dict[str, int]:
        index: dict[str, int] = {}
        for tid, name, short in s.execute(
            select(teams_t.c.id, teams_t.c.name, teams_t.c.short_name)
        ).all():
            for label in (name, short):
                if label:
                    index[normalize_name(label)] = tid
        return index

    @staticmethod
    def _identity_candidates(s: Session) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for r in s.execute(
            select(player_identity.c.player_key, player_identity.c.web_name,
                   player_identity.c.first_name, player_identity.c.second_name)
        ).all():
            for nm in (r.web_name, f"{r.first_name or ''} {r.second_name or ''}".strip()):
                if nm:
                    out.append((nm, r.player_key))
        return out

    @staticmethod
    def _resolve_player(name: str | None, candidates: list[tuple[str, int]]) -> int | None:
        if not name or not candidates:
            return None
        key, _ = best_match(name, candidates, threshold=0.86)
        return int(key) if key is not None else None

    # -- lineups --
    def ingest_lineups(self, fixture_ref: str | int) -> int:
        """GET /fixtures/lineups?fixture={id} -> per-player start/bench rows."""
        res = self._get("/fixtures/lineups", {"fixture": fixture_ref})
        if res.status_code != 200:
            log.warning("api-football lineups failed",
                        extra={"fixture": fixture_ref, "status": res.status_code})
            return 0
        rows: list[dict] = []
        with self._sm() as s:
            team_index = self._team_index(s)
            cands = self._identity_candidates(s)
            for team_block in _response_list(res.payload):
                team = (team_block.get("team") or {})
                team_name = team.get("name")
                team_id = resolve_team(team_name, team_index)
                formation = team_block.get("formation")
                for role, members in (("start", team_block.get("startXI") or []),
                                      ("bench", team_block.get("substitutes") or [])):
                    for m in members:
                        p = (m.get("player") or {})
                        pref = str(p.get("id"))
                        rows.append({
                            "source": self.PROVIDER, "fixture_ref": str(fixture_ref),
                            "player_ref": pref,
                            "team_ref": str(team.get("id")) if team.get("id") else None,
                            "team_id": team_id,
                            "player_key": self._resolve_player(p.get("name"), cands),
                            "role": role,
                            "confirmed": True,  # /lineups returns confirmed XIs
                            "formation": formation, "grid": p.get("grid"),
                        })
            _insert_ignore(s, lineups_t, rows,
                           ["source", "fixture_ref", "player_ref", "captured_at"])
            s.commit()
        log.info("api-football lineups ingested",
                 extra={"fixture": fixture_ref, "rows": len(rows)})
        return len(rows)

    # -- injuries --
    def ingest_injuries(self, season_year: int, league: int = EPL_LEAGUE_ID) -> int:
        """GET /injuries?league=39&season={year} -> injury rows."""
        res = self._get("/injuries", {"league": league, "season": season_year})
        if res.status_code != 200:
            log.warning("api-football injuries failed", extra={"status": res.status_code})
            return 0
        rows: list[dict] = []
        with self._sm() as s:
            team_index = self._team_index(s)
            cands = self._identity_candidates(s)
            for rec in _response_list(res.payload):
                p = rec.get("player") or {}
                team = rec.get("team") or {}
                fixture = rec.get("fixture") or {}
                rows.append({
                    "source": self.PROVIDER, "player_ref": str(p.get("id")),
                    "player_key": self._resolve_player(p.get("name"), cands),
                    "team_ref": str(team.get("id")) if team.get("id") else None,
                    "team_id": resolve_team(team.get("name"), team_index),
                    "fixture_ref": str(fixture.get("id")) if fixture.get("id") else None,
                    "type": p.get("type"), "reason": p.get("reason"),
                })
            _insert_ignore(s, injuries_t, rows,
                           ["source", "player_ref", "captured_at"])
            s.commit()
        log.info("api-football injuries ingested", extra={"rows": len(rows)})
        return len(rows)

    # -- referees (from the fixtures feed) --
    def ingest_referees(self, season_year: int, league: int = EPL_LEAGUE_ID) -> int:
        """GET /fixtures?league=39&season={year} -> referee per fixture."""
        res = self._get("/fixtures", {"league": league, "season": season_year})
        if res.status_code != 200:
            log.warning("api-football fixtures failed", extra={"status": res.status_code})
            return 0
        rows: list[dict] = []
        for rec in _response_list(res.payload):
            fixture = rec.get("fixture") or {}
            ref = fixture.get("referee")
            if not ref:
                continue
            rows.append({
                "source": self.PROVIDER, "fixture_ref": str(fixture.get("id")),
                "referee": ref,
            })
        if rows:
            with self._sm() as s:
                _insert_ignore(s, match_officials, rows,
                               ["source", "fixture_ref", "captured_at"])
                s.commit()
        log.info("api-football referees ingested", extra={"rows": len(rows)})
        return len(rows)


def _insert_ignore(s: Session, table, rows: list[dict], conflict_cols: list[str]) -> None:
    for i in range(0, len(rows), 1000):
        chunk = rows[i:i + 1000]
        if not chunk:
            continue
        stmt = insert(table).values(chunk)
        s.execute(stmt.on_conflict_do_nothing(index_elements=conflict_cols))
