"""Phase 2 integration: facts -> DC reconstruction -> targets, on synthetic
2025/26 data that carries the real DC component columns."""

import httpx
from sqlalchemy import select

from fpl_engine.db.models import dc_match
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.ingest.vaastav import VaastavIngestor
from fpl_engine.resolve import CrosswalkBuilder
from fpl_engine.store.dc import DcReconstructor
from fpl_engine.store.facts import FactBuilder
from fpl_engine.store.targets import TargetBuilder

PLAYERS_RAW = (
    "code,id,first_name,second_name,web_name,team,element_type\n"
    "100,1,Bukayo,Saka,Saka,1,3\n"        # MID
    "300,3,William,Saliba,Saliba,1,2\n"   # DEF
    "400,4,David,Raya,Raya,1,1\n"         # GK
    "500,5,Mikel,Arteta,Arteta,1,5\n"     # manager (out of scope)
)
# 2025/26 merged_gw includes tackles, clearances_blocks_interceptions,
# recoveries, defensive_contribution.
MERGED_GW = (
    "name,element,fixture,round,GW,opponent_team,was_home,minutes,goals_scored,"
    "assists,clean_sheets,goals_conceded,own_goals,penalties_saved,penalties_missed,"
    "saves,yellow_cards,red_cards,bonus,total_points,value,selected,transfers_balance,"
    "kickoff_time,tackles,clearances_blocks_interceptions,recoveries,defensive_contribution\n"
    # Saka MID: app2+goal5+assist3+CS(MID)1+DC2+bonus3 = 16; CBIRT=2+3+8=13>=12 hit
    "Saka,1,10,1,1,2,True,90,1,1,1,0,0,0,0,0,0,0,3,16,100,500000,0,"
    "2025-08-16T14:00:00Z,2,3,8,13\n"
    # Saliba DEF: app2+CS(DEF)4+DC2+bonus1 = 9; CBIT=4+7=11>=10 hit
    "Saliba,3,10,1,1,2,True,90,0,0,1,0,0,0,0,0,0,0,1,9,60,400000,0,"
    "2025-08-16T14:00:00Z,4,7,5,11\n"
    # Raya GK: app2+CS(GK)4+saves(3//3=1) = 7; GK ineligible for DC
    "Raya,4,10,1,1,2,True,90,0,0,1,0,0,0,0,3,0,0,0,7,55,300000,0,"
    "2025-08-16T14:00:00Z,0,0,2,0\n"
    # Manager (element_type 5): scores via a separate ruleset -> excluded
    "Arteta,5,10,1,1,2,True,90,0,0,0,0,0,0,0,0,0,0,0,8,0,0,0,"
    "2025-08-16T14:00:00Z,0,0,0,0\n"
)
FIXTURES = (
    "id,event,team_h,team_a,team_h_score,team_a_score,team_h_difficulty,"
    "team_a_difficulty,kickoff_time\n"
    "10,1,1,2,3,0,2,4,2025-08-16T14:00:00Z\n"
)

_FILES = {
    "players_raw.csv": PLAYERS_RAW,
    "gws/merged_gw.csv": MERGED_GW,
    "fixtures.csv": FIXTURES,
}


def _handler(request: httpx.Request) -> httpx.Response:
    for name, body in _FILES.items():
        if request.url.path.endswith(name):
            return httpx.Response(200, text=body)
    return httpx.Response(404, text="404: Not Found")


def _setup(sm):
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    v = VaastavIngestor(FetchClient(client=http, sm=sm), sm=sm)
    v.acquire(seasons=["2025-26"], files=["players_raw", "merged_gw", "fixtures"])
    CrosswalkBuilder(v, sm=sm).build_fpl(seasons=["2025-26"])
    FactBuilder(v, sm=sm).build_player_match_stats(seasons=["2025-26"])
    return v


def test_dc_reconstruction_and_validation(sm):
    _setup(sm)
    recon = DcReconstructor(sm=sm)
    recon.build(seasons=["2025-26"])

    with sm() as s:
        saka = s.execute(select(dc_match).where(
            dc_match.c.element_id == 1, dc_match.c.fixture_id == 10)).one()
        saliba = s.execute(select(dc_match).where(
            dc_match.c.element_id == 3, dc_match.c.fixture_id == 10)).one()
        raya = s.execute(select(dc_match).where(
            dc_match.c.element_id == 4, dc_match.c.fixture_id == 10)).one()

    assert saka.cbit == 5 and saka.cbirt == 13 and saka.dc_value == 13 and saka.dc_hit is True
    assert saliba.cbit == 11 and saliba.dc_value == 11 and saliba.dc_hit is True
    assert raya.dc_value is None and raya.dc_hit is False  # GK ineligible

    # Reconstructed dc_value matches FPL's official defensive_contribution.
    v = recon.validate_against_official("2025-26")
    assert v.n == 2  # GK excluded (dc_value NULL)
    assert v.exact == 2
    assert v.agreement == 1.0


def test_targets_reproduce_actual_points(sm):
    _setup(sm)
    DcReconstructor(sm=sm).build(seasons=["2025-26"])
    tb = TargetBuilder(sm=sm)
    tb.build(seasons=["2025-26"])

    repro = tb.reproduction("2025-26")
    assert repro.n == 3              # manager (element_type 5) excluded
    assert repro.exact == 3          # converter reproduces all actual points
    assert repro.exact_rate == 1.0
    assert repro.max_abs_error == 0


def test_normalised_is_rule_invariant_when_dc_known(sm):
    """When DC is observable, normalised_points (current rules) re-scores a
    pre-DC season by adding the +2 the old rules omitted; dc_known is set."""
    from sqlalchemy import select as _select

    from fpl_engine.db.models import targets as targets_t

    # Same fixtures, but label the season 2024-25 (rules had no DC). Because
    # the synthetic rows still carry DC components, dc_match is built and DC
    # is "known", so normalised must exceed as_played for threshold hitters.
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    v = VaastavIngestor(FetchClient(client=http, sm=sm), sm=sm)
    v.acquire(seasons=["2024-25"], files=["players_raw", "merged_gw", "fixtures"])
    CrosswalkBuilder(v, sm=sm).build_fpl(seasons=["2024-25"])
    FactBuilder(v, sm=sm).build_player_match_stats(seasons=["2024-25"])
    DcReconstructor(sm=sm).build(seasons=["2024-25"])
    TargetBuilder(sm=sm).build(seasons=["2024-25"])

    with sm() as s:
        saliba = s.execute(_select(targets_t).where(
            targets_t.c.season == "2024-25", targets_t.c.element_id == 3)).one()
        raya = s.execute(_select(targets_t).where(
            targets_t.c.season == "2024-25", targets_t.c.element_id == 4)).one()

    # Saliba (DEF) hit CBIT>=10: 2024-25 rules give no DC, current rules give +2.
    assert saliba.as_played_points == 7        # app2 + CS4 + bonus1 (no DC)
    assert saliba.normalised_points == 9       # + DC2 under current rules
    assert saliba.dc_known is True
    # GK never eligible for DC -> always known-complete, equal scores.
    assert raya.dc_known is True
    assert raya.as_played_points == raya.normalised_points
