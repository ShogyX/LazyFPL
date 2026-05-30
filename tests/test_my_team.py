"""Authed /my-team ingestion + authed-preferred budget resolution (mocked)."""

import httpx
import pytest
from sqlalchemy import select

from fpl_engine.config import get_settings
from fpl_engine.db.models import authed_picks, tracked_entries
from fpl_engine.ingest.entry import EntryIngestor
from fpl_engine.ingest.fetch import FetchClient

MY_TEAM = {
    "picks": [
        {"element": 100, "selling_price": 75, "purchase_price": 70,
         "multiplier": 2, "is_captain": True, "is_vice_captain": False},
        {"element": 101, "selling_price": 55, "purchase_price": 50,
         "multiplier": 1, "is_captain": False, "is_vice_captain": True},
    ],
    "transfers": {"bank": 8, "value": 1015, "limit": 1, "made": 0},
    "chips": [],
}


def _client(my_team_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if "/my-team/" in request.url.path:
            if my_team_status != 200:
                return httpx.Response(my_team_status, json={})
            return httpx.Response(200, json=MY_TEAM)
        return httpx.Response(404, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def _with_cookie():
    """Set the operator cookie for the duration of the test."""
    get_settings.cache_clear()
    import os
    os.environ["FPL_FPL_SESSION_COOKIE"] = "pl_profile=secret-cookie"
    get_settings.cache_clear()
    yield
    del os.environ["FPL_FPL_SESSION_COOKIE"]
    get_settings.cache_clear()


def test_my_team_ingests_prices_and_bank(sm, _with_cookie):
    ing = EntryIngestor(FetchClient(client=_client(), sm=sm), sm=sm)
    res = ing.ingest_my_team(7)
    assert res.authenticated is True
    assert res.bank == 8 and res.picks == 2

    with sm() as s:
        picks = {r.element_id: r for r in s.execute(select(authed_picks)).all()}
        entry = s.execute(select(tracked_entries).where(
            tracked_entries.c.entry_id == 7)).one()
    assert picks[100].selling_price == 75 and picks[100].purchase_price == 70
    assert entry.bank == 8 and entry.team_value == 1015  # authed overrides public


def test_my_team_without_cookie_flags_reauth(sm):
    get_settings.cache_clear()  # ensure no cookie leaks from another test
    ing = EntryIngestor(FetchClient(client=_client(), sm=sm), sm=sm)
    res = ing.ingest_my_team(7)
    assert res.authenticated is False and res.needs_reauth is True
    assert res.reason == "no_cookie"


def test_my_team_auth_failure_flags_reauth(sm, _with_cookie):
    ing = EntryIngestor(FetchClient(client=_client(my_team_status=403), sm=sm), sm=sm)
    res = ing.ingest_my_team(7)
    assert res.authenticated is False and res.needs_reauth is True
    assert res.reason == "auth_failed"


def test_resolve_budget_prefers_authed_purchase(sm, _with_cookie):
    ing = EntryIngestor(FetchClient(client=_client(), sm=sm), sm=sm)
    ing.ingest_my_team(7)
    bank, purchase = ing.resolve_budget(7)
    # Authed purchase prices for every owned player (incl. never-transferred).
    assert bank == 8
    assert purchase == {100: 70, 101: 50}
