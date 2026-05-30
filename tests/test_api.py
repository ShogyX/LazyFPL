"""Read API (FastAPI) — endpoints over seeded serving data."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from fpl_engine.api.app import create_app
from fpl_engine.db.models import (
    backtest_runs,
    player_match_stats,
    players,
    predictions_player_gw,
    recommendations,
    targets,
    teams,
    tracked_entries,
    tracked_picks,
    true_probabilities,
)

GK, DEF, MID, FWD = 1, 2, 3, 4
SEASON, GW = "2025-26", 20


@pytest.fixture
def client(sm):
    _seed(sm)
    return TestClient(create_app())


def _seed(sm):
    players_rows, pred_rows, target_rows = [], [], []
    pid = 0
    for pos, n in ((GK, 4), (DEF, 10), (MID, 10), (FWD, 6)):
        for _ in range(n):
            pid += 1
            players_rows.append({"id": pid, "element_type": pos, "team_id": (pid % 6) + 1,
                                 "now_cost": 50, "status": "a", "web_name": f"P{pid}",
                                 "selected_by_percent": float(pid)})
            pred_rows.append({"model_version": "v1", "season": SEASON, "gw": GW,
                              "player_key": pid, "element_id": pid, "element_type": pos,
                              "xp_next1": float(pid % 7) + 1.0, "xp_next6": 20.0,
                              "pred_minutes": 90.0})
            # Realised points correlated with predicted xP so accuracy IC is high.
            target_rows.append({"season": SEASON, "element_id": pid, "fixture_id": pid,
                                "player_key": pid, "gw": GW, "element_type": pos,
                                "actual_points": (pid % 7) + 2, "converter_version": "t1"})
    with sm() as s:
        s.execute(teams.insert(), [{"id": i, "name": f"Team{i}", "short_name": f"T{i}"}
                                   for i in range(1, 8)])
        s.execute(players.insert(), players_rows)
        s.execute(predictions_player_gw.insert(), pred_rows)
        s.execute(targets.insert(), target_rows)
        s.execute(recommendations.insert(), [{
            "model_version": "v1", "entry_id": 7, "season": SEASON, "target_event": GW,
            "kind": "captain", "ev": 3.2, "confidence": 0.4,
            "rationale": {"captain": {"name": "P10"}}}])
        s.execute(backtest_runs.insert(), [{
            "model_version": "v1", "season": SEASON, "strategy": "model",
            "start_gw": 1, "end_gw": 10, "total_points": 500, "total_hits": 8,
            "net_points": 492, "per_gw": []}])
        s.execute(true_probabilities.insert(), [{
            "event_ref": "evtX", "market": "1x2", "selection": sel,
            "captured_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "true_prob": prob, "n_sources": 3, "sharp_present": True,
            "method": "weighted"} for sel, prob in
            (("Home", 0.5), ("Draw", 0.3), ("Away", 0.2))])
        s.execute(player_match_stats.insert(), [{
            "season": SEASON, "element_id": 1, "fixture_id": 100, "gw": 5,
            "element_type": GK, "value": 50, "minutes": 90, "total_points": 6}])
        s.execute(tracked_entries.insert(), [{
            "entry_id": 42, "player_name": "Boss", "current_event": GW,
            "bank": 5, "team_value": 1005, "total_points": 1234, "overall_rank": 9000}])
        s.execute(tracked_picks.insert(), [{
            "entry_id": 42, "event": GW, "element_id": 10, "slot": 1,
            "multiplier": 2, "is_captain": True, "is_vice": False}])
        s.commit()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_predictions_sorted_desc(client):
    r = client.get(f"/predictions?season={SEASON}&gw={GW}&limit=5").json()
    assert r["gw"] == GW
    xps = [p["xp_next1"] for p in r["players"]]
    assert xps == sorted(xps, reverse=True)
    assert r["players"][0]["position"] in ("GK", "DEF", "MID", "FWD")


def test_predictions_position_filter(client):
    r = client.get(f"/predictions?season={SEASON}&gw={GW}&position=4").json()
    assert all(p["position"] == "FWD" for p in r["players"])


def test_squad_endpoint_returns_valid_xi(client):
    r = client.get(f"/squad?season={SEASON}&gw={GW}").json()
    assert r["status"] == "Optimal"
    assert r["total_cost"] <= 100.0
    starters = [p for p in r["picks"] if p["start"]]
    assert len(starters) == 11
    assert sum(1 for p in r["picks"] if p["captain"]) == 1


def test_recommendations_endpoint(client):
    r = client.get("/recommendations?entry=7").json()
    assert len(r["recommendations"]) == 1
    assert r["recommendations"][0]["kind"] == "captain"


def test_backtests_endpoint(client):
    r = client.get(f"/backtests?season={SEASON}").json()
    assert r["backtests"][0]["net_points"] == 492


def test_odds_consensus_endpoint(client):
    r = client.get("/odds/consensus?event=evtX&market=1x2").json()
    assert r["n_sources"] == 3 and r["sharp_present"] is True
    assert abs(sum(r["probabilities"].values()) - 1.0) < 1e-6


def test_player_history_endpoint(client):
    r = client.get(f"/players/1/history?season={SEASON}").json()
    assert r["history"][0]["points"] == 6


def test_squad_404_when_no_predictions(client):
    assert client.get("/squad?season=1999-00&gw=1").status_code == 404


def test_empty_results_do_not_500(client):
    assert client.get(f"/predictions?season={SEASON}&gw=99").json()["players"] == []
    assert client.get("/recommendations?entry=99999").json()["recommendations"] == []
    assert client.get("/backtests?season=1999-00").json()["backtests"] == []


def test_odds_consensus_404_for_unknown_event(client):
    assert client.get("/odds/consensus?event=nope&market=1x2").status_code == 404


def test_limit_bounds_enforced(client):
    assert client.get(f"/predictions?season={SEASON}&gw={GW}&limit=0").status_code == 422
    assert client.get(f"/predictions?season={SEASON}&gw={GW}&limit=99999").status_code == 422


def test_invalid_path_param_422(client):
    assert client.get("/players/abc/history?season=2025-26").status_code == 422


def test_squad_budget_bounds_enforced(client):
    assert client.get(f"/squad?season={SEASON}&gw={GW}&budget=10").status_code == 422


def test_recommendation_rationale_round_trips(client):
    r = client.get("/recommendations?entry=7").json()["recommendations"][0]
    assert r["rationale"]["captain"]["name"] == "P10"


# ---- F1: settings / models / search / tracking ----------------------------

def test_settings_general_round_trip(client):
    base = client.get("/settings").json()
    assert base["general"]["horizon"] == 6  # default
    client.put("/settings", json={"horizon": 9, "theme": "dark", "junk": 1})
    after = client.get("/settings").json()["general"]
    assert after["horizon"] == 9 and after["theme"] == "dark"
    assert "junk" not in after  # unknown keys rejected


def test_settings_secrets_masked_and_never_plaintext(client):
    r = client.put("/settings/secrets", json={"api_football_key": "SECRET123"}).json()
    assert r["secrets"]["api_football_key"] is True
    # The presence map must not echo the plaintext anywhere.
    assert "SECRET123" not in client.get("/settings").text
    cleared = client.put("/settings/secrets", json={"api_football_key": None}).json()
    assert cleared["secrets"]["api_football_key"] is False


def test_models_lists_versions_and_strategies(client):
    r = client.get("/models").json()
    assert "v1" in r["versions"]
    assert "model" in r["strategies"]
    assert r["active_model"] == "v1"


def test_models_compare_keeps_latest_per_strategy(client):
    r = client.get("/models/compare", params={"season": SEASON}).json()
    assert len(r["runs"]) == 1
    assert r["runs"][0]["strategy"] == "model"
    assert r["runs"][0]["net_points"] == 492


def test_player_search_returns_predictions(client):
    r = client.get("/players/search", params={"q": "P10"}).json()
    hit = next(p for p in r["players"] if p["name"] == "P10")
    assert hit["team"] is not None
    assert "v1" in hit["predictions"]


def test_track_list_and_get(client):
    lst = client.get("/track").json()["entries"]
    assert any(e["entry_id"] == 42 for e in lst)
    one = client.get("/track/42").json()
    assert one["name"] == "Boss"
    assert one["picks"][0]["captain"] is True


def test_track_get_404_for_unknown(client):
    assert client.get("/track/99999").status_code == 404


# ---- F4+: predicted-vs-actual analytics ----------------------------------

def test_accuracy_overall_and_breakdowns(client):
    r = client.get(f"/accuracy?season={SEASON}&version=v1").json()
    assert r["overall"]["n"] == 30 and r["overall"]["n_gws"] == 1
    assert r["overall"]["ic"] is not None  # predicted & actual are correlated
    assert {p["position"] for p in r["per_position"]} <= {"GK", "DEF", "MID", "FWD"}
    assert len(r["calibration"]) >= 1


def test_accuracy_empty_when_no_predictions(client):
    r = client.get("/accuracy?season=1999-00&version=v1").json()
    assert r["overall"] is None and r["per_gw"] == []


def test_optimal_xi_history(client):
    r = client.get(f"/optimal-xi?season={SEASON}&version=v1").json()
    assert r["totals"]["n_gws"] == 1
    g = r["gws"][0]
    assert g["gw"] == GW
    assert g["predicted_xi_xp"] > 0 and g["actual_points"] > 0
    assert g["captain"] is not None
