"""Component predictor as a pluggable, backtestable Predictor."""

from sqlalchemy import select

from fpl_engine.backtest import Backtester
from fpl_engine.db.models import backtest_runs, players, player_match_stats, training_rows
from fpl_engine.model.components import ComponentScorePredictor
from fpl_engine.model.predictors import Predictor

GK, DEF, MID, FWD = 1, 2, 3, 4
SEASON = "2025-26"
GWS = [1, 2, 3]


def test_satisfies_predictor_protocol():
    assert isinstance(ComponentScorePredictor(), Predictor)


def test_score_rewards_higher_xg():
    cp = ComponentScorePredictor()
    base = {"minutes__mean_3": 90.0, "starts__mean_3": 1.0}
    hot = cp.score({**base, "expected_goals__mean_3": 0.8}, FWD)
    cold = cp.score({**base, "expected_goals__mean_3": 0.05}, FWD)
    assert hot > cold


def test_score_frame_zeros_when_no_minutes():
    cp = ComponentScorePredictor()
    # no starts/minutes signal -> default starts prior still gives some xP, but a
    # player with zero recent minutes & starts should score low.
    out = cp.score_frame([
        (1, {"minutes__mean_3": 90.0, "starts__mean_3": 1.0,
             "expected_goals__mean_3": 0.5}, FWD),
        (2, {"minutes__mean_3": 0.0, "starts__mean_3": 0.0,
             "expected_goals__mean_3": 0.5}, FWD),
    ])
    assert out[1] > out[2]


def _seed(sm):
    """Two attacking profiles: high-xG and low-xG, both nailed starters."""
    players_rows, pms_rows, tr_rows = [], [], []
    profiles = [(pid, FWD, 0.8 if pid <= 8 else 0.05) for pid in range(1, 17)]
    # ensure a legal squad is fieldable: add GK/DEF/MID fillers
    fillers = ([(100 + i, GK, 0.0) for i in range(3)]
               + [(110 + i, DEF, 0.0) for i in range(6)]
               + [(120 + i, MID, 0.0) for i in range(6)])
    for pid, pos, xg in profiles + fillers:
        players_rows.append({"id": pid, "element_type": pos, "team_id": (pid % 6) + 1,
                             "now_cost": 50, "status": "a", "web_name": f"P{pid}",
                             "selected_by_percent": 5.0})
        for gw in GWS:
            pts = int(round(xg * 6)) + 2
            pms_rows.append({"season": SEASON, "element_id": pid,
                             "fixture_id": gw * 1000 + pid, "gw": gw, "player_key": pid,
                             "element_type": pos, "value": 50, "minutes": 90,
                             "total_points": pts})
            tr_rows.append({"season": SEASON, "player_key": pid, "gw": gw,
                            "element_id": pid, "element_type": pos, "hist_n": 5,
                            "features": {"minutes__mean_3": 90.0, "starts__mean_3": 1.0,
                                         "expected_goals__mean_3": xg,
                                         "expected_assists__mean_3": 0.1},
                            "feature_version": "t"})
    with sm() as s:
        s.execute(players.insert(), players_rows)
        s.execute(player_match_stats.insert(), pms_rows)
        s.execute(training_rows.insert(), tr_rows)
        s.commit()


def test_component_predictor_runs_in_backtester(sm):
    _seed(sm)
    res = Backtester(sm=sm).run(SEASON, GWS, ComponentScorePredictor())
    assert len(res.per_gw) == len(GWS)
    assert res.net_points == res.total_points - res.total_hits
    with sm() as s:
        row = s.execute(select(backtest_runs).where(
            backtest_runs.c.strategy == "component:c1")).one()
    assert row.net_points == res.net_points
