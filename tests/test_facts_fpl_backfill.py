"""FPL-API backfill of player_match_stats for GWs the vaastav CSVs lack
(the just-finished season lags upstream). Mocks /event/{gw}/live/."""

import httpx
from sqlalchemy import select

from fpl_engine.db.models import (
    player_match_stats,
    players,
    team_match_stats,
    teams,
)
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.ingest.vaastav import VaastavIngestor
from fpl_engine.store.facts import FactBuilder

SEASON = "2025-26"

LIVE = {"elements": [{
    "id": 1,
    "stats": {"minutes": 90, "starts": 1, "goals_scored": 1, "assists": 0,
              "clean_sheets": 0, "goals_conceded": 1, "saves": 0, "bonus": 2,
              "bps": 30, "total_points": 8, "expected_goals": "0.50",
              "expected_assists": "0.10", "defensive_contribution": 3,
              "tackles": 1, "recoveries": 4, "clearances_blocks_interceptions": 2},
    "explain": [{"fixture": 500, "stats": []}],
}]}


def _handler(req: httpx.Request) -> httpx.Response:
    if req.url.path.endswith("/event/30/live/"):
        return httpx.Response(200, json=LIVE)
    return httpx.Response(404, text="not found")


def test_fpl_backfill_inserts_missing_gw_with_correct_mapping(sm):
    with sm() as s:
        s.execute(teams.insert(), [{"id": 1, "name": "Home"}, {"id": 2, "name": "Away"}])
        s.execute(players.insert(), [
            {"id": 1, "element_type": 3, "team_id": 1, "now_cost": 75,
             "status": "a", "web_name": "P1"}])
        s.execute(team_match_stats.insert(), [
            {"season": SEASON, "fixture_id": 500, "team_id": 1,
             "opponent_team_id": 2, "gw": 30, "was_home": True}])
        s.commit()

    http = httpx.Client(transport=httpx.MockTransport(_handler))
    fetch = FetchClient(client=http, sm=sm)
    fb = FactBuilder(VaastavIngestor(fetch, sm=sm), sm=sm)
    fb.build_player_match_stats_fpl(SEASON, [30], fetch)

    with sm() as s:
        row = s.execute(select(player_match_stats).where(
            player_match_stats.c.season == SEASON,
            player_match_stats.c.gw == 30)).one()
    # stats carried from the live feed
    assert row.element_id == 1 and row.fixture_id == 500
    assert row.total_points == 8 and row.minutes == 90 and row.goals_scored == 1
    assert row.defensive_contribution == 3 and float(row.expected_goals) == 0.5
    # opponent / venue resolved from the fixtures table; price + position from players
    assert row.opponent_team_id == 2 and row.was_home is True
    assert row.element_type == 3 and row.value == 75


def test_fpl_backfill_upserts_without_duplicating(sm):
    with sm() as s:
        s.execute(teams.insert(), [{"id": 1, "name": "Home"}, {"id": 2, "name": "Away"}])
        s.execute(players.insert(), [
            {"id": 1, "element_type": 3, "team_id": 1, "now_cost": 75, "web_name": "P1"}])
        s.execute(team_match_stats.insert(), [
            {"season": SEASON, "fixture_id": 500, "team_id": 1,
             "opponent_team_id": 2, "gw": 30, "was_home": True}])
        s.commit()
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    fetch = FetchClient(client=http, sm=sm)
    fb = FactBuilder(VaastavIngestor(fetch, sm=sm), sm=sm)
    fb.build_player_match_stats_fpl(SEASON, [30], fetch)
    fb.build_player_match_stats_fpl(SEASON, [30], fetch)  # re-run
    with sm() as s:
        n = s.execute(select(player_match_stats).where(
            player_match_stats.c.season == SEASON)).all()
    assert len(n) == 1  # upsert on (season, element_id, fixture_id), no dupes
