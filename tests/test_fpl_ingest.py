import httpx
from sqlalchemy import func, select

from fpl_engine.db.models import players, teams
from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.ingest.fpl import FplIngestor

BOOTSTRAP = {
    "teams": [
        {"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS",
         "strength": 4, "strength_attack_home": 1300, "strength_defence_away": 1200},
        {"id": 2, "code": 7, "name": "Aston Villa", "short_name": "AVL", "strength": 3},
    ],
    "elements": [
        {"id": 1, "code": 100, "web_name": "Saka", "first_name": "Bukayo",
         "second_name": "Saka", "team": 1, "element_type": 3, "now_cost": 100,
         "status": "a", "selected_by_percent": "35.1", "total_points": 150,
         "minutes": 2800, "form": "6.2", "ep_next": "5.5"},
        {"id": 2, "code": 200, "web_name": "Watkins", "first_name": "Ollie",
         "second_name": "Watkins", "team": 2, "element_type": 4, "now_cost": 90,
         "status": "a", "selected_by_percent": "20.0", "total_points": 120,
         "minutes": 2900, "form": "5.0", "ep_next": "5.0"},
    ],
}
FIXTURES = [{"id": 1, "event": 1}, {"id": 2, "event": 1}, {"id": 3, "event": 2}]


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/bootstrap-static/"):
        return httpx.Response(200, json=BOOTSTRAP)
    if request.url.path.endswith("/fixtures/"):
        return httpx.Response(200, json=FIXTURES)
    return httpx.Response(404)  # pragma: no cover


def _client(sm) -> FetchClient:
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    return FetchClient(client=http, sm=sm)


def test_bootstrap_normalises_teams_and_players(sm):
    ing = FplIngestor(_client(sm), sm=sm)
    result = ing.ingest_bootstrap()

    assert result.teams == 2
    assert result.players == 2
    assert result.snapshot_id is not None
    assert result.deduped is False

    with sm() as s:
        assert s.execute(select(func.count()).select_from(teams)).scalar_one() == 2
        assert s.execute(select(func.count()).select_from(players)).scalar_one() == 2
        saka = s.execute(select(players).where(players.c.id == 1)).one()
    assert saka.web_name == "Saka"
    assert saka.team_id == 1
    assert saka.element_type == 3


def test_bootstrap_is_idempotent(sm):
    ing = FplIngestor(_client(sm), sm=sm)
    ing.ingest_bootstrap()
    second = ing.ingest_bootstrap()

    # identical content -> raw snapshot deduped, upsert leaves counts stable
    assert second.deduped is True
    with sm() as s:
        assert s.execute(select(func.count()).select_from(players)).scalar_one() == 2


def test_fixtures_ingest_returns_count(sm):
    ing = FplIngestor(_client(sm), sm=sm)
    assert ing.ingest_fixtures() == 3
