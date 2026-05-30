"""API-Football lineups / injuries / referees ingestion + resolution (mocked)."""

import httpx
from sqlalchemy import select

from fpl_engine.db.models import injuries, lineups, match_officials, player_identity, teams
from fpl_engine.ingest.api_football import ApiFootballIngestor
from fpl_engine.ingest.fetch import FetchClient

LINEUPS = {"response": [
    {"team": {"id": 50, "name": "Manchester City"}, "formation": "4-3-3",
     "startXI": [{"player": {"id": 1, "name": "Erling Haaland", "grid": "4:1"}}],
     "substitutes": [{"player": {"id": 2, "name": "Julian Alvarez", "grid": None}}]},
    {"team": {"id": 49, "name": "Chelsea"}, "formation": "3-4-3",
     "startXI": [{"player": {"id": 3, "name": "Cole Palmer", "grid": "3:2"}}],
     "substitutes": []},
]}

INJURIES = {"response": [
    {"player": {"id": 1, "name": "Erling Haaland", "type": "Missing Fixture",
                "reason": "Knock"},
     "team": {"id": 50, "name": "Manchester City"},
     "fixture": {"id": 999}},
]}

FIXTURES = {"response": [
    {"fixture": {"id": 999, "referee": "Michael Oliver"}},
    {"fixture": {"id": 1000, "referee": None}},   # no referee -> skipped
]}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/fixtures/lineups":
        return httpx.Response(200, json=LINEUPS)
    if path == "/injuries":
        return httpx.Response(200, json=INJURIES)
    if path == "/fixtures":
        return httpx.Response(200, json=FIXTURES)
    return httpx.Response(404, json={})


def _seed(sm):
    with sm() as s:
        s.execute(teams.insert(), [
            {"id": 11, "name": "Man City", "short_name": "MCI"},
            {"id": 12, "name": "Chelsea", "short_name": "CHE"},
        ])
        s.execute(player_identity.insert(), [
            {"player_key": 90001, "web_name": "Haaland", "first_name": "Erling",
             "second_name": "Haaland", "last_season": "2024-25"},
            {"player_key": 90003, "web_name": "Palmer", "first_name": "Cole",
             "second_name": "Palmer", "last_season": "2024-25"},
        ])
        s.commit()


def _ingestor(sm) -> ApiFootballIngestor:
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    return ApiFootballIngestor(FetchClient(client=http, sm=sm), sm=sm)


def test_ingest_lineups_resolves_team_and_player(sm):
    _seed(sm)
    n = _ingestor(sm).ingest_lineups(999)
    assert n == 3  # 2 City (1 start + 1 bench) + 1 Chelsea start

    with sm() as s:
        rows = {r.player_ref: r for r in s.execute(select(lineups)).all()}
    assert rows["1"].role == "start" and rows["1"].team_id == 11
    assert rows["1"].player_key == 90001 and rows["1"].confirmed is True
    assert rows["2"].role == "bench"
    assert rows["3"].team_id == 12 and rows["3"].player_key == 90003


def test_ingest_injuries(sm):
    _seed(sm)
    n = _ingestor(sm).ingest_injuries(2024)
    assert n == 1
    with sm() as s:
        row = s.execute(select(injuries)).one()
    assert row.player_key == 90001 and row.team_id == 11
    assert row.reason == "Knock" and row.fixture_ref == "999"


def test_ingest_referees_skips_missing(sm):
    n = _ingestor(sm).ingest_referees(2024)
    assert n == 1  # fixture 1000 (no referee) skipped
    with sm() as s:
        row = s.execute(select(match_officials)).one()
    assert row.referee == "Michael Oliver" and row.fixture_ref == "999"
