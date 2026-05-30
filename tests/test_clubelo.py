import httpx
from sqlalchemy import select

from fpl_engine.db.models import team_elo, teams
from fpl_engine.ingest.clubelo import ClubEloIngestor
from fpl_engine.ingest.fetch import FetchClient

CLUBELO_CSV = (
    "Rank,Club,Country,Level,Elo,From,To\n"
    "1,Man United,ENG,1,1800,2026-05-01,2026-05-31\n"
    "2,Forest,ENG,1,1700,2026-05-01,2026-05-31\n"
    "3,Tottenham,ENG,1,1750,2026-05-01,2026-05-31\n"
    "4,Arsenal,ENG,1,1900,2026-05-01,2026-05-31\n"
    "5,Coventry,ENG,2,1500,2026-05-01,2026-05-31\n"
    "6,Real Madrid,ESP,1,2000,2026-05-01,2026-05-31\n"
)


def _handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=CLUBELO_CSV)


def _seed_teams(sm):
    with sm() as s:
        s.execute(teams.insert(), [
            {"id": 14, "name": "Man Utd", "short_name": "MUN"},
            {"id": 16, "name": "Nott'm Forest", "short_name": "NFO"},
            {"id": 18, "name": "Spurs", "short_name": "TOT"},
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
        ])
        s.commit()


def test_clubelo_maps_to_fpl_teams(sm):
    _seed_teams(sm)
    http = httpx.Client(transport=httpx.MockTransport(_handler))
    n = ClubEloIngestor(FetchClient(client=http, sm=sm), sm=sm).ingest()
    assert n == 5  # 5 ENG clubs (Real Madrid excluded by country filter)

    with sm() as s:
        mapping = {
            row.club: row.fpl_team_id
            for row in s.execute(select(team_elo.c.club, team_elo.c.fpl_team_id)).all()
        }
    assert mapping["Man United"] == 14  # alias -> Man Utd
    assert mapping["Forest"] == 16      # alias -> Nott'm Forest
    assert mapping["Tottenham"] == 18   # alias -> Spurs
    assert mapping["Arsenal"] == 1      # direct
    assert mapping["Coventry"] is None  # not a current FPL team -> unmapped
