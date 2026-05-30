"""Tracked-team ingestion + transfer detection (mocked FPL API)."""

import httpx
from sqlalchemy import func, select

from fpl_engine.db.models import tracked_entries, tracked_picks, tracked_transfers
from fpl_engine.ingest.entry import EntryIngestor
from fpl_engine.ingest.fetch import FetchClient

ENTRY = {
    "player_first_name": "Jane", "player_last_name": "Doe", "current_event": 29,
    "last_deadline_bank": 5, "last_deadline_value": 1005,
    "summary_overall_points": 2000, "summary_overall_rank": 12345,
}
TRANSFERS = [
    {"element_in": 10, "element_out": 20, "element_in_cost": 80, "element_out_cost": 75,
     "entry": 1, "event": 29, "time": "2026-02-01T10:00:00Z"},
    {"element_in": 11, "element_out": 21, "element_in_cost": 60, "element_out_cost": 55,
     "entry": 1, "event": 28, "time": "2026-01-25T10:00:00Z"},
]
PICKS = {"picks": [
    {"element": 100 + k, "position": k + 1, "multiplier": 2 if k == 0 else 1,
     "is_captain": k == 0, "is_vice_captain": k == 1} for k in range(15)]}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/transfers/"):
        return httpx.Response(200, json=TRANSFERS)
    if "/picks/" in path:
        return httpx.Response(200, json=PICKS)
    if path.endswith("/entry/1/"):
        return httpx.Response(200, json=ENTRY)
    return httpx.Response(404, json={})


def _ingestor(sm) -> EntryIngestor:
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    return EntryIngestor(FetchClient(client=http, sm=sm), sm=sm)


def test_entry_ingest_and_transfer_detection(sm):
    ing = _ingestor(sm)
    res = ing.ingest_entry(1)

    assert res.name == "Jane Doe"
    assert res.current_event == 29
    assert res.team_value == 1005
    assert res.new_transfers == 2          # both transfers are new
    assert len(res.roster) == 15

    with sm() as s:
        e = s.execute(select(tracked_entries).where(tracked_entries.c.entry_id == 1)).one()
        assert e.overall_rank == 12345
        assert s.execute(select(func.count()).select_from(tracked_transfers)).scalar_one() == 2
        assert s.execute(select(func.count()).select_from(tracked_picks)).scalar_one() == 15


def test_transfer_detection_idempotent(sm):
    ing = _ingestor(sm)
    ing.ingest_entry(1)
    second = ing.ingest_entry(1)
    assert second.new_transfers == 0      # nothing new on re-poll
    with sm() as s:
        # no duplicate transfer rows
        assert s.execute(select(func.count()).select_from(tracked_transfers)).scalar_one() == 2


def test_latest_roster(sm):
    ing = _ingestor(sm)
    ing.ingest_entry(1)
    roster = ing.latest_roster(1)
    assert sorted(roster) == [100 + k for k in range(15)]


# Resolver test: transfers overlap roster ids so they appear in purchase.
RESOLVE_TRANSFERS = [
    # Player 100: bought 60 in GW28, then sold + rebought 70 in GW29.
    {"element_in": 100, "element_out": 999, "element_in_cost": 60, "element_out_cost": 50,
     "entry": 1, "event": 28, "time": "2026-01-25T10:00:00Z"},
    {"element_in": 100, "element_out": 50, "element_in_cost": 70, "element_out_cost": 65,
     "entry": 1, "event": 29, "time": "2026-02-01T10:00:00Z"},
    # Player 101: bought once at 80, currently held.
    {"element_in": 101, "element_out": 60, "element_in_cost": 80, "element_out_cost": 75,
     "entry": 1, "event": 29, "time": "2026-02-02T10:00:00Z"},
    # Player 200: transferred IN earlier then OUT later -- not in current roster.
    {"element_in": 200, "element_out": 99, "element_in_cost": 90, "element_out_cost": 85,
     "entry": 1, "event": 27, "time": "2026-01-18T10:00:00Z"},
]


def _handler_resolve(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/transfers/"):
        return httpx.Response(200, json=RESOLVE_TRANSFERS)
    if "/picks/" in path:
        return httpx.Response(200, json=PICKS)
    if path.endswith("/entry/1/"):
        return httpx.Response(200, json=ENTRY)
    return httpx.Response(404, json={})


def test_resolve_budget(sm):
    http = httpx.Client(transport=httpx.MockTransport(_handler_resolve))
    ing = EntryIngestor(FetchClient(client=http, sm=sm), sm=sm)
    ing.ingest_entry(1)

    bank, purchase = ing.resolve_budget(1)
    assert bank == 5                        # from tracked_entries.bank
    # Most recent in-cost per held player wins; player 100 has 70 (re-bought).
    assert purchase[100] == 70
    assert purchase[101] == 80
    # Player 200 was transferred out and is NOT currently held -- excluded.
    assert 200 not in purchase
    # Held players never transferred (102..114) have no purchase entry.
    assert all(pid not in purchase for pid in range(102, 115))
