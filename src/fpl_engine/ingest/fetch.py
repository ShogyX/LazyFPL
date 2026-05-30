"""Shared rate-limited fetch + snapshot layer.

One fetch path for every provider: real UA, budget-gated, exponential
back-off on 429/5xx (honours ``Retry-After``), in-memory TTL cache, and
content-addressed raw snapshot write-through with idempotent dedupe.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import raw_snapshots
from ..logging_setup import get_logger
from .budget import BudgetTracker
from .providers import USER_AGENT, get_provider

log = get_logger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


EMPTY_PARAMS_HASH = _sha256(_canonical({}))


@dataclass
class FetchResult:
    provider: str
    endpoint: str
    status_code: int
    payload: Any
    from_cache: bool
    snapshot_id: int | None
    deduped: bool


@dataclass
class _CacheEntry:
    result: FetchResult
    expires_at: float


class FetchClient:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        sm: sessionmaker[Session] | None = None,
        budget: BudgetTracker | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        max_retries: int = 4,
        backoff_base: float = 0.5,
        clock: Callable[[], datetime] | None = None,
    ):
        self._client = client or httpx.Client(timeout=20.0)
        self._sm = sm or get_sessionmaker()
        self._budget = budget or BudgetTracker(self._sm)
        self._sleep = sleeper
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._cache: dict[str, _CacheEntry] = {}

    # -- snapshot write-through with content-addressed dedupe --
    def snapshot(
        self,
        provider: str,
        endpoint: str,
        params: dict[str, Any] | None,
        *,
        payload: Any,
        status_code: int,
        season: str | None = None,
    ) -> tuple[int, bool]:
        params = params or {}
        params_hash = _sha256(_canonical(params))
        content_hash = _sha256(_canonical(payload))
        with self._sm() as s:
            latest = s.execute(
                select(raw_snapshots.c.id, raw_snapshots.c.content_hash)
                .where(
                    raw_snapshots.c.provider == provider,
                    raw_snapshots.c.endpoint == endpoint,
                    raw_snapshots.c.params_hash == params_hash,
                )
                .order_by(desc(raw_snapshots.c.fetched_at))
                .limit(1)
            ).first()
            if latest is not None and latest.content_hash == content_hash:
                return int(latest.id), True
            new_id = s.execute(
                raw_snapshots.insert()
                .values(
                    provider=provider,
                    endpoint=endpoint,
                    params_hash=params_hash,
                    params=params,
                    content_hash=content_hash,
                    status_code=status_code,
                    payload=payload,
                    season=season,
                )
                .returning(raw_snapshots.c.id)
            ).scalar_one()
            s.commit()
            return int(new_id), False

    def _cache_key(self, provider: str, path: str, params: dict[str, Any] | None) -> str:
        return f"{provider}|{path}|{_canonical(params or {})}"

    def _retry_after(self, response: httpx.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        return self._backoff_base * (2 ** attempt)

    def get(
        self,
        provider: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        cache_ttl: float = 0.0,
        season: str | None = None,
        store_snapshot: bool = True,
    ) -> FetchResult:
        cfg = get_provider(provider)
        key = self._cache_key(provider, path, params)
        now_mono = time.monotonic()

        if cache_ttl > 0:
            entry = self._cache.get(key)
            if entry and entry.expires_at > now_mono:
                cached = entry.result
                return FetchResult(
                    provider, path, cached.status_code, cached.payload,
                    from_cache=True, snapshot_id=cached.snapshot_id, deduped=cached.deduped,
                )

        # Budget gate: atomically reserve one call (blocks before any free cap).
        self._budget.consume(provider, now=self._clock())

        url = f"{cfg.base_url}{path}"
        headers = {"User-Agent": USER_AGENT, **cfg.headers, **(extra_headers or {})}

        response: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            response = self._client.get(url, params=params, headers=headers)
            if response.status_code not in RETRYABLE_STATUS or attempt == self._max_retries:
                break
            delay = self._retry_after(response, attempt)
            log.warning(
                "retrying after backoff",
                extra={"provider": provider, "status": response.status_code,
                       "attempt": attempt, "delay": delay},
            )
            self._sleep(delay)

        assert response is not None

        try:
            payload: Any = response.json()
        except (json.JSONDecodeError, ValueError):
            payload = {"_text": response.text}

        snapshot_id: int | None = None
        deduped = False
        if store_snapshot and response.status_code < 400:
            snapshot_id, deduped = self.snapshot(
                provider, path, params,
                payload=payload, status_code=response.status_code, season=season,
            )

        result = FetchResult(
            provider, path, response.status_code, payload,
            from_cache=False, snapshot_id=snapshot_id, deduped=deduped,
        )
        if cache_ttl > 0:
            self._cache[key] = _CacheEntry(result=result, expires_at=now_mono + cache_ttl)
        return result

    def close(self) -> None:
        self._client.close()
