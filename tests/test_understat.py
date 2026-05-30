"""Understat ingestion: embedded-JSON extraction + season acquisition (mocked)."""

import json

import httpx
from sqlalchemy import func, select

from fpl_engine.db.models import raw_snapshots
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.ingest.understat import (
    UnderstatIngestor,
    extract_json_var,
    understat_year,
)


def _hexify(obj) -> str:
    """Mimic Understat's `JSON.parse('\\xNN...')` hex-escaped embedding."""
    s = json.dumps(obj)
    return "".join(f"\\x{ord(c):02x}" for c in s)


def _league_html(dates, players) -> str:
    return (
        "<html><script>\n"
        f"var datesData = JSON.parse('{_hexify(dates)}');\n"
        f"var playersData = JSON.parse('{_hexify(players)}');\n"
        "</script></html>"
    )


def _match_html(rosters) -> str:
    return f"<html><script>var rostersData = JSON.parse('{_hexify(rosters)}');</script></html>"


DATES = [
    {"id": "1001", "isResult": True, "datetime": "2024-08-17 14:00:00",
     "h": {"id": "89", "title": "Manchester City"},
     "a": {"id": "88", "title": "Chelsea"},
     "goals": {"h": "2", "a": "1"}},
    {"id": "1002", "isResult": True, "datetime": "2024-08-18 16:30:00",
     "h": {"id": "87", "title": "Liverpool"},
     "a": {"id": "86", "title": "Arsenal"},
     "goals": {"h": "1", "a": "1"}},
    {"id": "9999", "isResult": False, "datetime": "2025-05-01 14:00:00",
     "h": {"id": "89", "title": "Manchester City"},
     "a": {"id": "87", "title": "Liverpool"}},  # unplayed -> excluded
]

PLAYERS = [
    {"id": "501", "player_name": "Erling Haaland", "team_title": "Manchester City",
     "position": "F", "games": "1", "goals": "1", "xG": "0.8"},
    {"id": "777", "player_name": "Cole Palmer", "team_title": "Chelsea",
     "position": "M", "games": "1", "goals": "1", "xG": "0.4"},
]

MATCH_1001 = {
    "h": {
        "501": {"id": "9001", "player_id": "501", "player": "Erling Haaland",
                "team": "Manchester City", "position": "FW", "time": "90",
                "goals": "1", "assists": "0", "shots": "4", "key_passes": "1",
                "xG": "0.85", "xA": "0.10", "npg": "1", "npxG": "0.80",
                "xGChain": "1.2", "xGBuildup": "0.3"},
    },
    "a": {
        "777": {"id": "9002", "player_id": "777", "player": "Cole Palmer",
                "team": "Chelsea", "position": "MF", "time": "90",
                "goals": "1", "assists": "0", "shots": "3", "key_passes": "2",
                "xG": "0.40", "xA": "0.35", "npg": "0", "npxG": "0.10",
                "xGChain": "0.9", "xGBuildup": "0.5"},
    },
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/league/EPL/2024":
        return httpx.Response(200, text=_league_html(DATES, PLAYERS))
    if path == "/match/1001":
        return httpx.Response(200, text=_match_html(MATCH_1001))
    if path == "/match/1002":
        return httpx.Response(200, text=_match_html({"h": {}, "a": {}}))
    return httpx.Response(404, text="not found")


def _ingestor(sm) -> UnderstatIngestor:
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    return UnderstatIngestor(FetchClient(client=http, sm=sm), sm=sm)


def test_understat_year_mapping():
    assert understat_year("2024-25") == 2024
    assert understat_year("2014-15") == 2014


def test_extract_json_var_roundtrip():
    html = _league_html(DATES, PLAYERS)
    dates = extract_json_var(html, "datesData")
    assert isinstance(dates, list) and dates[0]["id"] == "1001"
    assert extract_json_var(html, "missingVar") is None


def test_acquire_season_snapshots_league_and_matches(sm):
    ing = _ingestor(sm)
    res = ing.acquire_season("2024-25")
    assert res.league.status == 200
    # 2 played matches enumerated (the unplayed fixture is skipped).
    assert len(res.matches) == 2
    assert all(m.status == 200 for m in res.matches)

    with sm() as s:
        n = s.execute(select(func.count()).select_from(raw_snapshots).where(
            raw_snapshots.c.provider == "understat")).scalar_one()
    assert n == 3  # 1 league + 2 match pages


def test_match_rosters_flattened_with_side(sm):
    ing = _ingestor(sm)
    ing.acquire_season("2024-25")
    rosters = ing.match_rosters("2024-25", "1001")
    assert len(rosters) == 2
    by_player = {r["player_id"]: r for r in rosters}
    assert by_player["501"]["side"] == "h"
    assert by_player["777"]["side"] == "a"
    assert by_player["501"]["xG"] == "0.85"


def test_league_players_and_dates_readback(sm):
    ing = _ingestor(sm)
    ing.acquire_season("2024-25")
    assert ing.league_players("2024-25")[0]["player_name"] == "Erling Haaland"
    assert len(ing.league_dates("2024-25")) == 3


def test_reacquire_dedupes(sm):
    ing = _ingestor(sm)
    ing.acquire_season("2024-25")
    res2 = ing.acquire_season("2024-25")
    assert res2.league.deduped is True
    assert all(m.deduped for m in res2.matches)
    with sm() as s:  # no new rows on identical re-pull
        n = s.execute(select(func.count()).select_from(raw_snapshots).where(
            raw_snapshots.c.provider == "understat")).scalar_one()
    assert n == 3
