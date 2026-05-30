"""Shrinkage calibration + holdout validation + freeze v1 (plan 4.2).

The final season is held out untouched. For each (position, target, horizon)
cell we re-fit the Elastic-Net pipeline on the *training* seasons only, choose a
shrinkage strength by blending the model toward the stable season-average
baseline (tuned by inner leave-one-season-out CV on the training seasons), then
report metrics on the untouched holdout and freeze a reloadable spec into
``study.model_registry``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import feature_importance, model_registry, training_rows
from ..logging_setup import get_logger
from .stats import rmse, spearman_ic
from .study import MIN_HISTORY, TARGET_SPECS, PredictiveValidityStudy

log = get_logger(__name__)

SHRINK_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
_BASE_METRIC = {t: base for (t, _h, _c, base) in TARGET_SPECS}
_TARGET_COL = {(t, h): c for (t, h, c, _b) in TARGET_SPECS}


@dataclass
class CellFreeze:
    position: int
    target: str
    horizon: str
    n_train: int
    n_holdout: int
    holdout_spearman: float
    holdout_rmse: float
    shrink_lambda: float
    n_features: int


class WeightFreezer:
    def __init__(self, sm: sessionmaker[Session] | None = None,
                 study_version: str = "v1-dev", registry_version: str = "v1"):
        self._sm = sm or get_sessionmaker()
        self.study_version = study_version
        self.registry_version = registry_version

    def _selected(self, position: int, target: str, horizon: str) -> list[str]:
        fi = feature_importance.c
        with self._sm() as s:
            rows = s.execute(
                select(fi.feature).where(
                    fi.study_version == self.study_version, fi.position == position,
                    fi.target == target, fi.horizon == horizon, fi.selected.is_(True),
                )
            ).all()
        return [r[0] for r in rows]

    def _load(self, position: int, target_col: str) -> pd.DataFrame:
        tr = training_rows.c
        with self._sm() as s:
            rows = s.execute(
                select(tr.season, tr.features, tr[target_col]).where(
                    tr.element_type == position, tr.hist_n >= MIN_HISTORY,
                    tr[target_col].isnot(None))
            ).all()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([r.features for r in rows]).apply(pd.to_numeric, errors="coerce")
        df["__season"] = [r.season for r in rows]
        df["__y"] = [float(r[2]) for r in rows]
        return df

    def _blend(self, model_pred, base_pred, lam: float):
        base = np.where(np.isfinite(base_pred), base_pred, np.nanmean(model_pred))
        return (1 - lam) * model_pred + lam * base

    def freeze(self, holdout_season: str | None = None,
               positions: Iterable[int] = (1, 2, 3, 4)) -> list[CellFreeze]:
        study = PredictiveValidityStudy(self._sm, self.study_version)
        cells: list[CellFreeze] = []
        spec_cells: list[dict] = []

        for position in positions:
            for target, horizon, target_col, base_metric in TARGET_SPECS:
                df = self._load(position, target_col)
                if df.empty:
                    continue
                seasons = sorted(df["__season"].unique())
                hold = holdout_season or seasons[-1]
                if hold not in seasons or len(seasons) < 2:
                    continue
                train = df[df["__season"] != hold]
                test = df[df["__season"] == hold]
                if len(train) < 50 or test.empty:
                    continue

                # Re-screen on TRAIN seasons only so the holdout stays untouched
                # (the study's all-season selection must not leak into holdout).
                feat_cols = [c for c in train.columns if not c.startswith("__")]
                _summ, _q, selected = study._screen(train, position, feat_cols)
                # Drop zero-information columns (all-NaN or constant in train):
                # their imputer median / scaler params would be NaN and a frozen
                # spec must be finite to serialise and to serve from.
                cols = [c for c in selected if self._informative(train, c)]
                if not cols:
                    cols = [c for c in self._fallback_cols(df) if self._informative(train, c)]
                if not cols:
                    continue

                base_col = f"{base_metric}__career_mean"
                lam = self._tune_lambda(study, train, cols, base_col)

                pipe = study._pipeline()
                pipe.fit(train[cols].to_numpy(), train["__y"].to_numpy())
                model_pred = pipe.predict(test[cols].to_numpy())
                base_pred = (test[base_col].to_numpy() if base_col in test
                             else np.full(len(test), np.nan))
                pred = self._blend(model_pred, base_pred, lam)
                y = test["__y"].to_numpy()
                sp, _ = spearman_ic(pred, y)
                rm = rmse(y, pred)

                en = pipe.named_steps["en"]
                spec_cells.append({
                    "position": position, "target": target, "horizon": horizon,
                    "features": cols,
                    "coef": [float(c) for c in en.coef_],
                    "intercept": float(en.intercept_),
                    "impute_median": [float(v) for v in pipe.named_steps["impute"].statistics_],
                    "scale_mean": [float(v) for v in pipe.named_steps["scale"].mean_],
                    "scale_std": [float(v) for v in pipe.named_steps["scale"].scale_],
                    "shrink_lambda": lam, "baseline_feature": base_col,
                    "holdout_spearman": _f(sp), "holdout_rmse": _f(rm),
                })
                cells.append(CellFreeze(position, target, horizon, len(train), len(test),
                                        float(sp) if np.isfinite(sp) else float("nan"),
                                        float(rm) if np.isfinite(rm) else float("nan"),
                                        lam, len(cols)))
                log.info("freeze cell", extra={"position": position, "target": target,
                                               "horizon": horizon, "holdout_spearman": _f(sp),
                                               "shrink_lambda": lam})

        self._write_registry(spec_cells, holdout_season=holdout_season)
        return cells

    def _fallback_cols(self, df: pd.DataFrame) -> list[str]:
        return [c for c in df.columns
                if c.startswith(("total_points__", "minutes__")) and not c.startswith("__")][:10]

    @staticmethod
    def _informative(train: pd.DataFrame, col: str) -> bool:
        if col not in train.columns:
            return False
        s = train[col]
        if not s.notna().any():
            return False
        std = s.std(skipna=True)
        return bool(np.isfinite(std) and std > 0)

    def _tune_lambda(self, study, train: pd.DataFrame, cols: list[str], base_col: str) -> float:
        """Pick shrink lambda by inner LOSO on the training seasons."""
        seasons = sorted(train["__season"].unique())
        if len(seasons) < 2:
            return 0.0
        # gather inner OOS model preds once per fold, then score each lambda
        fold_data = []
        for hold in seasons:
            tr_in = train[train["__season"] != hold]
            te_in = train[train["__season"] == hold]
            if len(tr_in) < 50 or te_in.empty:
                continue
            pipe = study._pipeline()
            try:
                pipe.fit(tr_in[cols].to_numpy(), tr_in["__y"].to_numpy())
                mp = pipe.predict(te_in[cols].to_numpy())
            except Exception:  # pragma: no cover
                continue
            bp = te_in[base_col].to_numpy() if base_col in te_in else np.full(len(te_in), np.nan)
            fold_data.append((te_in["__y"].to_numpy(), mp, bp))
        if not fold_data:
            return 0.0
        # tune on the reported/gated metric (Spearman), not RMSE
        best_lam, best_score = 0.0, -np.inf
        for lam in SHRINK_GRID:
            ys, preds = [], []
            for y, mp, bp in fold_data:
                ys.append(y)
                preds.append(self._blend(mp, bp, lam))
            sp, _ = spearman_ic(np.concatenate(preds), np.concatenate(ys))
            if np.isfinite(sp) and sp > best_score:
                best_score, best_lam = sp, lam
        return best_lam

    def _write_registry(self, spec_cells: list[dict], holdout_season: str | None) -> None:
        valid = [c["holdout_spearman"] for c in spec_cells if c["holdout_spearman"] is not None]
        holdout_metrics = {
            "n_cells": len(spec_cells),
            "mean_holdout_spearman": round(float(np.mean(valid)), 4) if valid else None,
            "holdout_season": holdout_season or "last",
        }
        spec = _sanitize({"study_version": self.study_version, "cells": spec_cells})
        holdout_metrics = _sanitize(holdout_metrics)
        with self._sm() as s:
            # archive any previous frozen row of this version, then upsert.
            stmt = insert(model_registry).values(
                version=self.registry_version, status="frozen",
                spec=spec, holdout_metrics=holdout_metrics,
                notes=f"frozen from study {self.study_version}")
            s.execute(stmt.on_conflict_do_update(
                index_elements=["version"],
                set_={"status": "frozen", "spec": spec,
                      "holdout_metrics": holdout_metrics}))
            s.commit()
        log.info("v1 frozen", extra=holdout_metrics)

    def rollback_to(self, version: str) -> None:
        """Mark a registry version active (rollback support)."""
        with self._sm() as s:
            s.execute(model_registry.update()
                      .where(model_registry.c.version == version)
                      .values(status="active"))
            s.commit()


def freeze_ensemble(registry_version: str = "v2", train_season: str = "2024-25",
                    choice: str = "rank_top3", eval_season: str | None = None,
                    eval_gws: list[int] | None = None,
                    sm: sessionmaker[Session] | None = None) -> dict:
    """Freeze an ensemble (trained on ``train_season``) as a reloadable model.

    Weights/selection come only from the train season (causal). Optionally
    records a holdout backtest on a disjoint eval season for provenance.
    """
    from .analysis import PredictorAnalysis
    from .predictors import build_ensembles, default_predictors, ensemble_to_spec

    sm = sm or get_sessionmaker()
    base = default_predictors()
    rep = PredictorAnalysis(sm).analyse(train_season, list(range(1, 39)), base)
    ensembles = build_ensembles(rep, base)
    if choice not in ensembles:
        raise ValueError(f"unknown ensemble {choice!r}; have {list(ensembles)}")

    spec = ensemble_to_spec(choice, ensembles[choice])
    spec["train_season"] = train_season
    spec["minutes_version"] = "v1"
    # Cohort-relative blends (rank/z) output an ordinal signal; fit a per-position
    # linear map score -> expected points on TRAIN so the served xP is in points
    # units (keeps selection ordering, fixes captain/EV/display semantics).
    if spec.get("ensemble") in ("rank_blend", "z_blend"):
        spec["calibration"] = _fit_points_calibration(
            PredictorAnalysis(sm), train_season, choice, ensembles[choice])
    spec = _sanitize(spec)

    holdout: dict = {}
    if eval_season and eval_gws:
        from ..backtest.engine import Backtester
        res = Backtester(sm).run(eval_season, eval_gws, ensembles[choice])
        holdout = {"eval_season": eval_season, "eval_gws": [eval_gws[0], eval_gws[-1]],
                   "net_points": res.net_points}

    with sm() as s:
        stmt = insert(model_registry).values(
            version=registry_version, status="frozen", spec=spec,
            holdout_metrics=holdout, notes=f"ensemble {choice} trained on {train_season}")
        s.execute(stmt.on_conflict_do_update(
            index_elements=["version"],
            set_={"status": "frozen", "spec": spec, "holdout_metrics": holdout}))
        s.commit()
    log.info("ensemble frozen", extra={"version": registry_version, "choice": choice,
                                       "holdout": holdout})
    return {"version": registry_version, "choice": choice,
            "components": [p["component"].get("name") if "component" in p else None
                          for p in spec.get("parts", [])],
            "holdout": holdout}


def _fit_points_calibration(analysis, train_season: str, choice: str, predictor) -> dict:
    """Per-position linear map (raw ensemble score -> expected points), fit on
    the train season. Returns {str(pos): [intercept, slope>=0]}."""
    import numpy as np

    panel = analysis.build_panel(train_season, list(range(1, 39)), {choice: predictor})
    calib: dict[str, list[float]] = {}
    if panel.empty:
        return calib
    for pos in (1, 2, 3, 4):
        sub = panel[panel["pos"] == pos]
        if len(sub) >= 20 and sub[choice].std() > 1e-9:
            slope, intercept = np.polyfit(sub[choice].to_numpy(), sub["y"].to_numpy(), 1)
            calib[str(pos)] = [float(intercept), float(max(0.0, slope))]
    return calib


def load_spec(version: str = "v1", sm: sessionmaker[Session] | None = None) -> dict | None:
    sm = sm or get_sessionmaker()
    with sm() as s:
        row = s.execute(select(model_registry.c.spec)
                        .where(model_registry.c.version == version)).first()
    return row[0] if row else None


def _f(v) -> float | None:
    try:
        return float(v) if v is not None and np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _sanitize(obj):
    """Recursively replace non-finite floats with None so the spec is valid JSON."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        return obj if np.isfinite(obj) else None
    return obj
