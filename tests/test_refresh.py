"""Hands-off refresh helpers: current-GW selection + servable-GW fallback."""

from types import SimpleNamespace

from fpl_engine.cli import _current_gw, _servable_gw
from fpl_engine.db.models import training_rows

SEASON = "2025-26"


class _FakeFetch:
    def __init__(self, events):
        self._events = events

    def get(self, provider, path, cache_ttl=0.0):
        return SimpleNamespace(payload={"events": self._events})


def test_current_gw_picks_next_unfinished():
    fetch = _FakeFetch([
        {"id": 1, "finished": True},
        {"id": 2, "finished": True},
        {"id": 3, "finished": False},
        {"id": 4, "finished": False},
    ])
    assert _current_gw(fetch) == 3


def test_current_gw_falls_back_to_last_finished():
    fetch = _FakeFetch([{"id": 1, "finished": True}, {"id": 2, "finished": True}])
    assert _current_gw(fetch) == 2


def test_current_gw_none_preseason():
    assert _current_gw(_FakeFetch([])) is None


def test_servable_gw_prefers_requested_when_panel_exists(sm):
    with sm() as s:
        s.execute(training_rows.insert(), [
            _row(gw) for gw in (10, 11, 12)
        ])
        s.commit()
    assert _servable_gw(SEASON, 11) == 11


def test_servable_gw_falls_back_to_latest_built(sm):
    with sm() as s:
        s.execute(training_rows.insert(), [_row(gw) for gw in (10, 11, 12)])
        s.commit()
    # GW 38 has no panel rows -> fall back to the latest that does (12).
    assert _servable_gw(SEASON, 38) == 12


def test_servable_gw_none_when_no_rows(sm):
    assert _servable_gw(SEASON, 5) is None


def _row(gw: int) -> dict:
    return {"season": SEASON, "player_key": 1000 + gw, "gw": gw, "element_id": gw,
            "element_type": 3, "hist_n": 5, "features": {"x": 1.0},
            "feature_version": "p1.1"}
