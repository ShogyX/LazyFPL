import httpx
import pytest
from sqlalchemy import func, select

from fpl_engine.db.models import (
    id_crosswalk,
    player_identity,
    player_match_stats,
    team_match_stats,
)
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.ingest.vaastav import VaastavIngestor
from fpl_engine.resolve import CrosswalkBuilder
from fpl_engine.resolve.names import best_match, normalize_name
from fpl_engine.store.facts import FactBuilder

PLAYERS_RAW = (
    "code,id,first_name,second_name,web_name,team,element_type\n"
    "100,1,Bukayo,Saka,Saka,1,3\n"
    "200,2,Ollie,Watkins,Watkins,2,4\n"
)
MERGED_GW = (
    "name,element,fixture,round,GW,opponent_team,was_home,minutes,goals_scored,"
    "assists,total_points,value,selected,transfers_balance,kickoff_time,expected_goals\n"
    "Saka,1,10,1,1,2,True,90,1,0,9,100,500000,0,2024-08-17T14:00:00Z,0.7\n"
    "Watkins,2,10,1,1,1,False,80,0,0,2,90,400000,0,2024-08-17T14:00:00Z,0.4\n"
    "Saka,1,20,2,2,3,False,0,0,0,0,100,510000,0,2024-08-24T14:00:00Z,0.0\n"
)
FIXTURES = (
    "id,event,team_h,team_a,team_h_score,team_a_score,team_h_difficulty,"
    "team_a_difficulty,kickoff_time\n"
    "10,1,1,2,2,1,3,4,2024-08-17T14:00:00Z\n"
    "20,2,3,1,1,1,2,3,2024-08-24T14:00:00Z\n"
)

_FILES = {
    "players_raw.csv": PLAYERS_RAW,
    "merged_gw.csv": MERGED_GW,
    "fixtures.csv": FIXTURES,
}


def _handler(request: httpx.Request) -> httpx.Response:
    for name, body in _FILES.items():
        if request.url.path.endswith(name):
            return httpx.Response(200, text=body)
    return httpx.Response(404, text="404: Not Found")


def _vaastav(sm) -> VaastavIngestor:
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    return VaastavIngestor(FetchClient(client=http, sm=sm), sm=sm)


# --- name utils ---
def test_normalize_name_strips_accents_and_punct():
    assert normalize_name("Bruno Fernández (C)!") == "bruno fernandez c"


def test_best_match_threshold():
    cands = [("Bukayo Saka", 100), ("Ollie Watkins", 200)]
    key, score = best_match("B. Saka", cands, threshold=0.5)
    assert key == 100
    key2, _ = best_match("Totally Unknown Person", cands, threshold=0.84)
    assert key2 is None


def test_best_match_rejects_ambiguous_duplicate_names():
    # Two different players share a name -> must not guess one of them.
    cands = [("Danny Ward", 1), ("Danny Ward", 2)]
    key, _ = best_match("Danny Ward", cands, threshold=0.6)
    assert key is None


def test_best_match_aggregates_name_variants_per_key():
    # Same key under two variants must not trigger the ambiguity guard.
    cands = [("Saka", 100), ("Bukayo Saka", 100)]
    key, _ = best_match("Bukayo Saka", cands, threshold=0.6)
    assert key == 100


# --- acquisition ---
def test_acquire_and_coverage(sm):
    v = _vaastav(sm)
    res = v.acquire(seasons=["2024-25"], files=["players_raw", "merged_gw", "fixtures"])
    assert len(res.ok()) == 3
    cov = v.coverage()
    assert cov["2024-25"]["players_raw"] == 2
    assert cov["2024-25"]["merged_gw"] == 3
    assert cov["2024-25"]["teams"] is None  # not acquired -> flagged missing
    # re-pull is idempotent (content-addressed dedupe)
    res2 = v.acquire(seasons=["2024-25"], files=["players_raw"])
    assert res2.files[0].deduped is True


# --- entity resolution ---
def test_crosswalk_build_and_coverage(sm):
    v = _vaastav(sm)
    v.acquire(seasons=["2024-25"], files=["players_raw", "merged_gw"])
    cb = CrosswalkBuilder(v, sm=sm)
    n = cb.build_fpl(seasons=["2024-25"])
    assert n == 2

    with sm() as s:
        assert s.execute(select(func.count()).select_from(player_identity)).scalar_one() == 2
        saka_key = s.execute(
            select(id_crosswalk.c.player_key).where(
                id_crosswalk.c.source == "fpl", id_crosswalk.c.source_id == "1"
            )
        ).scalar_one()
    assert saka_key == 100

    cov = cb.fpl_coverage(seasons=["2024-25"])
    assert cov["2024-25"] == 1.0  # both played players mapped


def test_match_source_fuzzy(sm):
    v = _vaastav(sm)
    v.acquire(seasons=["2024-25"], files=["players_raw"])
    cb = CrosswalkBuilder(v, sm=sm)
    cb.build_fpl(seasons=["2024-25"])

    records = [{"id": "u1", "name": "B. Saka"}, {"id": "u2", "name": "Ollie Watkins"}]
    result = cb.match_source("understat", "2024-25", records, threshold=0.6)
    assert result.matched == 2
    with sm() as s:
        row = s.execute(
            select(id_crosswalk.c.player_key, id_crosswalk.c.confidence).where(
                id_crosswalk.c.source == "understat", id_crosswalk.c.source_id == "u2"
            )
        ).one()
    assert row.player_key == 200
    assert float(row.confidence) > 0.6


# --- per-match facts ---
def test_build_player_and_team_facts(sm):
    v = _vaastav(sm)
    v.acquire(seasons=["2024-25"], files=["players_raw", "merged_gw", "fixtures"])
    CrosswalkBuilder(v, sm=sm).build_fpl(seasons=["2024-25"])
    fb = FactBuilder(v, sm=sm)

    pres = fb.build_player_match_stats(seasons=["2024-25"])
    assert pres[0].rows_written == 3
    tres = fb.build_team_match_stats(seasons=["2024-25"])
    assert tres[0].rows_written == 4  # 2 fixtures x 2 teams

    with sm() as s:
        saka = s.execute(
            select(player_match_stats).where(
                player_match_stats.c.element_id == 1, player_match_stats.c.fixture_id == 10
            )
        ).one()
        assert saka.player_key == 100
        assert saka.goals_scored == 1
        assert saka.was_home is True
        assert float(saka.expected_goals) == 0.7

        home = s.execute(
            select(team_match_stats).where(
                team_match_stats.c.fixture_id == 10, team_match_stats.c.team_id == 1
            )
        ).one()
        assert home.result == "W"
        assert home.points == 3
        assert home.goals_for == 2

    recon = fb.reconcile(seasons=["2024-25"])
    assert recon["2024-25"]["raw_rows"] == 3
    assert recon["2024-25"]["normalised_rows"] == 3
    assert recon["2024-25"]["ok"] is True
