"""Phase 4 integration: the study selects a true signal, rejects noise, beats
the naive baseline, and freezes a reloadable v1 spec. Uses synthetic
training_rows inserted directly (the study consumes the panel)."""

import numpy as np
from sqlalchemy import select

from fpl_engine.db.models import feature_importance, model_registry, training_rows
from fpl_engine.model.freeze import WeightFreezer, load_spec
from fpl_engine.model.study import PredictiveValidityStudy

SEASONS = ["2022-23", "2023-24", "2024-25", "2025-26"]


def _insert_panel(sm, n_per_season=90):
    rng = np.random.default_rng(7)
    rows = []
    for si, season in enumerate(SEASONS):
        for i in range(n_per_season):
            signal = float(rng.normal())
            noise = float(rng.normal())
            # target driven by signal; baseline (last GW) is a weak proxy
            y = 3.0 * signal + rng.normal(scale=0.5)
            last_gw = 0.3 * signal + rng.normal(scale=1.0)
            rows.append({
                "season": season, "player_key": si * 1000 + i, "gw": 5,
                "element_id": i, "element_type": 3, "hist_n": 10,
                "tgt_pts_next1": y, "tgt_pts_next6": None, "tgt_minutes_next1": None,
                "features": {
                    "signal__mean_5": signal,
                    "noise__mean_5": noise,
                    "total_points__mean_1": last_gw,
                    "total_points__career_mean": float(rng.normal(scale=0.2)),
                },
                "feature_version": "test",
            })
    with sm() as s:
        s.execute(training_rows.insert(), rows)
        s.commit()


def test_study_selects_signal_rejects_noise_beats_baseline(sm):
    _insert_panel(sm)
    study = PredictiveValidityStudy(sm=sm, study_version="vt")
    target_spec = [("points", "next1", "tgt_pts_next1", "total_points")]
    results = study.run(positions=(3,), targets=target_spec)

    assert len(results) == 1
    res = results[0]
    assert res.beats_baseline is True
    assert res.oos_spearman > 0.7   # strong signal recovered out of sample

    with sm() as s:
        fi = {r.feature: r for r in s.execute(
            select(feature_importance).where(
                feature_importance.c.study_version == "vt")).all()}

    assert fi["signal__mean_5"].selected is True
    assert float(fi["signal__mean_5"].mean_ic) > 0.5
    assert float(fi["signal__mean_5"].fdr_q) < 0.1
    assert abs(float(fi["signal__mean_5"].en_weight)) > 0
    # pure noise must not be selected
    assert fi["noise__mean_5"].selected is False


def test_freeze_writes_reloadable_v1_spec(sm):
    _insert_panel(sm)
    PredictiveValidityStudy(sm=sm, study_version="vt").run(
        positions=(3,), targets=[("points", "next1", "tgt_pts_next1", "total_points")])

    freezer = WeightFreezer(sm=sm, study_version="vt", registry_version="v1")
    cells = freezer.freeze(holdout_season="2025-26")

    assert len(cells) == 1
    cell = cells[0]
    assert cell.position == 3 and cell.target == "points"
    assert cell.n_features >= 1
    assert np.isfinite(cell.holdout_spearman)

    spec = load_spec("v1", sm=sm)
    assert spec is not None
    assert spec["study_version"] == "vt"
    assert len(spec["cells"]) == 1
    c = spec["cells"][0]
    # reloadable: weights + scaler + imputer params present
    assert len(c["coef"]) == len(c["features"])
    assert len(c["scale_mean"]) == len(c["features"])
    assert "signal__mean_5" in c["features"]

    with sm() as s:
        reg = s.execute(select(model_registry).where(
            model_registry.c.version == "v1")).one()
    assert reg.status == "frozen"
    assert reg.holdout_metrics["n_cells"] == 1


def _insert_custom(sm, feature_fn, n_per_season=90):
    rng = np.random.default_rng(11)
    rows = []
    for si, season in enumerate(SEASONS):
        for i in range(n_per_season):
            signal = float(rng.normal())
            y = 3.0 * signal + float(rng.normal(scale=0.5))
            feats = feature_fn(season, signal, y, rng)
            rows.append({
                "season": season, "player_key": si * 1000 + i, "gw": 5,
                "element_id": i, "element_type": 3, "hist_n": 10,
                "tgt_pts_next1": y, "tgt_pts_next6": None, "tgt_minutes_next1": None,
                "features": feats, "feature_version": "test",
            })
    with sm() as s:
        s.execute(training_rows.insert(), rows)
        s.commit()


def test_freeze_screens_train_only_and_excludes_holdout_leak(sm):
    # 'leak__mean_5' equals the target ONLY in the holdout season; a train-only
    # screen must not select it (it is pure noise in the training seasons).
    def feats(season, signal, y, rng):
        leak = y if season == "2025-26" else float(rng.normal())
        return {
            "signal__mean_5": signal,
            "leak__mean_5": leak,
            "total_points__mean_1": 0.3 * signal + float(rng.normal()),
            "total_points__career_mean": float(rng.normal(scale=0.2)),
        }
    _insert_custom(sm, feats)

    WeightFreezer(sm=sm, study_version="vt", registry_version="v1").freeze(
        holdout_season="2025-26")
    spec = load_spec("v1", sm=sm)
    cell = spec["cells"][0]
    assert "signal__mean_5" in cell["features"]
    assert "leak__mean_5" not in cell["features"]  # holdout-only signal not leaked


def test_selection_is_lean_collapsing_collinear_windows(sm):
    # 7 collinear windows of one metric must collapse to <= MAX_PER_METRIC.
    from fpl_engine.model.study import MAX_PER_METRIC, MAX_SELECTED

    def feats(season, signal, y, rng):
        d = {f"signal__mean_{w}": signal + float(rng.normal(scale=0.05))
             for w in (1, 3, 5, 8, 12, 19, 38)}
        d["noise__mean_5"] = float(rng.normal())
        d["total_points__mean_1"] = 0.3 * signal + float(rng.normal())
        d["total_points__career_mean"] = float(rng.normal(scale=0.2))
        return d
    _insert_custom(sm, feats)

    PredictiveValidityStudy(sm=sm, study_version="vt").run(
        positions=(3,), targets=[("points", "next1", "tgt_pts_next1", "total_points")])

    with sm() as s:
        sel = [r.feature for r in s.execute(
            select(feature_importance.c.feature).where(
                feature_importance.c.study_version == "vt",
                feature_importance.c.selected.is_(True))).all()]
    signal_sel = [f for f in sel if f.startswith("signal__")]
    assert len(signal_sel) <= MAX_PER_METRIC      # collinear windows collapsed
    assert len(sel) <= MAX_SELECTED               # overall lean
    assert "noise__mean_5" not in sel
