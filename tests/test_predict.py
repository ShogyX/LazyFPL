"""Prediction service: frozen spec is applied correctly to features."""

from sqlalchemy import select

from fpl_engine.db.models import model_registry, predictions_player_gw, training_rows
from fpl_engine.model.predict import Predictor, _apply_cell


def test_apply_cell_linear_combo_with_shrinkage():
    cell = {
        "features": ["a", "b"], "coef": [2.0, -1.0], "intercept": 1.0,
        "impute_median": [0.0, 0.0], "scale_mean": [0.0, 0.0], "scale_std": [1.0, 1.0],
        "shrink_lambda": 0.0, "baseline_feature": "base",
    }
    # 1 + 2*3 - 1*1 = 6
    assert _apply_cell(cell, {"a": 3.0, "b": 1.0}) == 6.0
    # missing feature -> imputed median (0) -> 1 + 2*3 - 0 = 7
    assert _apply_cell(cell, {"a": 3.0}) == 7.0


def test_apply_cell_shrinkage_blend():
    cell = {
        "features": ["a"], "coef": [1.0], "intercept": 0.0,
        "impute_median": [0.0], "scale_mean": [0.0], "scale_std": [1.0],
        "shrink_lambda": 0.5, "baseline_feature": "base",
    }
    # model = 10; baseline = 4; blend 0.5 -> 7
    assert _apply_cell(cell, {"a": 10.0, "base": 4.0}) == 7.0


def _seed_spec(sm):
    def cell(pos, target, horizon):
        return {"position": pos, "target": target, "horizon": horizon,
                "features": ["f1"], "coef": [2.0], "intercept": 1.0,
                "impute_median": [0.0], "scale_mean": [0.0], "scale_std": [1.0],
                "shrink_lambda": 0.0, "baseline_feature": "b__career_mean"}
    spec = {"study_version": "vt", "cells": [
        cell(3, "points", "next1"), cell(3, "points", "next6"),
        cell(3, "minutes", "next1")]}
    with sm() as s:
        s.execute(model_registry.insert().values(
            version="vt", status="frozen", spec=spec, holdout_metrics={}))
        s.execute(training_rows.insert(), [{
            "season": "2025-26", "player_key": 100, "gw": 10, "element_id": 7,
            "element_type": 3, "hist_n": 5, "features": {"f1": 4.0},
            "feature_version": "t"}])
        s.commit()


def test_predictor_writes_predictions(sm):
    _seed_spec(sm)
    res = Predictor(sm=sm, version="vt").predict_gw("2025-26", 10)
    assert res.n_players == 1
    with sm() as s:
        row = s.execute(select(predictions_player_gw).where(
            predictions_player_gw.c.player_key == 100)).one()
    # 1 + 2*4 = 9 for each cell
    assert float(row.xp_next1) == 9.0
    assert float(row.xp_next6) == 9.0
    assert float(row.pred_minutes) == 9.0
    assert row.element_id == 7


def test_predictor_missing_cell_yields_none(sm):
    # spec with ONLY the points/next1 cell -> next6 and minutes are None.
    spec = {"study_version": "vt", "cells": [{
        "position": 3, "target": "points", "horizon": "next1",
        "features": ["f1"], "coef": [2.0], "intercept": 1.0,
        "impute_median": [0.0], "scale_mean": [0.0], "scale_std": [1.0],
        "shrink_lambda": 0.0, "baseline_feature": "b__career_mean"}]}
    with sm() as s:
        s.execute(model_registry.insert().values(
            version="vt2", status="frozen", spec=spec, holdout_metrics={}))
        s.execute(training_rows.insert(), [{
            "season": "2025-26", "player_key": 200, "gw": 11, "element_id": 8,
            "element_type": 3, "hist_n": 5, "features": {"f1": 4.0},
            "feature_version": "t"}])
        s.commit()

    Predictor(sm=sm, version="vt2").predict_gw("2025-26", 11)
    with sm() as s:
        row = s.execute(select(predictions_player_gw).where(
            predictions_player_gw.c.player_key == 200)).one()
    assert float(row.xp_next1) == 9.0
    assert row.xp_next6 is None        # no cell for this target/horizon
    assert row.pred_minutes is None
