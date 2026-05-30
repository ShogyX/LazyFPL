"""Defensive Contribution reconstruction (plan 2.1 / B.13).

CBIT  (DEF)      = clearances+blocks+interceptions + tackles            >= 10
CBIRT (MID/FWD)  = CBIT + recoveries                                    >= 12
GKs are ineligible. The DC components are present in vaastav merged_gw from
2025/26; for earlier seasons they must be reconstructed from FBref (deferred
acquisition) and carry ``recoveries_imputed``.

Validation: on the 2025/26 overlap the reconstructed ``dc_value`` is checked
against FPL's official ``defensive_contribution`` (the clean feed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import dc_match, player_match_stats
from ..logging_setup import get_logger
from ..model.scoring import CURRENT, DEF, FWD, MID, dc_threshold

log = get_logger(__name__)


@dataclass
class DcBuildResult:
    season: str
    rows: int


@dataclass
class DcValidation:
    season: str
    n: int
    exact: int
    mismatches: int
    mean_abs_diff: float
    agreement: float


def _dc_value(element_type: int | None, cbit: int | None, cbirt: int | None) -> int | None:
    if element_type == DEF:
        return cbit
    if element_type in (MID, FWD):
        return cbirt
    return None  # GK ineligible / unknown position


class DcReconstructor:
    def __init__(self, sm: sessionmaker[Session] | None = None):
        self._sm = sm or get_sessionmaker()

    def build(self, seasons: Iterable[str] | None = None) -> list[DcBuildResult]:
        results: list[DcBuildResult] = []
        with self._sm() as s:
            if seasons is None:
                seasons = [
                    r[0] for r in s.execute(
                        select(player_match_stats.c.season).distinct()
                    ).all()
                ]
            for season in seasons:
                rows = self._build_season(s, season)
                results.append(DcBuildResult(season, rows))
            s.commit()
        for r in results:
            log.info("dc_match built", extra={"season": r.season, "rows": r.rows})
        return results

    def _build_season(self, s: Session, season: str) -> int:
        pms = player_match_stats.c
        # Only rows that actually carry DC components are reconstructable here.
        src = s.execute(
            select(
                pms.season, pms.element_id, pms.fixture_id, pms.player_key, pms.gw,
                pms.element_type, pms.clearances_blocks_interceptions, pms.tackles,
                pms.recoveries, pms.defensive_contribution,
            ).where(
                pms.season == season,
                or_(
                    pms.clearances_blocks_interceptions.isnot(None),
                    pms.tackles.isnot(None),
                    pms.recoveries.isnot(None),
                    pms.defensive_contribution.isnot(None),
                ),
            )
        ).all()

        rows: list[dict] = []
        for r in src:
            cbi = r.clearances_blocks_interceptions
            tackles = r.tackles
            recoveries = r.recoveries
            cbit = (cbi or 0) + (tackles or 0) if (cbi is not None or tackles is not None) else None
            cbirt = (cbit + (recoveries or 0)) if cbit is not None else None
            threshold = dc_threshold(CURRENT, r.element_type)
            value = _dc_value(r.element_type, cbit, cbirt)
            hit = (threshold is not None and value is not None and value >= threshold)
            rows.append({
                "season": season, "element_id": r.element_id, "fixture_id": r.fixture_id,
                "player_key": r.player_key, "gw": r.gw, "element_type": r.element_type,
                "cbi": cbi, "tackles": tackles, "recoveries": recoveries,
                "cbit": cbit, "cbirt": cbirt, "dc_value": value,
                "dc_official": r.defensive_contribution, "threshold": threshold,
                "dc_hit": hit, "recoveries_imputed": recoveries is None,
                "source": "vaastav",
            })

        for i in range(0, len(rows), 1000):
            chunk = rows[i:i + 1000]
            if not chunk:
                continue
            stmt = insert(dc_match).values(chunk)
            update = {c: stmt.excluded[c] for c in chunk[0]
                      if c not in ("season", "element_id", "fixture_id")}
            s.execute(stmt.on_conflict_do_update(
                index_elements=["season", "element_id", "fixture_id"], set_=update))
        return len(rows)

    def validate_against_official(self, season: str) -> DcValidation:
        """Compare reconstructed dc_value to FPL's official defensive_contribution."""
        dm = dc_match.c
        with self._sm() as s:
            rows = s.execute(
                select(dm.dc_value, dm.dc_official).where(
                    dm.season == season,
                    dm.dc_value.isnot(None),
                    dm.dc_official.isnot(None),
                )
            ).all()
        n = len(rows)
        if n == 0:
            return DcValidation(season, 0, 0, 0, 0.0, 0.0)
        exact = sum(1 for v, o in rows if v == o)
        total_abs = sum(abs(v - o) for v, o in rows)
        return DcValidation(
            season=season, n=n, exact=exact, mismatches=n - exact,
            mean_abs_diff=round(total_abs / n, 4), agreement=round(exact / n, 4),
        )
