"""Odds provider integrations: parsers, key-gating, end-to-end (mocked)."""

import httpx
from sqlalchemy import func, select

from fpl_engine.config import Settings
from fpl_engine.db.models import odds_snapshots
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.ingest.odds_providers import (
    OddsIngestor,
    auth_for,
    parse_api_football_1x2,
    parse_theoddsapi_h2h,
)
from fpl_engine.odds.store import OddsStore

API_FOOTBALL = {"response": [{
    "fixture": {"id": 123},
    "bookmakers": [
        {"name": "Pinnacle", "bets": [{"name": "Match Winner", "values": [
            {"value": "Home", "odd": "1.90"}, {"value": "Draw", "odd": "3.60"},
            {"value": "Away", "odd": "4.20"}]}]},
        {"name": "Bet365", "bets": [{"name": "Match Winner", "values": [
            {"value": "Home", "odd": "2.00"}, {"value": "Draw", "odd": "3.50"},
            {"value": "Away", "odd": "3.80"}]}]},
    ]}]}

ODDSAPI = [{
    "id": "evtA", "home_team": "Arsenal", "away_team": "Chelsea",
    "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
        {"name": "Arsenal", "price": 1.8}, {"name": "Chelsea", "price": 4.5},
        {"name": "Draw", "price": 3.7}]}]}]}]


def test_auth_schemes():
    s = Settings(api_football_key="afkey", oddsapi_io_key="ioKey", _env_file=None)
    h, p, ok = auth_for("api_football", s)
    assert ok and h["x-apisports-key"] == "afkey" and p == {}
    h, p, ok = auth_for("oddsapi_io", s)
    assert ok and p["apiKey"] == "ioKey" and h == {}
    # no key -> disabled
    _, _, ok2 = auth_for("sharpapi", s)
    assert ok2 is False


def test_parse_api_football():
    quotes = parse_api_football_1x2(API_FOOTBALL)
    assert len(quotes) == 2
    pinnacle = next(q for q in quotes if q.book == "pinnacle")
    assert pinnacle.sharp is True
    assert pinnacle.odds == {"Home": 1.90, "Draw": 3.60, "Away": 4.20}
    assert next(q for q in quotes if q.book == "bet365").sharp is False


def test_parse_theoddsapi():
    quotes = parse_theoddsapi_h2h(ODDSAPI)
    assert len(quotes) == 1
    q = quotes[0]
    assert q.event_ref == "evtA" and q.book == "pinnacle" and q.sharp is True
    assert q.odds == {"Home": 1.8, "Away": 4.5, "Draw": 3.7}


def test_theoddsapi_unmapped_name_skipped_not_drawn():
    # a bookmaker lists a team name that doesn't match home/away exactly -> it
    # must be SKIPPED, not silently bucketed as Draw.
    payload = [{
        "id": "e", "home_team": "Arsenal", "away_team": "Chelsea",
        "bookmakers": [{"key": "b", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Arsenal", "price": 1.8},
            {"name": "Chelsea FC", "price": 4.5},   # mismatched -> skipped
            {"name": "Draw", "price": 3.7}]}]}]}]
    quotes = parse_theoddsapi_h2h(payload)
    assert len(quotes) == 1
    assert quotes[0].odds == {"Home": 1.8, "Draw": 3.7}   # 'Chelsea FC' dropped
    assert "Away" not in quotes[0].odds


def test_parsers_tolerate_malformed_payloads():
    assert parse_api_football_1x2({}) == []
    assert parse_api_football_1x2({"response": [{"bookmakers": [
        {"name": "x", "bets": [{"name": "Match Winner", "values": [
            {"value": "Home", "odd": "notanumber"}]}]}]}]}) == []  # bad odd + no fixture
    assert parse_theoddsapi_h2h(None) == []
    assert parse_theoddsapi_h2h([{"id": "e", "bookmakers": []}]) == []


def test_ingestor_returns_zero_on_non_200(sm):
    def handler(request):
        return httpx.Response(500, json={})
    fetch = FetchClient(client=httpx.Client(transport=httpx.MockTransport(handler)), sm=sm)
    ing = OddsIngestor("api_football", parse_api_football_1x2, fetch=fetch,
                       store=OddsStore(sm=sm), settings=Settings(api_football_key="k", _env_file=None))
    assert ing.ingest("/odds", params={"fixture": "1"}) == 0


def test_query_param_key_is_redacted_in_logs(sm):
    # oddsapi_io puts the key in the URL query; the redaction filter must scrub
    # it from any emitted log line.
    import logging
    from fpl_engine.logging_setup import RedactionFilter
    flt = RedactionFilter(["SECRETKEY123"])
    rec = logging.LogRecord("httpx", logging.INFO, __file__, 1,
                            "HTTP Request: GET https://api.odds-api.io/odds?apiKey=SECRETKEY123",
                            None, None)
    flt.filter(rec)
    assert "SECRETKEY123" not in rec.getMessage()
    assert "REDACTED" in rec.getMessage()


def test_ingestor_disabled_without_key(sm):
    ing = OddsIngestor("api_football", parse_api_football_1x2,
                       fetch=FetchClient(sm=sm), store=OddsStore(sm=sm),
                       settings=Settings(_env_file=None))
    assert ing.enabled is False
    assert ing.ingest("/odds", params={"fixture": "123"}) == 0  # no fetch, no write


def test_ingestor_end_to_end_with_key(sm):
    def handler(request):
        return httpx.Response(200, json=API_FOOTBALL)

    fetch = FetchClient(client=httpx.Client(transport=httpx.MockTransport(handler)), sm=sm)
    store = OddsStore(sm=sm)
    ing = OddsIngestor("api_football", parse_api_football_1x2, fetch=fetch, store=store,
                       settings=Settings(api_football_key="k", _env_file=None))
    assert ing.enabled is True

    written = ing.ingest("/odds", params={"fixture": "123"})
    assert written == 2  # two bookmakers

    with sm() as s:
        n = s.execute(select(func.count()).select_from(odds_snapshots).where(
            odds_snapshots.c.event_ref == "123")).scalar_one()
    assert n == 6  # 2 books x 3 selections

    res = store.build_consensus("123", "1x2")
    assert res.n_sources == 2
    assert res.sharp_present is True   # Pinnacle present
    assert abs(sum(res.probs.values()) - 1.0) < 1e-6
