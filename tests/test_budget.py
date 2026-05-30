from datetime import datetime, timezone

import pytest

from fpl_engine.ingest.budget import BudgetExceeded, BudgetTracker


def test_budget_blocks_before_exceeding_cap(sm):
    tracker = BudgetTracker(sm)
    now = datetime(2026, 1, 1, 12, 30, 15, tzinfo=timezone.utc)
    provider = "sharpapi"  # 12 req/min

    # 12 calls fit within the per-minute cap.
    for _ in range(12):
        tracker.check(provider, now=now)
        tracker.record(provider, now=now)

    assert tracker.usage(provider, now)["minute"] == 12
    assert tracker.remaining(provider, now)["minute"] == 0

    # The 13th must be blocked before the network call.
    with pytest.raises(BudgetExceeded) as exc:
        tracker.check(provider, now=now)
    assert exc.value.window_kind == "minute"
    assert exc.value.limit == 12


def test_consume_is_atomic_check_and_increment(sm):
    tracker = BudgetTracker(sm)
    now = datetime(2026, 2, 2, 8, 0, 0, tzinfo=timezone.utc)

    for _ in range(12):  # sharpapi 12/min
        tracker.consume("sharpapi", now=now)
    assert tracker.usage("sharpapi", now)["minute"] == 12

    # At cap: consume blocks and must NOT increment beyond the cap.
    with pytest.raises(BudgetExceeded):
        tracker.consume("sharpapi", now=now)
    assert tracker.usage("sharpapi", now)["minute"] == 12


def test_budget_windows_are_independent(sm):
    tracker = BudgetTracker(sm)
    t1 = datetime(2026, 1, 1, 12, 30, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 12, 31, 0, tzinfo=timezone.utc)  # next minute
    tracker.record("sharpapi", now=t1)
    assert tracker.usage("sharpapi", t1)["minute"] == 1
    # A new minute starts a fresh counter.
    assert tracker.usage("sharpapi", t2)["minute"] == 0
