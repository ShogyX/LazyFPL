"""FPL availability snapshots: change-detection / flip timestamping (mocked)."""

import httpx
from sqlalchemy import select

from fpl_engine.db.models import player_availability
from fpl_engine.ingest.availability import AvailabilityIngestor
from fpl_engine.ingest.fetch import FetchClient


def _bootstrap(elements):
    return {"elements": elements, "teams": [], "events": []}


# Two players; player 1 fit, player 2 doubtful.
STATE_A = [
    {"id": 1, "status": "a", "news": "", "news_added": None,
     "chance_of_playing_this_round": 100, "chance_of_playing_next_round": 100},
    {"id": 2, "status": "d", "news": "Knock - 75% chance", "news_added": "2026-05-01T09:00:00Z",
     "chance_of_playing_this_round": 75, "chance_of_playing_next_round": 75},
]
# Player 2 flips to injured; player 1 unchanged.
STATE_B = [
    {"id": 1, "status": "a", "news": "", "news_added": None,
     "chance_of_playing_this_round": 100, "chance_of_playing_next_round": 100},
    {"id": 2, "status": "i", "news": "Hamstring - expected back GW38",
     "news_added": "2026-05-08T09:00:00Z",
     "chance_of_playing_this_round": 0, "chance_of_playing_next_round": 0},
]


def _client(state):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_bootstrap(state))
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_first_snapshot_records_all(sm):
    ing = AvailabilityIngestor(FetchClient(client=_client(STATE_A), sm=sm), sm=sm)
    res = ing.snapshot_from_bootstrap()
    assert res.scanned == 2 and res.flips == 2
    with sm() as s:
        n = len(s.execute(select(player_availability)).all())
    assert n == 2


def test_unchanged_state_writes_nothing(sm):
    ing = AvailabilityIngestor(FetchClient(client=_client(STATE_A), sm=sm), sm=sm)
    ing.snapshot_from_bootstrap()
    res2 = ing.snapshot_from_bootstrap()       # identical bootstrap
    assert res2.flips == 0
    with sm() as s:
        n = len(s.execute(select(player_availability)).all())
    assert n == 2                              # no duplicate rows


def test_flip_detected_and_timestamped(sm):
    AvailabilityIngestor(FetchClient(client=_client(STATE_A), sm=sm), sm=sm) \
        .snapshot_from_bootstrap()
    res = AvailabilityIngestor(FetchClient(client=_client(STATE_B), sm=sm), sm=sm) \
        .snapshot_from_bootstrap()
    assert res.flips == 1                       # only player 2 changed

    with sm() as s:
        rows = s.execute(
            select(player_availability.c.status, player_availability.c.captured_at)
            .where(player_availability.c.element_id == 2)
            .order_by(player_availability.c.captured_at)
        ).all()
    assert [r.status for r in rows] == ["d", "i"]   # both states retained, ordered
    assert rows[0].captured_at < rows[1].captured_at
