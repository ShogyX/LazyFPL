"""Normalise Understat advanced stats: player + fixture resolution (mocked)."""

from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from fpl_engine.db.models import (
    player_advanced_match_stats,
    player_identity,
    team_match_stats,
    teams,
)
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.ingest.understat import UnderstatIngestor
from fpl_engine.resolve.crosswalk import CrosswalkBuilder
from fpl_engine.store.advanced import AdvancedStatsBuilder
from tests.test_understat import _handler  # reuse the mocked Understat pages


def _seed(sm):
    """FPL teams, the home fixture facts, and player identities to resolve onto."""
    with sm() as s:
        s.execute(teams.insert(), [
            {"id": 1, "name": "Man City", "short_name": "MCI"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
            {"id": 3, "name": "Liverpool", "short_name": "LIV"},
            {"id": 4, "name": "Arsenal", "short_name": "ARS"},
        ])
        # Home rows only are needed for the (home_team_id, date) fixture index.
        s.execute(team_match_stats.insert(), [
            {"season": "2024-25", "fixture_id": 5001, "team_id": 1,
             "opponent_team_id": 2, "gw": 1, "was_home": True,
             "kickoff_time": datetime(2024, 8, 17, 14, 0, tzinfo=timezone.utc)},
            {"season": "2024-25", "fixture_id": 5002, "team_id": 3,
             "opponent_team_id": 4, "gw": 1, "was_home": True,
             "kickoff_time": datetime(2024, 8, 18, 16, 30, tzinfo=timezone.utc)},
        ])
        # Identities Haaland + Palmer can fuzzy-match onto.
        s.execute(player_identity.insert(), [
            {"player_key": 90001, "web_name": "Haaland",
             "first_name": "Erling", "second_name": "Haaland", "last_season": "2024-25"},
            {"player_key": 90002, "web_name": "Palmer",
             "first_name": "Cole", "second_name": "Palmer", "last_season": "2024-25"},
        ])
        s.commit()


def _builder(sm) -> AdvancedStatsBuilder:
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    fetch = FetchClient(client=http, sm=sm)
    us = UnderstatIngestor(fetch, sm=sm)
    us.acquire_season("2024-25")  # populate raw snapshots first
    return AdvancedStatsBuilder(us, CrosswalkBuilder(None, sm=sm), sm=sm)


def test_build_understat_resolves_players_and_fixtures(sm):
    _seed(sm)
    [res] = _builder(sm).build_understat(["2024-25"])

    # Match 1001 has 2 roster rows (Haaland home, Palmer away); 1002 is empty.
    assert res.rows_written == 2
    assert res.players_resolved == 2 and res.players_unresolved == 0

    with sm() as s:
        rows = {r.source_player_id: r for r in s.execute(
            select(player_advanced_match_stats)).all()}

    haaland = rows["501"]
    assert haaland.player_key == 90001
    assert haaland.fixture_id == 5001        # Man City home on 2024-08-17
    assert haaland.was_home is True
    assert float(haaland.xg) == 0.85
    assert float(haaland.npxg) == 0.80
    assert haaland.source_opponent == "Chelsea"

    palmer = rows["777"]
    assert palmer.player_key == 90002
    assert palmer.fixture_id == 5001         # same fixture, away side
    assert palmer.was_home is False


def test_build_understat_idempotent(sm):
    _seed(sm)
    b = _builder(sm)
    b.build_understat(["2024-25"])
    b.build_understat(["2024-25"])
    with sm() as s:
        n = len(s.execute(select(player_advanced_match_stats)).all())
    assert n == 2  # upsert on source keys -> no duplication
