"""Phase 3 integration: availability matrix, walk-forward panel (leakage audit,
causal features, horizon targets), per-position assembly."""

import httpx
from sqlalchemy import select

from fpl_engine.db.models import feature_availability, training_rows
from fpl_engine.features.availability import AvailabilityBuilder
from fpl_engine.features.families import FeatureMatrixBuilder
from fpl_engine.features.panel import PanelBuilder
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.ingest.vaastav import VaastavIngestor
from fpl_engine.resolve import CrosswalkBuilder
from fpl_engine.store.dc import DcReconstructor
from fpl_engine.store.facts import FactBuilder
from fpl_engine.store.targets import TargetBuilder

PLAYERS_RAW = (
    "code,id,first_name,second_name,web_name,team,element_type\n"
    "100,1,Bukayo,Saka,Saka,1,3\n"   # MID
)
# 3 single-fixture GWs for one player. total_points: 6, 2, 9.
_COLS = (
    "name,element,fixture,round,GW,opponent_team,was_home,minutes,goals_scored,"
    "assists,clean_sheets,goals_conceded,own_goals,penalties_saved,penalties_missed,"
    "saves,yellow_cards,red_cards,bonus,total_points,value,selected,transfers_balance,"
    "kickoff_time,tackles,clearances_blocks_interceptions,recoveries,defensive_contribution,"
    "expected_goals,expected_assists,ict_index\n"
)
# expected_goals/ict_index are Numeric -> arrive as Decimal from the DB, which
# exercises the float-coercion path in the windowing engine.
MERGED_GW = _COLS + (
    "Saka,1,10,1,1,2,True,90,0,1,0,0,0,0,0,0,0,0,1,6,100,1,0,2025-08-16T14:00:00Z,1,2,5,3,0.4,0.7,5.2\n"
    "Saka,1,20,2,2,3,False,90,0,0,0,1,0,0,0,0,0,0,0,2,100,1,0,2025-08-23T14:00:00Z,2,3,6,5,0.2,0.1,2.1\n"
    "Saka,1,30,3,3,4,True,45,1,0,0,0,0,0,0,0,0,0,3,9,100,1,0,2025-08-30T14:00:00Z,0,1,2,1,0.9,0.0,8.8\n"
)
FIXTURES = (
    "id,event,team_h,team_a,team_h_score,team_a_score,team_h_difficulty,"
    "team_a_difficulty,kickoff_time\n"
    "10,1,1,2,1,1,2,3,2025-08-16T14:00:00Z\n"
    "20,2,3,1,2,0,3,2,2025-08-23T14:00:00Z\n"
    "30,3,1,4,1,0,2,4,2025-08-30T14:00:00Z\n"
)
_FILES = {"players_raw.csv": PLAYERS_RAW, "gws/merged_gw.csv": MERGED_GW,
          "fixtures.csv": FIXTURES}


def _handler(request: httpx.Request) -> httpx.Response:
    for name, body in _FILES.items():
        if request.url.path.endswith(name):
            return httpx.Response(200, text=body)
    return httpx.Response(404, text="404")


def _pipeline(sm):
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    v = VaastavIngestor(FetchClient(client=http, sm=sm), sm=sm)
    v.acquire(seasons=["2025-26"], files=["players_raw", "merged_gw", "fixtures"])
    CrosswalkBuilder(v, sm=sm).build_fpl(seasons=["2025-26"])
    FactBuilder(v, sm=sm).build_player_match_stats(seasons=["2025-26"])
    DcReconstructor(sm=sm).build(seasons=["2025-26"])
    TargetBuilder(sm=sm).build(seasons=["2025-26"])


def test_availability_matrix(sm):
    _pipeline(sm)
    AvailabilityBuilder(sm=sm).build(seasons=["2025-26"])
    with sm() as s:
        cov = {r.metric: float(r.coverage) for r in s.execute(
            select(feature_availability).where(
                feature_availability.c.season == "2025-26")).all()}
    assert cov["minutes"] == 1.0
    assert cov["defensive_contribution"] == 1.0  # present in 2025-26


def test_panel_targets_and_causal_features(sm):
    _pipeline(sm)
    PanelBuilder(sm=sm).build(seasons=["2025-26"], min_history=1)

    with sm() as s:
        rows = {r.gw: r for r in s.execute(
            select(training_rows).where(training_rows.c.player_key == 100)
            .order_by(training_rows.c.gw)).all()}

    # GW1 has no prior history -> no prediction point.
    assert set(rows) == {2, 3}

    gw2 = rows[2]
    # target = realised points in GW2; horizon sums forward only.
    assert gw2.tgt_pts_next1 == 2
    assert gw2.tgt_pts_next6 == 2 + 9     # GW2 + GW3 (rest of available)
    assert gw2.tgt_pts_ros == 2 + 9
    assert gw2.hist_n == 1
    # features use only GW1 (strictly prior): mean of total_points == 6
    assert gw2.features["total_points__mean_3"] == 6.0
    assert gw2.features["minutes__mean_5"] == 90.0

    gw3 = rows[3]
    assert gw3.tgt_pts_next1 == 9
    assert gw3.features["total_points__mean_3"] == (6 + 2) / 2  # GW1+GW2 only
    # Numeric (Decimal) columns flow through the EWMA path without error.
    assert gw3.features["expected_goals__mean_3"] == (0.4 + 0.2) / 2
    assert isinstance(gw3.features["expected_goals__ewma_hl2"], float)


def test_leakage_audit_passes(sm):
    _pipeline(sm)
    PanelBuilder(sm=sm).build(seasons=["2025-26"], min_history=1)
    audit = PanelBuilder(sm=sm).leakage_audit(season="2025-26")
    assert audit["rows_audited"] == 2
    assert audit["history_after_deadline"] == 0
    assert audit["target_before_deadline"] == 0
    assert audit["ok"] is True


def test_per_position_assembly_has_families_with_spans(sm):
    _pipeline(sm)
    PanelBuilder(sm=sm).build(seasons=["2025-26"], min_history=1)
    matrix = FeatureMatrixBuilder(sm=sm).assemble("2025-26", position=3)  # MID

    assert {"availability", "goal_threat", "creation", "dc_cbirt",
            "team_attack", "bonus_drivers"} <= set(matrix.families)
    # DC family is span-tagged to the dc source.
    assert matrix.families["dc_cbirt"].sources == ("dc",)
    # creation mixes fpl_basic + fpl_xg sources.
    assert set(matrix.families["creation"].sources) >= {"fpl_basic", "fpl_xg"}
    # every family resolved to at least one concrete feature key
    assert all(spec.feature_keys for spec in matrix.families.values())
