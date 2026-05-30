"""Freeze an ensemble as v2 (reloadable spec) and serve it as predictions."""

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fpl_engine.db.models import (
    model_registry,
    players,
    player_match_stats,
    predictions_player_gw,
    training_rows,
)
from fpl_engine.model.freeze import freeze_ensemble, load_spec
from fpl_engine.model.predict import EnsembleServer, prediction_server
from fpl_engine.model.predictors import (
    FeaturePredictor,
    PerPositionZBlend,
    RankBlend,
    ZBlend,
    ensemble_to_spec,
    predictor_from_spec,
)

GK, DEF, MID, FWD = 1, 2, 3, 4


# --- spec round-trip (pure) ---
def _items():
    return [(1, {"a": 5.0, "b": 1.0}, MID), (2, {"a": 1.0, "b": 9.0}, MID),
            (3, {"a": 3.0, "b": 3.0}, FWD)]


def test_rank_blend_spec_roundtrip():
    ens = RankBlend("r", [(FeaturePredictor("A", "a"), 1.0),
                          (FeaturePredictor("B", "b"), 2.0)])
    back = predictor_from_spec(ensemble_to_spec("r", ens))
    assert isinstance(back, RankBlend)
    assert back.score_frame(_items()) == ens.score_frame(_items())


def test_z_blend_spec_roundtrip():
    ens = ZBlend("z", [(FeaturePredictor("A", "a"), 1.0)], clip=1.5)
    spec = ensemble_to_spec("z", ens)
    assert spec["clip"] == 1.5
    back = predictor_from_spec(spec)
    assert back.score_frame(_items()) == ens.score_frame(_items())


def test_per_position_spec_roundtrip():
    ens = PerPositionZBlend("pp", {MID: [(FeaturePredictor("A", "a"), 1.0)],
                                   FWD: [(FeaturePredictor("B", "b"), 1.0)]})
    back = predictor_from_spec(ensemble_to_spec("pp", ens))
    assert isinstance(back, PerPositionZBlend)
    assert back.score_frame(_items()) == ens.score_frame(_items())


# --- freeze + serve (DB) ---
TRAIN, EVAL = "2023-24", "2024-25"


def _seed_season(sm, season, gws):
    rng = np.random.default_rng(0)
    players_rows, pms_rows, tr_rows = [], [], []
    pid = 0
    for pos, n in ((GK, 4), (DEF, 10), (MID, 10), (FWD, 6)):
        for _ in range(n):
            pid += 1
            skill = float(pid % 9) + 1.0
            players_rows.append({"id": pid, "element_type": pos, "team_id": (pid % 6) + 1,
                                 "now_cost": 50, "status": "a", "web_name": f"P{pid}",
                                 "selected_by_percent": 5.0})
            for gw in gws:
                feats = {"total_points__mean_1": skill, "total_points__mean_3": skill,
                         "total_points__mean_5": skill, "total_points__ewma_hl5": skill,
                         "total_points__mean_38": skill * 0.9,
                         "total_points__career_mean": skill * 0.8,
                         "ict_index__ewma_hl5": skill * 0.7, "xgi90": skill * 0.3}
                tr_rows.append({"season": season, "player_key": pid, "gw": gw,
                                "element_id": pid, "element_type": pos, "hist_n": 5,
                                "features": feats, "feature_version": "t"})
                pms_rows.append({"season": season, "element_id": pid,
                                 "fixture_id": gw * 1000 + pid, "gw": gw, "player_key": pid,
                                 "element_type": pos, "value": 50, "minutes": 90,
                                 "total_points": int(skill + rng.normal(scale=0.3))})
    with sm() as s:
        # players are shared across seasons -> idempotent insert
        s.execute(pg_insert(players).on_conflict_do_nothing(index_elements=["id"]),
                  players_rows)
        s.execute(player_match_stats.insert(), pms_rows)
        s.execute(training_rows.insert(), tr_rows)
        s.commit()


def test_freeze_v2_writes_reloadable_spec(sm):
    _seed_season(sm, TRAIN, [1, 2, 3, 4, 5])
    out = freeze_ensemble(registry_version="v2", train_season=TRAIN, choice="rank_top3",
                          sm=sm)
    assert out["version"] == "v2"

    spec = load_spec("v2", sm=sm)
    assert spec is not None
    assert spec["type"] == "ensemble" and spec["ensemble"] == "rank_blend"
    assert spec["train_season"] == TRAIN
    assert len(spec["parts"]) >= 1
    # reconstructable
    pred = predictor_from_spec(spec)
    assert isinstance(pred, RankBlend)

    with sm() as s:
        reg = s.execute(select(model_registry).where(
            model_registry.c.version == "v2")).one()
    assert reg.status == "frozen"


def test_ensemble_server_serves_v2_predictions(sm):
    _seed_season(sm, TRAIN, [1, 2, 3, 4, 5])
    freeze_ensemble(registry_version="v2", train_season=TRAIN, choice="rank_top3", sm=sm)
    _seed_season(sm, EVAL, [10])

    server = prediction_server(version="v2", sm=sm)
    assert isinstance(server, EnsembleServer)
    res = server.predict_gw(EVAL, 10)
    assert res.n_players == 30

    with sm() as s:
        n = s.execute(select(func.count()).select_from(predictions_player_gw).where(
            predictions_player_gw.c.model_version == "v2",
            predictions_player_gw.c.season == EVAL)).scalar_one()
        sample = s.execute(select(predictions_player_gw).where(
            predictions_player_gw.c.model_version == "v2").limit(1)).one()
    assert n == 30
    assert sample.xp_next1 is not None
