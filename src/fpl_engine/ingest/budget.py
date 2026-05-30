"""Per-provider budget counters.

Windowed consumption counters in ``core.budget_usage``. ``check`` blocks
*before* a free cap is exceeded; ``record`` increments every configured
window after a real network call (cache hits do not count).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import budget_usage
from .providers import RateLimits, get_provider


class BudgetExceeded(RuntimeError):
    def __init__(self, provider: str, window_kind: str, limit: int):
        self.provider = provider
        self.window_kind = window_kind
        self.limit = limit
        super().__init__(
            f"budget cap reached for provider={provider} window={window_kind} limit={limit}"
        )


def window_start(kind: str, now: datetime) -> datetime:
    now = now.astimezone(timezone.utc)
    if kind == "minute":
        return now.replace(second=0, microsecond=0)
    if kind == "hour":
        return now.replace(minute=0, second=0, microsecond=0)
    if kind == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"unknown window kind: {kind!r}")


class BudgetTracker:
    def __init__(self, sm: sessionmaker[Session] | None = None):
        self._sm = sm or get_sessionmaker()

    def _limits(self, provider: str) -> RateLimits:
        return get_provider(provider).limits

    def _count(self, s: Session, provider: str, kind: str, ws: datetime) -> int:
        row = s.execute(
            select(budget_usage.c.count).where(
                budget_usage.c.provider == provider,
                budget_usage.c.window_kind == kind,
                budget_usage.c.window_start == ws,
            )
        ).scalar_one_or_none()
        return int(row or 0)

    def usage(self, provider: str, now: datetime | None = None) -> dict[str, int]:
        """Current consumption per configured window."""
        now = now or datetime.now(timezone.utc)
        limits = self._limits(provider).configured()
        with self._sm() as s:
            return {
                kind: self._count(s, provider, kind, window_start(kind, now))
                for kind in limits
            }

    def remaining(self, provider: str, now: datetime | None = None) -> dict[str, int]:
        now = now or datetime.now(timezone.utc)
        limits = self._limits(provider).configured()
        used = self.usage(provider, now)
        return {kind: cap - used.get(kind, 0) for kind, cap in limits.items()}

    def check(self, provider: str, now: datetime | None = None) -> None:
        """Raise :class:`BudgetExceeded` if one more call would breach a cap."""
        now = now or datetime.now(timezone.utc)
        limits = self._limits(provider).configured()
        with self._sm() as s:
            for kind, cap in limits.items():
                if self._count(s, provider, kind, window_start(kind, now)) >= cap:
                    raise BudgetExceeded(provider, kind, cap)

    def _increment(self, s: Session, provider: str, now: datetime) -> None:
        for kind in self._limits(provider).configured():
            ws = window_start(kind, now)
            stmt = (
                insert(budget_usage)
                .values(provider=provider, window_kind=kind, window_start=ws, count=1)
                .on_conflict_do_update(
                    index_elements=["provider", "window_kind", "window_start"],
                    set_={"count": budget_usage.c.count + 1},
                )
            )
            s.execute(stmt)

    def record(self, provider: str, now: datetime | None = None) -> None:
        """Increment every configured window counter (atomic upsert)."""
        now = now or datetime.now(timezone.utc)
        with self._sm() as s:
            self._increment(s, provider, now)
            s.commit()

    def consume(self, provider: str, now: datetime | None = None) -> None:
        """Atomically reserve one call: raise if at cap, else increment.

        Serialised per-provider with a transaction-scoped advisory lock so two
        concurrent fetchers cannot both pass the check at ``cap-1`` and overshoot
        a hard free cap. On :class:`BudgetExceeded` the transaction rolls back,
        so no counter is incremented and the lock is released.
        """
        now = now or datetime.now(timezone.utc)
        limits = self._limits(provider).configured()
        if not limits:
            return
        with self._sm() as s:
            s.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:p))"), {"p": provider}
            )
            for kind, cap in limits.items():
                if self._count(s, provider, kind, window_start(kind, now)) >= cap:
                    raise BudgetExceeded(provider, kind, cap)
            self._increment(s, provider, now)
            s.commit()
