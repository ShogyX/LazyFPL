"""Elite cohort: enumeration, picks, EO aggregation, loader override (mocked)."""

import httpx
from sqlalchemy import select

from fpl_engine.db.models import (
    elite_managers,
    elite_ownership,
    players,
    predictions_player_gw,
)
from fpl_engine.ingest.elite import EliteCohortIngestor, latest_elite_eo
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.optimise.loader import load_candidates

# Two standings pages (has_next chains them); 3 managers total.
PAGE_1 = {"standings": {"has_next": True, "results": [
    {"entry": 11, "player_name": "Ann", "rank": 1, "total": 2600},
    {"entry": 12, "player_name": "Bob", "rank": 2, "total": 2590},
]}}
PAGE_2 = {"standings": {"has_next": False, "results": [
    {"entry": 13, "player_name": "Cat", "rank": 3, "total": 2580},
]}}

# Picks per manager for GW20. Player 100 owned by all 3 + captained by 2.
PICKS = {
    11: [{"element": 100, "multiplier": 2, "is_captain": True},
         {"element": 200, "multiplier": 1, "is_captain": False}],
    12: [{"element": 100, "multiplier": 2, "is_captain": True},
         {"element": 201, "multiplier": 1, "is_captain": False}],
    13: [{"element": 100, "multiplier": 1, "is_captain": False},
         {"element": 200, "multiplier": 1, "is_captain": False}],
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if "/leagues-classic/" in path:
        page = int(request.url.params.get("page_standings", "1"))
        return httpx.Response(200, json=PAGE_1 if page == 1 else PAGE_2)
    for eid, picks in PICKS.items():
        if path.endswith(f"/entry/{eid}/event/20/picks/"):
            return httpx.Response(200, json={"picks": picks})
    return httpx.Response(404, json={})


def _ingestor(sm) -> EliteCohortIngestor:
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    return EliteCohortIngestor(FetchClient(client=http, sm=sm), sm=sm)


def test_enumerate_cohort_pages(sm):
    res = _ingestor(sm).enumerate_cohort(max_managers=10)
    assert res.managers == 3
    with sm() as s:
        ranks = {r.entry_id: r.rank for r in s.execute(select(elite_managers)).all()}
    assert ranks == {11: 1, 12: 2, 13: 3}


def test_enumerate_respects_max(sm):
    res = _ingestor(sm).enumerate_cohort(max_managers=2)
    assert res.managers == 2  # stops mid-cohort


def test_picks_and_ownership_aggregate(sm):
    ing = _ingestor(sm)
    ing.enumerate_cohort(max_managers=10)
    ing.ingest_picks(20)
    res = ing.aggregate_ownership(20)
    assert res.n_managers == 3

    with sm() as s:
        eo = {r.element_id: r for r in s.execute(select(elite_ownership)).all()}
    # Player 100: owned 3/3, captained 2/3 -> EO = (3+2)/3 = 1.6667
    assert eo[100].owned == 3 and eo[100].captained == 2
    assert abs(float(eo[100].eo) - (5 / 3)) < 1e-6
    # Player 200: owned 2/3, captained 0 -> EO = 2/3
    assert abs(float(eo[200].eo) - (2 / 3)) < 1e-6


def test_latest_elite_eo_helper_returns_percent(sm):
    ing = _ingestor(sm)
    ing.enumerate_cohort(max_managers=10)
    ing.ingest_picks(20)
    ing.aggregate_ownership(20)
    eo = latest_elite_eo(20, sm=sm)
    assert abs(eo[100] - (5 / 3) * 100.0) < 1e-4   # percent scale


def test_loader_applies_elite_eo_override(sm):
    with sm() as s:
        s.execute(players.insert(), [{
            "id": 100, "web_name": "Star", "team_id": 1, "element_type": 4,
            "now_cost": 120, "status": "a", "selected_by_percent": 40.0}])
        s.execute(predictions_player_gw.insert(), [{
            "model_version": "vt", "season": "2025-26", "gw": 20, "player_key": 9001,
            "element_id": 100, "element_type": 4, "xp_next1": 8.0, "pred_minutes": 90}])
        s.commit()

    # Without override: global selected_by_percent (40.0).
    [base] = load_candidates("2025-26", 20, model_version="vt", sm=sm)
    assert base.ownership == 40.0

    # With elite EO override (e.g. 85%): overlay sees the elite signal instead.
    [over] = load_candidates("2025-26", 20, model_version="vt", sm=sm,
                             eo_override={100: 85.0})
    assert over.ownership == 85.0
