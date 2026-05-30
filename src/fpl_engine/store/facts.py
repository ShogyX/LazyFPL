"""Normalised per-match fact builders (plan 1.3).

``player_match_stats`` from vaastav ``merged_gw`` (keyed by canonical
player_key via the FPL crosswalk); ``team_match_stats`` from ``fixtures``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import id_crosswalk, player_match_stats, team_match_stats
from ..ingest.vaastav import VaastavIngestor
from ..logging_setup import get_logger

log = get_logger(__name__)


def _int(v: Any) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _bool(v: Any) -> bool | None:
    if v in (None, ""):
        return None
    return str(v).strip().lower() in ("true", "1", "t", "yes")


def _ts(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


_PMS_COLS = (
    "minutes", "starts", "goals_scored", "assists", "clean_sheets", "goals_conceded",
    "own_goals", "penalties_saved", "penalties_missed", "saves", "yellow_cards",
    "red_cards", "bonus", "bps",
)
_PMS_FLOATS = ("influence", "creativity", "threat", "ict_index",
               "expected_goals", "expected_assists", "expected_goal_involvements",
               "expected_goals_conceded")

# merged_gw `position` string -> FPL element_type, used as a fallback when
# players_raw lacks the element (keeps element_type populated for all seasons).
_POSITION_MAP = {"GK": 1, "GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}


@dataclass
class BuildResult:
    season: str
    rows_in: int
    rows_written: int
    skipped: int
    duplicates: int = 0


def _dedupe(rows: list[dict], key_cols: tuple[str, ...]) -> tuple[list[dict], int]:
    """Collapse rows sharing the PK (last wins); return (unique_rows, n_dupes)."""
    by_key: dict[tuple, dict] = {}
    for r in rows:
        by_key[tuple(r[c] for c in key_cols)] = r
    return list(by_key.values()), len(rows) - len(by_key)


def _chunked_upsert(s: Session, table, rows: list[dict], conflict_cols: list[str]) -> None:
    for i in range(0, len(rows), 1000):
        chunk = rows[i:i + 1000]
        if not chunk:
            continue
        stmt = insert(table).values(chunk)
        update = {c: stmt.excluded[c] for c in chunk[0] if c not in conflict_cols}
        s.execute(stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update))


class FactBuilder:
    def __init__(self, vaastav: VaastavIngestor, sm: sessionmaker[Session] | None = None):
        self._vaastav = vaastav
        self._sm = sm or get_sessionmaker()

    def _fpl_key_map(self, s: Session, season: str) -> dict[str, int]:
        rows = s.execute(
            select(id_crosswalk.c.source_id, id_crosswalk.c.player_key).where(
                id_crosswalk.c.source == "fpl", id_crosswalk.c.season == season
            )
        ).all()
        return {r.source_id: r.player_key for r in rows}

    def _element_type_map(self, season: str) -> dict[int, int]:
        """element_id -> element_type (1 GK, 2 DEF, 3 MID, 4 FWD) from players_raw."""
        raw = self._vaastav.latest_csv(season, "players_raw")
        out: dict[int, int] = {}
        if not raw:
            return out
        for r in raw:
            eid, et = _int(r.get("id")), _int(r.get("element_type"))
            if eid is not None and et is not None:
                out[eid] = et
        return out

    def build_player_match_stats(self, seasons: Iterable[str] | None = None) -> list[BuildResult]:
        seasons = tuple(seasons) if seasons is not None else self._vaastav.SEASONS
        results: list[BuildResult] = []
        for season in seasons:
            gw = self._vaastav.latest_csv(season, "merged_gw")
            if not gw:
                continue
            et_map = self._element_type_map(season)
            with self._sm() as s:
                key_map = self._fpl_key_map(s, season)
                rows: list[dict] = []
                skipped = 0
                for r in gw:
                    element = _int(r.get("element"))
                    fixture = _int(r.get("fixture"))
                    gw_num = _int(r.get("round")) or _int(r.get("GW"))
                    if element is None or fixture is None or gw_num is None:
                        skipped += 1
                        continue
                    rec = {
                        "season": season,
                        "element_id": element,
                        "fixture_id": fixture,
                        "player_key": key_map.get(str(element)),
                        "gw": gw_num,
                        "team_id": None,
                        "opponent_team_id": _int(r.get("opponent_team")),
                        "was_home": _bool(r.get("was_home")),
                        "total_points": _int(r.get("total_points")),
                        "value": _int(r.get("value")),
                        "selected": _int(r.get("selected")),
                        "transfers_balance": _int(r.get("transfers_balance")),
                        "kickoff_time": _ts(r.get("kickoff_time")),
                        "element_type": et_map.get(element)
                            or _POSITION_MAP.get((r.get("position") or "").upper()),
                        "tackles": _int(r.get("tackles")),
                        "clearances_blocks_interceptions":
                            _int(r.get("clearances_blocks_interceptions")),
                        "recoveries": _int(r.get("recoveries")),
                        "defensive_contribution": _int(r.get("defensive_contribution")),
                        "raw": r,
                    }
                    for c in _PMS_COLS:
                        rec[c] = _int(r.get(c))
                    for c in _PMS_FLOATS:
                        rec[c] = _float(r.get(c))
                    rows.append(rec)
                unique, dupes = _dedupe(rows, ("season", "element_id", "fixture_id"))
                _chunked_upsert(s, player_match_stats, unique,
                                ["season", "element_id", "fixture_id"])
                s.commit()
            results.append(BuildResult(season, len(gw), len(unique), skipped, dupes))
            log.info("player_match_stats built", extra={"season": season,
                                                         "rows": len(unique), "skipped": skipped,
                                                         "duplicates": dupes})
        return results

    def build_team_match_stats(self, seasons: Iterable[str] | None = None) -> list[BuildResult]:
        seasons = tuple(seasons) if seasons is not None else self._vaastav.SEASONS
        results: list[BuildResult] = []
        for season in seasons:
            fixtures = self._vaastav.latest_csv(season, "fixtures")
            if not fixtures:
                continue
            rows: list[dict] = []
            skipped = 0
            for f in fixtures:
                fid = _int(f.get("id"))
                home = _int(f.get("team_h"))
                away = _int(f.get("team_a"))
                if fid is None or home is None or away is None:
                    skipped += 1
                    continue
                hs, as_ = _int(f.get("team_h_score")), _int(f.get("team_a_score"))
                gw_num = _int(f.get("event"))
                kickoff = _ts(f.get("kickoff_time"))
                rows.append(self._team_row(season, fid, home, away, True, hs, as_,
                                           gw_num, kickoff, _int(f.get("team_h_difficulty"))))
                rows.append(self._team_row(season, fid, away, home, False, as_, hs,
                                           gw_num, kickoff, _int(f.get("team_a_difficulty"))))
            unique, dupes = _dedupe(rows, ("season", "fixture_id", "team_id"))
            with self._sm() as s:
                _chunked_upsert(s, team_match_stats, unique,
                                ["season", "fixture_id", "team_id"])
                s.commit()
            results.append(BuildResult(season, len(fixtures), len(unique), skipped, dupes))
            log.info("team_match_stats built", extra={"season": season, "rows": len(unique)})
        return results

    @staticmethod
    def _team_row(season, fid, team, opp, home, gf, ga, gw, kickoff, difficulty) -> dict:
        result = points = None
        if gf is not None and ga is not None:
            if gf > ga:
                result, points = "W", 3
            elif gf == ga:
                result, points = "D", 1
            else:
                result, points = "L", 0
        return {
            "season": season, "fixture_id": fid, "team_id": team,
            "opponent_team_id": opp, "gw": gw, "was_home": home,
            "goals_for": gf, "goals_against": ga, "result": result,
            "points": points, "difficulty": difficulty, "kickoff_time": kickoff,
        }

    def reconcile(self, seasons: Iterable[str] | None = None) -> dict[str, dict]:
        """Reconcile raw merged_gw against normalised player_match_stats.

        Recomputes, from the raw CSV, the count of valid rows (those with
        element/fixture/gw) and the count of *distinct* PKs, then checks the
        normalised table holds exactly that many rows. ``ok`` is true only when
        every raw row is accounted for: ``raw = unique + skipped + duplicates``
        and ``normalised == unique``.
        """
        from sqlalchemy import func

        seasons = tuple(seasons) if seasons is not None else self._vaastav.SEASONS
        out: dict[str, dict] = {}
        with self._sm() as s:
            for season in seasons:
                gw = self._vaastav.latest_csv(season, "merged_gw")
                if not gw:
                    continue
                keys: set[tuple[int, int]] = set()
                skipped = 0
                for r in gw:
                    element = _int(r.get("element"))
                    fixture = _int(r.get("fixture"))
                    gw_num = _int(r.get("round")) or _int(r.get("GW"))
                    if element is None or fixture is None or gw_num is None:
                        skipped += 1
                        continue
                    keys.add((element, fixture))
                unique = len(keys)
                duplicates = len(gw) - skipped - unique
                norm = int(s.execute(
                    select(func.count()).select_from(player_match_stats).where(
                        player_match_stats.c.season == season
                    )
                ).scalar_one())
                out[season] = {
                    "raw_rows": len(gw),
                    "valid_unique": unique,
                    "skipped": skipped,
                    "duplicates": duplicates,
                    "normalised_rows": norm,
                    "ok": norm == unique and len(gw) == unique + skipped + duplicates,
                }
        return out
