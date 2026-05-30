"""Understat advanced-stats acquisition (plan 1.1).

Understat ships its data as ``JSON.parse('<hex-escaped-json>')`` embedded in
``<script>`` tags — no HTML parser needed, just regex extraction + unescape.

Two endpoints we use:

* ``/league/EPL/{start_year}`` — embeds ``datesData`` (every fixture with id,
  date, home/away team + goals) and ``playersData`` (season aggregates). We use
  ``datesData`` to enumerate the season's match ids.
* ``/match/{match_id}`` — embeds ``rostersData`` (per-player-per-match: minutes,
  goals, xG, assists, xA, shots, key passes, npg, npxG, xGChain, xGBuildup,
  position, team side). This is the per-match grain we normalise.

Everything is snapshotted raw + content-addressed so re-pulls dedupe. Parsing
is pure and unit-tested against sample embedded-JSON; the live backfill is a
budget-gated operational run.
"""

from __future__ import annotations

import codecs
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import raw_snapshots
from ..logging_setup import get_logger
from .fetch import EMPTY_PARAMS_HASH, FetchClient

log = get_logger(__name__)

# Understat seasons are identified by the calendar start year (2014 = 2014/15).
# Map FPL-style "2024-25" season labels onto Understat's start-year path param.
SEASONS: tuple[str, ...] = (
    "2014-15", "2015-16", "2016-17", "2017-18", "2018-19", "2019-20",
    "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26",
)


def understat_year(season: str) -> int:
    """'2024-25' -> 2024 (Understat's league path uses the start year)."""
    return int(season.split("-")[0])


def _text(payload: Any) -> str:
    if isinstance(payload, dict) and "_text" in payload:
        return payload["_text"]
    return payload if isinstance(payload, str) else ""


def extract_json_var(html: str, var: str) -> Any:
    """Pull ``var <name> = JSON.parse('...')`` out of an Understat page.

    The argument is a single-quoted string with hex escapes (``\\x22`` etc.).
    Returns the decoded object, or ``None`` if the variable isn't present.
    """
    m = re.search(
        rf"{re.escape(var)}\s*=\s*JSON\.parse\('(?P<body>.*?)'\)",
        html,
        re.DOTALL,
    )
    if not m:
        return None
    body = m.group("body")
    # Decode hex/unicode escapes (\xNN, \uNNNN) the page uses to embed the JSON.
    decoded = codecs.decode(body, "unicode_escape").encode("latin-1").decode("utf-8")
    return json.loads(decoded)


@dataclass
class FetchStat:
    ref: str
    status: int
    snapshot_id: int | None
    deduped: bool


@dataclass
class AcquireResult:
    season: str
    league: FetchStat | None = None
    matches: list[FetchStat] = field(default_factory=list)

    def ok_matches(self) -> list[FetchStat]:
        return [m for m in self.matches if m.status == 200]


class UnderstatIngestor:
    PROVIDER = "understat"
    SEASONS = SEASONS

    def __init__(self, fetch: FetchClient, sm: sessionmaker[Session] | None = None):
        self._fetch = fetch
        self._sm = sm or get_sessionmaker()

    # -- raw acquisition --
    def _league_path(self, season: str) -> str:
        return f"/league/EPL/{understat_year(season)}"

    @staticmethod
    def _match_path(match_id: str) -> str:
        return f"/match/{match_id}"

    def acquire_season(
        self, season: str, *, max_matches: int | None = None
    ) -> AcquireResult:
        """Fetch the league page then every match page for ``season``.

        ``max_matches`` bounds a partial/test run; the budget tracker still
        gates each call, so a full season backfill paces itself under the cap.
        """
        result = AcquireResult(season=season)
        res = self._fetch.get(self.PROVIDER, self._league_path(season), season=season)
        result.league = FetchStat(self._league_path(season), res.status_code,
                                  res.snapshot_id, res.deduped)
        if res.status_code != 200:
            log.warning("understat league fetch failed",
                        extra={"season": season, "status": res.status_code})
            return result

        dates = extract_json_var(_text(res.payload), "datesData") or []
        match_ids = [str(d["id"]) for d in dates if d.get("id") is not None
                     and d.get("isResult", True)]
        if max_matches is not None:
            match_ids = match_ids[:max_matches]
        for mid in match_ids:
            mres = self._fetch.get(self.PROVIDER, self._match_path(mid), season=season)
            result.matches.append(FetchStat(self._match_path(mid), mres.status_code,
                                            mres.snapshot_id, mres.deduped))
        log.info("understat season acquired", extra={"season": season,
                                                     "matches": len(result.matches)})
        return result

    # -- raw read-back --
    def _latest_payload(self, path: str) -> str | None:
        with self._sm() as s:
            row = s.execute(
                select(raw_snapshots.c.payload, raw_snapshots.c.status_code)
                .where(raw_snapshots.c.provider == self.PROVIDER,
                       raw_snapshots.c.endpoint == path,
                       raw_snapshots.c.params_hash == EMPTY_PARAMS_HASH)
                .order_by(desc(raw_snapshots.c.fetched_at))
                .limit(1)
            ).first()
        if row is None or row.status_code != 200:
            return None
        return _text(row.payload)

    def league_players(self, season: str) -> list[dict]:
        """Season-aggregate player rows (id, player_name, team_title, position...)."""
        html = self._latest_payload(self._league_path(season))
        if html is None:
            return []
        return extract_json_var(html, "playersData") or []

    def league_dates(self, season: str) -> list[dict]:
        html = self._latest_payload(self._league_path(season))
        if html is None:
            return []
        return extract_json_var(html, "datesData") or []

    def match_rosters(self, season: str, match_id: str) -> list[dict]:
        """Flatten a match page's rostersData into per-player rows.

        ``rostersData`` is ``{"h": {pid: {...}}, "a": {pid: {...}}}``; we tag
        each row with its ``side`` (h/a) so the normaliser can set was_home.
        """
        html = self._latest_payload(self._match_path(match_id))
        if html is None:
            return []
        rosters = extract_json_var(html, "rostersData") or {}
        out: list[dict] = []
        for side in ("h", "a"):
            for row in (rosters.get(side) or {}).values():
                if isinstance(row, dict):
                    out.append({**row, "side": side})
        return out
