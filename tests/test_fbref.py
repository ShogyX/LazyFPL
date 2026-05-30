"""FBref ingestion: stdlib data-stat table parsing + match normalisation."""

from datetime import date, datetime, timezone

import httpx
from sqlalchemy import select

from fpl_engine.db.models import (
    player_advanced_match_stats,
    player_identity,
    team_match_stats,
    teams,
)
from fpl_engine.ingest.fbref import FBrefIngestor, parse_table
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.resolve.crosswalk import CrosswalkBuilder
from fpl_engine.store.advanced import AdvancedStatsBuilder

# A summary table for the home side, with one repeated header row in the body
# and a non-player "totals" footer row that must be dropped.
HOME_TABLE = """
<table id="stats_summary_home">
 <thead><tr><th data-stat="player">Player</th></tr></thead>
 <tbody>
  <tr><th data-stat="player" data-append-csv="haaland01"><a href="/en/players/haaland01/">Erling Haaland</a></th>
      <td data-stat="minutes">90</td><td data-stat="goals">1</td>
      <td data-stat="xg">0.85</td><td data-stat="npxg">0.80</td>
      <td data-stat="sca">3</td><td data-stat="gca">1</td>
      <td data-stat="progressive_passes">2</td><td data-stat="tackles">1</td></tr>
  <tr class="thead"><th data-stat="player">Player</th></tr>
  <tr><td data-stat="minutes">90</td><td data-stat="goals">1</td></tr>
 </tbody>
</table>
"""

# An away table wrapped in an HTML comment (FBref defers rendering this way).
AWAY_TABLE = """
<!--
<table id="stats_summary_away">
 <tbody>
  <tr><th data-stat="player" data-append-csv="palmer01">Cole Palmer</th>
      <td data-stat="minutes">90</td><td data-stat="goals">1</td>
      <td data-stat="xg">0.40</td><td data-stat="sca">4</td>
      <td data-stat="progressive_carries">5</td></tr>
 </tbody>
</table>
-->
"""

PAGE = f"<html><body>{HOME_TABLE}{AWAY_TABLE}</body></html>"


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/match/abc":
        return httpx.Response(200, text=PAGE)
    return httpx.Response(404, text="nope")


def test_parse_table_reads_data_stat_rows_and_player_id():
    rows = parse_table(HOME_TABLE, "stats_summary_home")
    assert len(rows) == 1                      # repeated-header + totals dropped
    r = rows[0]
    assert r["_id"] == "haaland01"
    assert r["player"] == "Erling Haaland"
    assert r["goals"] == "1" and r["xg"] == "0.85"
    assert r["sca"] == "3" and r["progressive_passes"] == "2"


def test_parse_table_reveals_commented_tables():
    rows = parse_table(AWAY_TABLE, "stats_summary_away")
    assert len(rows) == 1 and rows[0]["_id"] == "palmer01"


def test_fbref_ingest_and_read_table(sm):
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    ing = FBrefIngestor(FetchClient(client=http, sm=sm), sm=sm)
    stat = ing.acquire("/match/abc", season="2024-25")
    assert stat.status == 200
    rows = ing.read_table("/match/abc", "stats_summary_home")
    assert rows[0]["_id"] == "haaland01"
    # re-acquire dedupes (content-addressed snapshot)
    assert ing.acquire("/match/abc", season="2024-25").deduped is True


def _seed(sm):
    with sm() as s:
        s.execute(teams.insert(), [
            {"id": 1, "name": "Man City", "short_name": "MCI"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
        ])
        s.execute(team_match_stats.insert(), [
            {"season": "2024-25", "fixture_id": 5001, "team_id": 1,
             "opponent_team_id": 2, "gw": 1, "was_home": True,
             "kickoff_time": datetime(2024, 8, 17, 14, 0, tzinfo=timezone.utc)},
        ])
        s.execute(player_identity.insert(), [
            {"player_key": 90001, "web_name": "Haaland", "first_name": "Erling",
             "second_name": "Haaland", "last_season": "2024-25"},
            {"player_key": 90002, "web_name": "Palmer", "first_name": "Cole",
             "second_name": "Palmer", "last_season": "2024-25"},
        ])
        s.commit()


def test_build_fbref_match_resolves_and_writes(sm):
    _seed(sm)
    xwalk = CrosswalkBuilder(None, sm=sm)
    # Season FBref player list -> fbref crosswalk (keyed by FBref player id).
    xwalk.match_source("fbref", "2024-25", [
        {"id": "haaland01", "name": "Erling Haaland", "team": "Manchester City"},
        {"id": "palmer01", "name": "Cole Palmer", "team": "Chelsea"},
    ], id_field="id", name_field="name", team_field="team")

    builder = AdvancedStatsBuilder(understat=None, crosswalk=xwalk, sm=sm)
    home = parse_table(HOME_TABLE, "stats_summary_home")
    away = parse_table(AWAY_TABLE, "stats_summary_away")
    res = builder.build_fbref_match(
        "2024-25", "abc", home_title="Manchester City", away_title="Chelsea",
        match_date=date(2024, 8, 17), home_rows=home, away_rows=away)

    assert res.rows_written == 2
    assert res.players_resolved == 2
    assert res.fixtures_resolved == 1

    with sm() as s:
        rows = {r.source_player_id: r for r in s.execute(
            select(player_advanced_match_stats).where(
                player_advanced_match_stats.c.source == "fbref")).all()}
    h = rows["haaland01"]
    assert h.player_key == 90001 and h.fixture_id == 5001 and h.was_home is True
    assert float(h.xg) == 0.85 and float(h.sca) == 3 and float(h.prog_passes) == 2
    assert rows["palmer01"].was_home is False
    assert float(rows["palmer01"].prog_carries) == 5
