"""Normalise Understat/FBref advanced stats into player_advanced_match_stats.

Resolution is two-legged:

* **player** — Understat's per-season player list is fuzzy-matched to the
  canonical ``player_key`` via the existing crosswalk (``match_source``), then
  each roster row's ``player_id`` is looked up in that crosswalk.
* **fixture** — Understat tags each match with home/away team *titles* + a date.
  We map titles to FPL ``team_id`` (alias + fuzzy) and look up the FPL
  ``fixture_id`` in ``team_match_stats`` keyed by (home_team_id, match_date).

Either leg may fail (new player, missing fixture facts); rows are still written
keyed on the source's own ids, with ``player_key``/``fixture_id`` left null and
counted in the result so coverage is observable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import (
    id_crosswalk,
    player_advanced_match_stats,
    team_match_stats,
    teams as teams_t,
)
from ..ingest.understat import UnderstatIngestor
from ..logging_setup import get_logger
from ..resolve.crosswalk import CrosswalkBuilder
from ..resolve.names import normalize_name, resolve_team

log = get_logger(__name__)


def _num(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _int(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f is not None else None


def _match_date(dt: str | None) -> date | None:
    if not dt:
        return None
    try:
        return datetime.fromisoformat(str(dt).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(str(dt)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


@dataclass
class AdvancedBuildResult:
    season: str
    rows_written: int
    players_resolved: int
    players_unresolved: int
    fixtures_resolved: int
    fixtures_unresolved: int


class AdvancedStatsBuilder:
    def __init__(self, understat: UnderstatIngestor,
                 crosswalk: CrosswalkBuilder,
                 sm: sessionmaker[Session] | None = None):
        self._us = understat
        self._xwalk = crosswalk
        self._sm = sm or get_sessionmaker()

    # -- resolvers --
    def _team_index(self, s: Session) -> dict[str, int]:
        index: dict[str, int] = {}
        for tid, name, short in s.execute(
            select(teams_t.c.id, teams_t.c.name, teams_t.c.short_name)
        ).all():
            for label in (name, short):
                if label:
                    index[normalize_name(label)] = tid
        return index

    def _fixture_index(self, s: Session, season: str) -> dict[tuple[int, date], int]:
        """(home_team_id, kickoff_date) -> fixture_id from the FPL fact table."""
        rows = s.execute(
            select(team_match_stats.c.fixture_id, team_match_stats.c.team_id,
                   team_match_stats.c.kickoff_time)
            .where(team_match_stats.c.season == season,
                   team_match_stats.c.was_home.is_(True))
        ).all()
        out: dict[tuple[int, date], int] = {}
        for r in rows:
            if r.team_id is not None and r.kickoff_time is not None:
                out[(r.team_id, r.kickoff_time.date())] = r.fixture_id
        return out

    def _key_map(self, s: Session, source: str, season: str) -> dict[str, int]:
        rows = s.execute(
            select(id_crosswalk.c.source_id, id_crosswalk.c.player_key).where(
                id_crosswalk.c.source == source, id_crosswalk.c.season == season)
        ).all()
        return {r.source_id: r.player_key for r in rows}

    # -- build --
    def build_understat(self, seasons: Iterable[str] | None = None
                        ) -> list[AdvancedBuildResult]:
        seasons = tuple(seasons) if seasons is not None else self._us.SEASONS
        results: list[AdvancedBuildResult] = []
        for season in seasons:
            players = self._us.league_players(season)
            dates = self._us.league_dates(season)
            if not dates:
                continue
            # Leg 1: resolve this season's Understat players -> player_key.
            if players:
                self._xwalk.match_source(
                    "understat", season, players,
                    id_field="id", name_field="player_name", team_field="team_title")

            match_meta = {
                str(d["id"]): {
                    "date": _match_date(d.get("datetime")),
                    "home": (d.get("h") or {}).get("title"),
                    "away": (d.get("a") or {}).get("title"),
                }
                for d in dates
                if d.get("id") is not None and d.get("isResult", True)
            }

            with self._sm() as s:
                pk_map = self._key_map(s, "understat", season)
                team_index = self._team_index(s)
                fixture_index = self._fixture_index(s, season)

                rows: list[dict] = []
                fixtures_hit = fixtures_miss = 0
                players_hit = players_miss = 0
                for mid, meta in match_meta.items():
                    home_id = resolve_team(meta["home"], team_index)
                    away_id = resolve_team(meta["away"], team_index)
                    fixture_id = (fixture_index.get((home_id, meta["date"]))
                                  if home_id is not None and meta["date"] else None)
                    for r in self._us.match_rosters(season, mid):
                        spid = str(r.get("player_id"))
                        pk = pk_map.get(spid)
                        if pk is None:
                            players_miss += 1
                        else:
                            players_hit += 1
                        was_home = r.get("side") == "h"
                        rows.append({
                            "source": "understat", "season": season,
                            "source_match_id": mid, "source_player_id": spid,
                            "player_key": pk, "fixture_id": fixture_id,
                            "source_team": r.get("team"),
                            "source_opponent": meta["away"] if was_home else meta["home"],
                            "was_home": was_home, "match_date": meta["date"],
                            "minutes": _int(r.get("time")), "position": r.get("position"),
                            "goals": _num(r.get("goals")), "assists": _num(r.get("assists")),
                            "npg": _num(r.get("npg")), "xg": _num(r.get("xG")),
                            "xa": _num(r.get("xA")), "npxg": _num(r.get("npxG")),
                            "key_passes": _num(r.get("key_passes")),
                            "shots": _num(r.get("shots")),
                            "xg_chain": _num(r.get("xGChain")),
                            "xg_buildup": _num(r.get("xGBuildup")),
                            "raw": r,
                        })
                    if fixture_id is not None:
                        fixtures_hit += 1
                    else:
                        fixtures_miss += 1

                _chunked_upsert(s, player_advanced_match_stats, rows,
                                ["source", "season", "source_match_id", "source_player_id"])
                s.commit()

            results.append(AdvancedBuildResult(
                season, len(rows), players_hit, players_miss,
                fixtures_hit, fixtures_miss))
            log.info("understat advanced stats built", extra={
                "season": season, "rows": len(rows),
                "players_resolved": players_hit, "fixtures_resolved": fixtures_hit})
        return results

    def build_fbref_match(
        self, season: str, match_ref: str, *, home_title: str, away_title: str,
        match_date: date | None, home_rows: list[dict], away_rows: list[dict],
    ) -> AdvancedBuildResult:
        """Normalise one FBref match report's two player tables.

        Players are resolved via the ``fbref`` crosswalk (run
        ``CrosswalkBuilder.match_source('fbref', season, ...)`` for the season
        first); the fixture is resolved by (home_team_id, match_date).
        """
        with self._sm() as s:
            pk_map = self._key_map(s, "fbref", season)
            team_index = self._team_index(s)
            fixture_index = self._fixture_index(s, season)

            home_id = resolve_team(home_title, team_index)
            fixture_id = (fixture_index.get((home_id, match_date))
                          if home_id is not None and match_date else None)

            rows: list[dict] = []
            players_hit = players_miss = 0
            for recs, was_home, team, opp in (
                (home_rows, True, home_title, away_title),
                (away_rows, False, away_title, home_title),
            ):
                for rec in recs:
                    spid = str(rec.get("_id") or rec.get("player"))
                    pk = pk_map.get(spid)
                    players_hit += pk is not None
                    players_miss += pk is None
                    rows.append(_fbref_row(
                        rec, season=season, match_ref=match_ref, pk=pk,
                        fixture_id=fixture_id, was_home=was_home,
                        team=team, opponent=opp, when=match_date))

            _chunked_upsert(s, player_advanced_match_stats, rows,
                            ["source", "season", "source_match_id", "source_player_id"])
            s.commit()
        log.info("fbref match built", extra={"season": season, "match": match_ref,
                                             "rows": len(rows), "players_resolved": players_hit})
        return AdvancedBuildResult(season, len(rows), players_hit, players_miss,
                                   1 if fixture_id is not None else 0,
                                   0 if fixture_id is not None else 1)


# FBref data-stat key -> our advanced-stats column.
_FBREF_MAP = {
    "minutes": "minutes", "goals": "goals", "assists": "assists",
    "xg": "xg", "npxg": "npxg", "xg_assist": "xa",
    "shots": "shots", "shots_total": "shots",
    "sca": "sca", "gca": "gca",
    "progressive_passes": "prog_passes", "progressive_carries": "prog_carries",
    "progressive_passes_received": "prog_passes_rec",
    "passes_completed": "passes_completed", "passes": "passes_attempted",
    "tackles": "tackles", "interceptions": "interceptions", "blocks": "blocks",
    "clearances": "clearances", "touches": "touches",
    "take_ons": "take_ons", "take_ons_won": "take_ons_won",
    "aerials_won": "aerials_won", "aerials_lost": "aerials_lost",
}


def _fbref_row(rec: dict, *, season: str, match_ref: str, pk: int | None,
               fixture_id: int | None, was_home: bool, team: str | None,
               opponent: str | None, when: date | None) -> dict:
    row: dict[str, Any] = {
        "source": "fbref", "season": season, "source_match_id": match_ref,
        "source_player_id": str(rec.get("_id") or rec.get("player")),
        "player_key": pk, "fixture_id": fixture_id, "source_team": team,
        "source_opponent": opponent, "was_home": was_home, "match_date": when,
        "position": rec.get("position"), "raw": rec,
    }
    # Uniform column set (None where absent) so a multi-row upsert of ragged
    # FBref rows renders the same columns for every row.
    for col in set(_FBREF_MAP.values()):
        row[col] = None
    for stat, col in _FBREF_MAP.items():
        if stat in rec:
            row[col] = _int(rec[stat]) if col == "minutes" else _num(rec[stat])
    return row


def _chunked_upsert(s: Session, table, rows: list[dict], conflict_cols: list[str]) -> None:
    for i in range(0, len(rows), 1000):
        chunk = rows[i:i + 1000]
        if not chunk:
            continue
        stmt = insert(table).values(chunk)
        update = {c: stmt.excluded[c] for c in chunk[0] if c not in conflict_cols}
        s.execute(stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update))
