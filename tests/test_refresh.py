"""Hands-off refresh helpers: current-GW selection + servable-GW fallback."""

from types import SimpleNamespace

from fpl_engine.cli import _current_gw, _servable_gws
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


def test_servable_gws_filters_to_built_panels(sm):
    with sm() as s:
        s.execute(training_rows.insert(), [_row(gw) for gw in (10, 11, 12)])
        s.commit()
    # Of the requested range, only those with panel rows are returned.
    assert _servable_gws(SEASON, [10, 11, 12, 13, 14]) == [10, 11, 12]


def test_servable_gws_falls_back_to_latest_built(sm):
    with sm() as s:
        s.execute(training_rows.insert(), [_row(gw) for gw in (10, 11, 12)])
        s.commit()
    # None of the requested GWs have rows -> fall back to the latest that does.
    assert _servable_gws(SEASON, [38, 39, 40]) == [12]


def test_servable_gws_none_when_no_rows(sm):
    assert _servable_gws(SEASON, [5, 6]) == []


def _row(gw: int) -> dict:
    return {"season": SEASON, "player_key": 1000 + gw, "gw": gw, "element_id": gw,
            "element_type": 3, "hist_n": 5, "features": {"x": 1.0},
            "feature_version": "p1.1"}
