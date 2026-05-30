"""Build the cross-source id crosswalk (plan 1.2).

FPL side is deterministic: each season's ``players_raw`` row carries the
season-local element ``id`` *and* the stable cross-season ``code``. The code
is the canonical ``player_key``. Other sources (Understat/FBref) are matched
by normalised name (+team) with a fuzzy scorer, with a manual-override table
taking precedence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import id_crosswalk, id_overrides, player_identity
from ..ingest.vaastav import VaastavIngestor
from ..logging_setup import get_logger
from .names import best_match

log = get_logger(__name__)


@dataclass
class MatchResult:
    matched: int
    unmatched: int
    candidates: int


class CrosswalkBuilder:
    def __init__(self, vaastav: VaastavIngestor, sm: sessionmaker[Session] | None = None):
        self._vaastav = vaastav
        self._sm = sm or get_sessionmaker()

    def build_fpl(self, seasons: Iterable[str] | None = None) -> int:
        """Deterministically map every FPL season element id -> stable code."""
        seasons = tuple(seasons) if seasons is not None else self._vaastav.SEASONS
        identities: dict[int, dict] = {}
        xwalk_rows: list[dict] = []

        for season in seasons:
            rows = self._vaastav.latest_csv(season, "players_raw")
            if not rows:
                continue
            for r in rows:
                code = r.get("code")
                element = r.get("id")
                if not code or not element:
                    continue
                key = int(code)
                identities[key] = {
                    "player_key": key,
                    "web_name": r.get("web_name"),
                    "first_name": r.get("first_name"),
                    "second_name": r.get("second_name"),
                    "last_season": season,  # seasons iterate ascending -> ends latest
                }
                xwalk_rows.append({
                    "source": "fpl",
                    "season": season,
                    "source_id": str(element),
                    "player_key": key,
                    "source_name": f"{r.get('first_name','')} {r.get('second_name','')}".strip(),
                    "source_team": r.get("team"),
                    "match_method": "deterministic_code",
                    "confidence": 1.0,
                })

        if not identities:
            return 0

        with self._sm() as s:
            id_stmt = insert(player_identity).values(list(identities.values()))
            s.execute(id_stmt.on_conflict_do_update(
                index_elements=["player_key"],
                set_={c: id_stmt.excluded[c]
                      for c in ("web_name", "first_name", "second_name", "last_season")},
            ))
            # Batch crosswalk upsert.
            for i in range(0, len(xwalk_rows), 1000):
                chunk = xwalk_rows[i:i + 1000]
                x_stmt = insert(id_crosswalk).values(chunk)
                s.execute(x_stmt.on_conflict_do_update(
                    index_elements=["source", "season", "source_id"],
                    set_={c: x_stmt.excluded[c]
                          for c in ("player_key", "source_name", "source_team",
                                    "match_method", "confidence")},
                ))
            s.commit()
        log.info("fpl crosswalk built", extra={"identities": len(identities),
                                               "rows": len(xwalk_rows)})
        return len(xwalk_rows)

    def _identity_candidates(self, s: Session) -> list[tuple[str, int]]:
        rows = s.execute(
            select(player_identity.c.player_key, player_identity.c.web_name,
                   player_identity.c.first_name, player_identity.c.second_name)
        ).all()
        out: list[tuple[str, int]] = []
        for r in rows:
            # web_name + full name only; a bare surname invites collisions
            # between different players (the margin guard catches the rest).
            for nm in (r.web_name, f"{r.first_name or ''} {r.second_name or ''}".strip()):
                if nm:
                    out.append((nm, r.player_key))
        return out

    def match_source(
        self,
        source: str,
        season: str,
        records: Iterable[dict],
        *,
        id_field: str = "id",
        name_field: str = "name",
        team_field: str | None = None,
        threshold: float = 0.84,
    ) -> MatchResult:
        """Fuzzy-match an external source's per-season players to player_key.

        Overrides are applied first; remaining records are matched by name.
        """
        records = list(records)
        with self._sm() as s:
            overrides = {
                row.source_id: row.player_key
                for row in s.execute(
                    select(id_overrides.c.source_id, id_overrides.c.player_key).where(
                        id_overrides.c.source == source, id_overrides.c.season == season
                    )
                ).all()
            }
            candidates = self._identity_candidates(s)

            matched = 0
            unmatched = 0
            rows: list[dict] = []
            for rec in records:
                src_id = str(rec.get(id_field))
                name = rec.get(name_field) or ""
                if src_id in overrides:
                    key, score, method = overrides[src_id], 1.0, "override"
                else:
                    key, score = best_match(name, candidates, threshold=threshold)
                    method = "fuzzy_name"
                if key is None:
                    unmatched += 1
                    continue
                matched += 1
                rows.append({
                    "source": source, "season": season, "source_id": src_id,
                    "player_key": int(key), "source_name": name,
                    "source_team": rec.get(team_field) if team_field else None,
                    "match_method": method, "confidence": round(float(score), 4),
                })

            for i in range(0, len(rows), 1000):
                chunk = rows[i:i + 1000]
                if not chunk:
                    continue
                stmt = insert(id_crosswalk).values(chunk)
                s.execute(stmt.on_conflict_do_update(
                    index_elements=["source", "season", "source_id"],
                    set_={c: stmt.excluded[c] for c in
                          ("player_key", "source_name", "source_team",
                           "match_method", "confidence")},
                ))
            s.commit()
        log.info("source matched", extra={"source": source, "season": season,
                                          "matched": matched, "unmatched": unmatched})
        return MatchResult(matched, unmatched, len(records))

    def fpl_coverage(self, seasons: Iterable[str] | None = None) -> dict[str, float]:
        """Fraction of player-seasons with minutes>0 that have an FPL crosswalk row."""
        seasons = tuple(seasons) if seasons is not None else self._vaastav.SEASONS
        out: dict[str, float] = {}
        with self._sm() as s:
            for season in seasons:
                gw = self._vaastav.latest_csv(season, "merged_gw")
                if not gw:
                    continue
                played: set[str] = set()
                for r in gw:
                    try:
                        if int(r.get("minutes") or 0) > 0:
                            played.add(str(r.get("element")))
                    except ValueError:
                        continue
                if not played:
                    continue
                mapped = {
                    row[0] for row in s.execute(
                        select(id_crosswalk.c.source_id).where(
                            id_crosswalk.c.source == "fpl",
                            id_crosswalk.c.season == season,
                            id_crosswalk.c.source_id.in_(played),
                        )
                    ).all()
                }
                out[season] = round(len(mapped) / len(played), 4)
        return out
