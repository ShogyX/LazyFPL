"""Feature-availability matrix (plan 3.1 / B.1 "ragged-history rule").

Records, per (metric, season), how many player-match rows carry the metric, so
the study can validate each feature only over the span it actually exists and
report findings with their ``n_seasons``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import (
    feature_availability,
    player_advanced_match_stats,
    player_match_stats,
)
from ..logging_setup import get_logger

log = get_logger(__name__)

# metric column -> source tag (provenance / confidence).
METRIC_SOURCES: dict[str, str] = {
    "minutes": "fpl_basic", "goals_scored": "fpl_basic", "assists": "fpl_basic",
    "clean_sheets": "fpl_basic", "goals_conceded": "fpl_basic", "saves": "fpl_basic",
    "bonus": "fpl_basic", "bps": "fpl_basic", "ict_index": "fpl_basic",
    "influence": "fpl_basic", "creativity": "fpl_basic", "threat": "fpl_basic",
    "expected_goals": "fpl_xg", "expected_assists": "fpl_xg",
    "expected_goal_involvements": "fpl_xg", "expected_goals_conceded": "fpl_xg",
    "tackles": "dc", "clearances_blocks_interceptions": "dc",
    "recoveries": "dc", "defensive_contribution": "dc",
}

# Advanced metrics live in player_advanced_match_stats (shorter, ragged span).
ADVANCED_METRIC_SOURCES: dict[str, str] = {
    "npxg": "understat", "xg_chain": "understat", "xg_buildup": "understat",
    "key_passes": "understat", "shots": "understat",
    "sca": "fbref", "gca": "fbref", "prog_passes": "fbref", "prog_carries": "fbref",
}


@dataclass
class AvailabilityRow:
    metric: str
    season: str
    source: str
    n_rows: int
    n_present: int
    coverage: float


class AvailabilityBuilder:
    def __init__(self, sm: sessionmaker[Session] | None = None):
        self._sm = sm or get_sessionmaker()

    def build(self, seasons: Iterable[str] | None = None) -> list[AvailabilityRow]:
        pms = player_match_stats.c
        out: list[AvailabilityRow] = []
        with self._sm() as s:
            if seasons is None:
                seasons = [r[0] for r in s.execute(
                    select(pms.season).distinct()).all()]
            for season in seasons:
                n_rows = int(s.execute(
                    select(func.count()).select_from(player_match_stats).where(
                        pms.season == season)).scalar_one())
                if not n_rows:
                    continue
                rows: list[dict] = []
                for metric, source in METRIC_SOURCES.items():
                    col = pms[metric]
                    n_present = int(s.execute(
                        select(func.count()).select_from(player_match_stats).where(
                            pms.season == season, col.isnot(None))).scalar_one())
                    coverage = round(n_present / n_rows, 4)
                    rows.append({"metric": metric, "season": season, "source": source,
                                 "n_rows": n_rows, "n_present": n_present,
                                 "coverage": coverage})
                    out.append(AvailabilityRow(metric, season, source, n_rows,
                                               n_present, coverage))

                # Advanced metrics: count distinct resolved (player_key, fixture)
                # appearances carrying the metric, against the season's PMS rows.
                adv = player_advanced_match_stats.c
                for metric, source in ADVANCED_METRIC_SOURCES.items():
                    n_present = int(s.execute(
                        select(func.count(func.distinct(
                            func.concat(adv.player_key, ":", adv.fixture_id))))
                        .where(adv.season == season, adv.player_key.isnot(None),
                               adv.fixture_id.isnot(None), adv[metric].isnot(None))
                    ).scalar_one())
                    coverage = round(n_present / n_rows, 4)
                    rows.append({"metric": metric, "season": season, "source": source,
                                 "n_rows": n_rows, "n_present": n_present,
                                 "coverage": coverage})
                    out.append(AvailabilityRow(metric, season, source, n_rows,
                                               n_present, coverage))
                stmt = insert(feature_availability).values(rows)
                s.execute(stmt.on_conflict_do_update(
                    index_elements=["metric", "season"],
                    set_={c: stmt.excluded[c] for c in
                          ("source", "n_rows", "n_present", "coverage")}))
                s.commit()
        log.info("feature_availability built", extra={"rows": len(out)})
        return out
