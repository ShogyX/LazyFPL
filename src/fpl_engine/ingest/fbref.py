"""FBref advanced-stats acquisition (plan 1.1).

FBref serves stat tables as HTML, but every cell carries a stable
``data-stat`` attribute and each player row a ``data-append-csv`` player id —
so we can read tables reliably with the stdlib ``html.parser`` (no lxml/bs4).

Two quirks handled here:

* Many tables are wrapped in HTML comments (``<!-- ...<table>... -->``) to defer
  rendering; we strip comment markers before parsing so they become visible.
* Header rows repeat inside the body (``class="thead"``); rows without a
  ``player`` cell are dropped.

Parsing is pure + unit-tested; the live, rate-limited backfill is operational.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import raw_snapshots
from ..logging_setup import get_logger
from .fetch import EMPTY_PARAMS_HASH, FetchClient

log = get_logger(__name__)

_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)


def _uncomment(html: str) -> str:
    """Reveal comment-wrapped tables (FBref defers rendering this way)."""
    return _COMMENT.sub(lambda m: m.group(1), html)


def _text(payload: Any) -> str:
    if isinstance(payload, dict) and "_text" in payload:
        return payload["_text"]
    return payload if isinstance(payload, str) else ""


class _TableParser(HTMLParser):
    """Collect rows of a target ``<table id=...>`` as {data-stat: text} dicts.

    Each player row also exposes ``_id`` (FBref's ``data-append-csv`` player id).
    """

    def __init__(self, table_id: str | None):
        super().__init__(convert_charrefs=True)
        self._target = table_id
        self.rows: list[dict[str, str]] = []
        self._in_table = self._target is None
        self._depth = 0          # table nesting while inside target
        self._in_thead = False   # header section -> skip its rows
        self._row: dict[str, str] | None = None
        self._cell_stat: str | None = None
        self._cell_text: list[str] = []
        self._skip_row = False

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: v for k, v in attrs_list}
        if tag == "table":
            if self._target is not None and attrs.get("id") == self._target:
                self._in_table = True
                self._depth = 1
            elif self._in_table:
                self._depth += 1
            return
        if not self._in_table:
            return
        if tag == "thead":
            self._in_thead = True
        elif tag == "tr":
            self._row = {}
            self._skip_row = self._in_thead or "thead" in (attrs.get("class") or "")
        elif tag in ("td", "th") and self._row is not None:
            self._cell_stat = attrs.get("data-stat")
            self._cell_text = []
            if attrs.get("data-append-csv"):
                self._row["_id"] = attrs["data-append-csv"]

    def handle_data(self, data: str) -> None:
        if self._cell_stat is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table and self._target is not None:
            self._depth -= 1
            if self._depth == 0:
                self._in_table = False
            return
        if not self._in_table:
            return
        if tag == "thead":
            self._in_thead = False
            return
        if tag in ("td", "th") and self._row is not None and self._cell_stat:
            self._row[self._cell_stat] = "".join(self._cell_text).strip()
            self._cell_stat = None
            self._cell_text = []
        elif tag == "tr" and self._row is not None:
            if not self._skip_row and self._row.get("player"):
                self.rows.append(self._row)
            self._row = None


def parse_table(html: str, table_id: str | None = None) -> list[dict[str, str]]:
    parser = _TableParser(table_id)
    parser.feed(_uncomment(html))
    return parser.rows


@dataclass
class FetchStat:
    ref: str
    status: int
    snapshot_id: int | None
    deduped: bool


@dataclass
class AcquireResult:
    pages: list[FetchStat] = field(default_factory=list)

    def ok(self) -> list[FetchStat]:
        return [p for p in self.pages if p.status == 200]


class FBrefIngestor:
    PROVIDER = "fbref"

    def __init__(self, fetch: FetchClient, sm: sessionmaker[Session] | None = None):
        self._fetch = fetch
        self._sm = sm or get_sessionmaker()

    def acquire(self, path: str, *, season: str | None = None) -> FetchStat:
        """Fetch + snapshot a single FBref page (match report, match-log, ...)."""
        res = self._fetch.get(self.PROVIDER, path, season=season)
        if res.status_code != 200:
            log.warning("fbref fetch failed", extra={"path": path, "status": res.status_code})
        return FetchStat(path, res.status_code, res.snapshot_id, res.deduped)

    def latest_html(self, path: str) -> str | None:
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

    def read_table(self, path: str, table_id: str | None = None) -> list[dict[str, str]]:
        html = self.latest_html(path)
        return parse_table(html, table_id) if html is not None else []
