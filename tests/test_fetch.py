from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import func, select

from fpl_engine.ingest.budget import BudgetExceeded, BudgetTracker
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.db.models import raw_snapshots


def make_client(handler, sm, sleeps, *, clock=None, **kw):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return FetchClient(
        client=http, sm=sm, sleeper=sleeps.append,
        backoff_base=0.01, clock=clock, **kw,
    )


def test_backoff_on_429_then_success(sm):
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    sleeps: list[float] = []
    client = make_client(handler, sm, sleeps)
    res = client.get("fpl", "/bootstrap-static/")

    assert res.status_code == 200
    assert res.payload == {"ok": True}
    assert state["calls"] == 3  # two 429s then a 200
    assert len(sleeps) == 2  # backed off twice


def test_cache_hit_does_not_count_against_budget(sm):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"v": 1})

    sleeps: list[float] = []
    client = make_client(handler, sm, sleeps)

    first = client.get("fpl", "/cached/", cache_ttl=60)
    second = client.get("fpl", "/cached/", cache_ttl=60)

    assert first.from_cache is False
    assert second.from_cache is True
    # Only the real network call counted.
    assert BudgetTracker(sm).usage("fpl")["minute"] == 1


def test_snapshot_dedupes_identical_content_but_records_changes(sm):
    state = {"v": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"v": state["v"]})

    sleeps: list[float] = []
    client = make_client(handler, sm, sleeps)

    r1 = client.get("fpl", "/snap/")
    r2 = client.get("fpl", "/snap/")  # identical content -> deduped
    state["v"] = 2
    r3 = client.get("fpl", "/snap/")  # changed content -> new row

    assert r1.deduped is False
    assert r2.deduped is True
    assert r3.deduped is False

    with sm() as s:
        n = s.execute(
            select(func.count())
            .select_from(raw_snapshots)
            .where(raw_snapshots.c.provider == "fpl", raw_snapshots.c.endpoint == "/snap/")
        ).scalar_one()
    assert n == 2  # one per distinct content, re-run did not duplicate


def test_budget_exceeded_blocks_request(sm):
    now = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    tracker = BudgetTracker(sm)
    for _ in range(12):  # fill sharpapi's 12/min cap
        tracker.record("sharpapi", now=now)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("network must not be hit when budget is exhausted")

    sleeps: list[float] = []
    client = make_client(handler, sm, sleeps, clock=lambda: now)

    with pytest.raises(BudgetExceeded):
        client.get("sharpapi", "/odds/")
