"""Load-bearing leakage tests: a double-gameweek with cross-season history.

If the builder leaked the upcoming GW's matches (or the DGW's second fixture)
into that GW's features, the cross-season mean below would change — so these
assertions actually fail on a leak, unlike a by-construction-clean fixture.
"""

from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from fpl_engine.db.models import training_rows
from fpl_engine.features.panel import PanelBuilder
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.ingest.vaastav import VaastavIngestor
from fpl_engine.resolve import CrosswalkBuilder
from fpl_engine.store.facts import FactBuilder
from fpl_engine.store.targets import TargetBuilder

_COLS = (
    "name,element,fixture,round,GW,opponent_team,was_home,minutes,goals_scored,"
    "assists,clean_sheets,goals_conceded,saves,bonus,total_points,value,selected,"
    "transfers_balance,kickoff_time\n"
)
PLAYERS_RAW = "code,id,first_name,second_name,web_name,team,element_type\n100,1,Bukayo,Saka,Saka,1,3\n"

SEASON_FILES = {
    "2024-25": {
        "players_raw.csv": PLAYERS_RAW,
        "gws/merged_gw.csv": _COLS + (
            "Saka,1,370,37,37,5,True,90,0,0,0,0,0,0,4,100,1,0,2025-05-18T14:00:00Z\n"
            "Saka,1,380,38,38,6,False,90,0,0,0,0,0,0,6,100,1,0,2025-05-25T14:00:00Z\n"
        ),
        "fixtures.csv": (
            "id,event,team_h,team_a,team_h_score,team_a_score,team_h_difficulty,"
            "team_a_difficulty,kickoff_time\n"
            "370,37,1,5,1,0,2,3,2025-05-18T14:00:00Z\n"
            "380,38,6,1,0,1,3,2,2025-05-25T14:00:00Z\n"
        ),
    },
    "2025-26": {
        "players_raw.csv": PLAYERS_RAW,
        # GW1 is a DOUBLE gameweek (fixtures 10 and 11, same round=1).
        "gws/merged_gw.csv": _COLS + (
            "Saka,1,10,1,1,2,True,90,0,0,0,0,0,0,9,100,1,0,2025-08-16T14:00:00Z\n"
            "Saka,1,11,1,1,3,True,90,0,0,0,0,0,0,5,100,1,0,2025-08-19T19:00:00Z\n"
            "Saka,1,20,2,2,4,False,60,0,0,0,0,0,0,2,100,1,0,2025-08-23T14:00:00Z\n"
        ),
        "fixtures.csv": (
            "id,event,team_h,team_a,team_h_score,team_a_score,team_h_difficulty,"
            "team_a_difficulty,kickoff_time\n"
            "10,1,1,2,2,0,2,3,2025-08-16T14:00:00Z\n"
            "11,1,1,3,1,1,3,2,2025-08-19T19:00:00Z\n"
            "20,2,4,1,1,1,2,3,2025-08-23T14:00:00Z\n"
        ),
    },
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    season = "2024-25" if "2024-25" in path else "2025-26"
    for name, body in SEASON_FILES[season].items():
        if path.endswith(name):
            return httpx.Response(200, text=body)
    return httpx.Response(404, text="404")


def _pipeline(sm):
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    v = VaastavIngestor(FetchClient(client=http, sm=sm), sm=sm)
    seasons = ["2024-25", "2025-26"]
    v.acquire(seasons=seasons, files=["players_raw", "merged_gw", "fixtures"])
    CrosswalkBuilder(v, sm=sm).build_fpl(seasons=seasons)
    FactBuilder(v, sm=sm).build_player_match_stats(seasons=seasons)
    TargetBuilder(sm=sm).build(seasons=seasons)
    PanelBuilder(sm=sm).build(seasons=seasons, min_history=1)


def test_dgw_and_cross_season_no_leak(sm):
    _pipeline(sm)
    with sm() as s:
        gw1 = s.execute(select(training_rows).where(
            training_rows.c.season == "2025-26", training_rows.c.gw == 1)).one()

    # History is the two 2024-25 matches only — neither GW1 fixture leaks in.
    assert gw1.hist_n == 2
    assert gw1.features["total_points__mean_3"] == (4 + 6) / 2  # == 5.0, no DGW data
    assert gw1.hist_last_kickoff == datetime(2025, 5, 25, 14, tzinfo=timezone.utc)
    assert gw1.deadline == datetime(2025, 8, 16, 14, tzinfo=timezone.utc)
    # Target for the DGW sums BOTH fixtures.
    assert gw1.tgt_pts_next1 == 9 + 5


def test_independent_audit_matches_builder(sm):
    _pipeline(sm)
    pb = PanelBuilder(sm=sm)
    result = pb.independent_leakage_audit()
    assert result["rows_checked"] >= 2
    assert result["mismatches"] == 0
    assert result["ok"] is True
