"""vaastav/Fantasy-Premier-League historical acquisition (plan 1.1).

Pulls the canonical historical FPL CSVs (players_raw, teams, fixtures,
gws/merged_gw) for every available season into the RAW layer, verbatim and
idempotent (content-addressed dedupe handles re-pulls). Emits a coverage
report of season x file presence and row counts.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import raw_snapshots
from ..logging_setup import get_logger
from .fetch import EMPTY_PARAMS_HASH, FetchClient

log = get_logger(__name__)

# Seasons present in the repository (2016/17 onward).
SEASONS: tuple[str, ...] = (
    "2016-17", "2017-18", "2018-19", "2019-20", "2020-21",
    "2021-22", "2022-23", "2023-24", "2024-25", "2025-26",
)

# Logical file name -> path template under /data/{season}/.
FILES: dict[str, str] = {
    "players_raw": "/data/{season}/players_raw.csv",
    "teams": "/data/{season}/teams.csv",
    "fixtures": "/data/{season}/fixtures.csv",
    "merged_gw": "/data/{season}/gws/merged_gw.csv",
}


def parse_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _text(payload: Any) -> str:
    if isinstance(payload, dict) and "_text" in payload:
        return payload["_text"]
    if isinstance(payload, str):
        return payload
    return ""


@dataclass
class FileResult:
    season: str
    file: str
    status: int
    rows: int
    snapshot_id: int | None
    deduped: bool


@dataclass
class AcquireResult:
    files: list[FileResult] = field(default_factory=list)

    def ok(self) -> list[FileResult]:
        return [f for f in self.files if f.status == 200]


class VaastavIngestor:
    PROVIDER = "vaastav"
    SEASONS = SEASONS
    FILES = FILES

    def __init__(self, fetch: FetchClient, sm: sessionmaker[Session] | None = None):
        self._fetch = fetch
        self._sm = sm or get_sessionmaker()

    def acquire(
        self,
        seasons: Iterable[str] | None = None,
        files: Iterable[str] | None = None,
    ) -> AcquireResult:
        seasons = tuple(seasons) if seasons is not None else SEASONS
        files = tuple(files) if files is not None else tuple(FILES)
        result = AcquireResult()
        for season in seasons:
            for fname in files:
                path = FILES[fname].format(season=season)
                res = self._fetch.get(self.PROVIDER, path, season=season)
                rows = 0
                if res.status_code == 200:
                    rows = len(parse_csv(_text(res.payload)))
                else:
                    log.info("vaastav file absent", extra={"season": season, "file": fname,
                                                            "status": res.status_code})
                result.files.append(
                    FileResult(season, fname, res.status_code, rows,
                               res.snapshot_id, res.deduped)
                )
        return result

    def latest_csv(self, season: str, file: str) -> list[dict[str, str]] | None:
        """Return the most recent stored snapshot for a season/file as rows."""
        path = FILES[file].format(season=season)
        with self._sm() as s:
            row = s.execute(
                select(raw_snapshots.c.payload, raw_snapshots.c.status_code)
                .where(
                    raw_snapshots.c.provider == self.PROVIDER,
                    raw_snapshots.c.endpoint == path,
                    raw_snapshots.c.params_hash == EMPTY_PARAMS_HASH,
                )
                .order_by(desc(raw_snapshots.c.fetched_at))
                .limit(1)
            ).first()
        if row is None or row.status_code != 200:
            return None
        return parse_csv(_text(row.payload))

    def coverage(self) -> dict[str, dict[str, int | None]]:
        """Coverage report: {season: {file: row_count|None}} from stored snapshots.

        A ``None`` value flags a file that was expected for the season but is
        absent from the source (e.g. teams/fixtures before 2018-19). Seasons
        with no files at all are omitted.
        """
        report: dict[str, dict[str, int | None]] = {}
        for season in SEASONS:
            files: dict[str, int | None] = {}
            for fname in FILES:
                rows = self.latest_csv(season, fname)
                files[fname] = len(rows) if rows is not None else None
            if any(v is not None for v in files.values()):
                report[season] = files
        return report
