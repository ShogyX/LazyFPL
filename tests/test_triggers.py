"""Continuous triggers: change detection drives recompute (mocked)."""

import httpx

from fpl_engine.ingest.fetch import FetchClient
from fpl_engine.orchestrator.triggers import TriggerEngine

# bootstrap with one player whose price moved (+1) this event, one static.
BOOTSTRAP_PRICE_MOVE = {"elements": [
    {"id": 1, "cost_change_event": 1, "status": "a", "news": "",
     "chance_of_playing_next_round": 100},
    {"id": 2, "cost_change_event": 0, "status": "a", "news": "",
     "chance_of_playing_next_round": 100},
], "teams": [], "events": []}

BOOTSTRAP_NO_MOVE = {"elements": [
    {"id": 1, "cost_change_event": 0, "status": "a", "news": "",
     "chance_of_playing_next_round": 100},
], "teams": [], "events": []}


class _Recorder:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


def _engine(sm, payload, *, status_payload=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/event-status/"):
            return httpx.Response(200, json=status_payload or {"status": []})
        return httpx.Response(200, json=payload)
    fetch = FetchClient(client=httpx.Client(transport=httpx.MockTransport(handler)), sm=sm)
    rec = _Recorder()
    return TriggerEngine(fetch, rec, sm=sm), rec


def test_price_watch_fires_on_movement(sm):
    eng, rec = _engine(sm, BOOTSTRAP_PRICE_MOVE)
    out = eng.price_watch()
    assert out.changed == 1 and out.recomputed is True
    assert rec.calls == 1


def test_price_watch_silent_when_static(sm):
    eng, rec = _engine(sm, BOOTSTRAP_NO_MOVE)
    out = eng.price_watch()
    assert out.changed == 0 and out.recomputed is False
    assert rec.calls == 0


def test_news_lineup_watch_fires_on_flip(sm):
    # First snapshot records all -> flips, recompute fires.
    eng, rec = _engine(sm, BOOTSTRAP_PRICE_MOVE)
    out = eng.news_lineup_watch()
    assert out.changed >= 1 and out.recomputed is True
    # Second identical poll -> no flips -> no recompute.
    eng2, rec2 = _engine(sm, BOOTSTRAP_PRICE_MOVE)
    out2 = eng2.news_lineup_watch()
    assert out2.changed == 0 and out2.recomputed is False
    assert rec2.calls == 0


def test_post_match_fires_when_bonus_confirmed(sm):
    eng, rec = _engine(sm, BOOTSTRAP_NO_MOVE,
                       status_payload={"status": [{"event": 20, "bonus_added": True}]})
    out = eng.post_match_recompute()
    assert out.changed == 1 and out.recomputed is True


def test_post_match_silent_before_bonus(sm):
    eng, rec = _engine(sm, BOOTSTRAP_NO_MOVE,
                       status_payload={"status": [{"event": 20, "bonus_added": False}]})
    out = eng.post_match_recompute()
    assert out.changed == 0 and out.recomputed is False
