"""Rule-invariant targets + current-rules conversion (plan 2.2 / B.12).

For each player-match we record the realised components, then store:
  * ``actual_points``     — FPL total_points as recorded
  * ``as_played_points``  — converter under that season's rules
  * ``normalised_points`` — converter under CURRENT rules (rule-invariant)

The converter reproducing ``actual_points`` from ``as_played_points`` is the
correctness gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import dc_match, player_match_stats, targets
from ..logging_setup import get_logger
from ..model.scoring import CURRENT, GK, Components, rules_for_season, score

log = get_logger(__name__)


@dataclass
class TargetBuildResult:
    season: str
    rows: int
    converter_version: str


@dataclass
class ReproResult:
    season: str
    n: int
    exact: int
    mean_abs_error: float
    max_abs_error: int
    exact_rate: float


def _components(r) -> Components:
    return Components(
        element_type=r.element_type or 0,
        minutes=r.minutes or 0,
        goals_scored=r.goals_scored or 0,
        assists=r.assists or 0,
        clean_sheets=r.clean_sheets or 0,
        goals_conceded=r.goals_conceded or 0,
        saves=r.saves or 0,
        penalties_saved=r.penalties_saved or 0,
        penalties_missed=r.penalties_missed or 0,
        own_goals=r.own_goals or 0,
        yellow_cards=r.yellow_cards or 0,
        red_cards=r.red_cards or 0,
        bonus=r.bonus or 0,
    )


class TargetBuilder:
    def __init__(self, sm: sessionmaker[Session] | None = None):
        self._sm = sm or get_sessionmaker()

    def build(self, seasons: Iterable[str] | None = None) -> list[TargetBuildResult]:
        results: list[TargetBuildResult] = []
        with self._sm() as s:
            if seasons is None:
                seasons = [r[0] for r in s.execute(
                    select(player_match_stats.c.season).distinct()).all()]
            for season in seasons:
                results.append(self._build_season(s, season))
            s.commit()
        for r in results:
            log.info("targets built", extra={"season": r.season, "rows": r.rows})
        return results

    def _dc_hits(self, s: Session, season: str) -> dict[tuple[int, int], bool]:
        """(element_id, fixture_id) -> dc_hit for every observed dc_match row.

        Presence of a key also signals DC was observable for that row (used to
        flag whether normalised_points is known-complete).
        """
        dm = dc_match.c
        return {
            (r.element_id, r.fixture_id): bool(r.dc_hit)
            for r in s.execute(
                select(dm.element_id, dm.fixture_id, dm.dc_hit).where(dm.season == season)
            ).all()
        }

    def _build_season(self, s: Session, season: str) -> TargetBuildResult:
        pms = player_match_stats.c
        dc_hits = self._dc_hits(s, season)
        as_played_rules = rules_for_season(season)

        src = s.execute(
            select(
                pms.season, pms.element_id, pms.fixture_id, pms.player_key, pms.gw,
                pms.element_type, pms.minutes, pms.goals_scored, pms.assists,
                pms.clean_sheets, pms.goals_conceded, pms.saves, pms.penalties_saved,
                pms.penalties_missed, pms.own_goals, pms.yellow_cards, pms.red_cards,
                pms.bonus, pms.total_points,
            ).where(
                pms.season == season,
                # Four FPL positions only (decision E.3.8); the 2024/25
                # "Assistant Manager" elements (element_type 5) score via a
                # separate manager ruleset and are out of scope.
                pms.element_type.in_([1, 2, 3, 4]),
            )
        ).all()

        rows: list[dict] = []
        for r in src:
            key = (r.element_id, r.fixture_id)
            dc_hit = dc_hits.get(key, False)
            # normalised_points is known-complete iff DC was observable (GKs are
            # DC-ineligible so always complete); otherwise it is a lower bound.
            dc_known = (r.element_type == GK) or (key in dc_hits)
            c = _components(r)
            c.dc_hit = dc_hit  # ignored by rule sets where dc_enabled is False
            rows.append({
                "season": season, "element_id": r.element_id, "fixture_id": r.fixture_id,
                "player_key": r.player_key, "gw": r.gw, "element_type": r.element_type,
                "minutes": r.minutes, "actual_points": r.total_points,
                "as_played_points": score(c, as_played_rules),
                "normalised_points": score(c, CURRENT),
                "dc_hit": dc_hit,
                "dc_known": dc_known,
                "components": dict(c.__dict__),
                "converter_version": CURRENT.version,
            })

        for i in range(0, len(rows), 1000):
            chunk = rows[i:i + 1000]
            if not chunk:
                continue
            stmt = insert(targets).values(chunk)
            update = {c: stmt.excluded[c] for c in chunk[0]
                      if c not in ("season", "element_id", "fixture_id")}
            update["built_at"] = func.now()
            s.execute(stmt.on_conflict_do_update(
                index_elements=["season", "element_id", "fixture_id"], set_=update))
        return TargetBuildResult(season, len(rows), CURRENT.version)

    def reproduction(self, season: str) -> ReproResult:
        """How exactly as_played_points reproduces actual FPL points."""
        t = targets.c
        with self._sm() as s:
            rows = s.execute(
                select(t.actual_points, t.as_played_points).where(
                    t.season == season,
                    t.actual_points.isnot(None),
                    t.element_type.isnot(None),
                )
            ).all()
        n = len(rows)
        if n == 0:
            return ReproResult(season, 0, 0, 0.0, 0, 0.0)
        diffs = [abs(a - p) for a, p in rows]
        exact = sum(1 for d in diffs if d == 0)
        return ReproResult(
            season=season, n=n, exact=exact,
            mean_abs_error=round(sum(diffs) / n, 4),
            max_abs_error=max(diffs), exact_rate=round(exact / n, 4),
        )
