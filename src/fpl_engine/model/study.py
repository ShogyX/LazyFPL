"""Predictive-validity study (plan 4.1).

For each (position, target, horizon):
  1. univariate Spearman rank-IC screen with Benjamini-Hochberg FDR control;
  2. per-season IC -> mean/sd IC + sign stability (LOSO-style robustness);
  3. Elastic-Net weights fit with leave-one-season-out CV (pooled OOS skill);
  4. beat-the-baseline gate vs last-GW and season-average naive predictors;
  5. family-level grouping + optional LightGBM gain importances.

Writes ``study.feature_importance`` and ``study.model_calibration``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNetCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import feature_importance, model_calibration, training_rows
from ..features.families import POSITION_FAMILIES, _PER90_FAMILY, _metric_source
from ..logging_setup import get_logger
from .stats import benjamini_hochberg, per_season_ic, rmse, spearman_ic

log = get_logger(__name__)

# (target name, horizon, training_rows column, baseline metric prefix)
TARGET_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("points", "next1", "tgt_pts_next1", "total_points"),
    ("points", "next6", "tgt_pts_next6", "total_points"),
    ("minutes", "next1", "tgt_minutes_next1", "minutes"),
)

FDR_Q = 0.10
MIN_SIGN_STABILITY = 0.6
MIN_ABS_IC = 0.02
MIN_HISTORY = 3
# Lean live model (plan E.4): collapse collinear windows of one metric and cap
# the total feature count so the catalog stays broad but the model stays lean.
MAX_PER_METRIC = 2
MAX_SELECTED = 30


def _metric_family(position: int, metric: str) -> str | None:
    for family, metrics in POSITION_FAMILIES.get(position, {}).items():
        if metric in metrics:
            return family
    return None


def _parse_feature(position: int, feature: str) -> dict:
    """Decompose a feature key into metric/window/half_life/family."""
    if "__" in feature:
        metric, suffix = feature.split("__", 1)
        window = suffix if not suffix.startswith("ewma_hl") else None
        half_life = suffix[len("ewma_hl"):] if suffix.startswith("ewma_hl") else None
        family = _metric_family(position, metric)
        return {"metric": metric, "window": window, "half_life": half_life,
                "family": family}
    # per-90 feature (e.g. xg90): find owning family in _PER90_FAMILY
    family = None
    for fam, names in _PER90_FAMILY.get(position, {}).items():
        if feature in names:
            family = fam
    return {"metric": feature, "window": "per90", "half_life": None, "family": family}


@dataclass
class StudyResult:
    position: int
    target: str
    horizon: str
    n_rows: int
    n_seasons: int
    n_selected: int
    oos_spearman: float
    beats_baseline: bool


class PredictiveValidityStudy:
    def __init__(self, sm: sessionmaker[Session] | None = None,
                 study_version: str = "v1-dev"):
        self._sm = sm or get_sessionmaker()
        self.version = study_version

    # -- dataset --
    def _load(self, position: int, target_col: str,
              seasons: Iterable[str] | None) -> pd.DataFrame:
        tr = training_rows.c
        stmt = select(tr.season, tr.player_key, tr.gw, tr.features, tr[target_col]).where(
            tr.element_type == position, tr.hist_n >= MIN_HISTORY,
            tr[target_col].isnot(None),
        )
        if seasons is not None:
            stmt = stmt.where(tr.season.in_(list(seasons)))
        with self._sm() as s:
            rows = s.execute(stmt).all()
        if not rows:
            return pd.DataFrame()
        feats = pd.DataFrame([r.features for r in rows]).apply(pd.to_numeric, errors="coerce")
        feats["__season"] = [r.season for r in rows]
        feats["__y"] = [float(r[4]) for r in rows]
        return feats

    def run_one(self, position: int, target: str, horizon: str, target_col: str,
                base_metric: str, seasons: Iterable[str] | None = None) -> StudyResult | None:
        df = self._load(position, target_col, seasons)
        if df.empty or df["__season"].nunique() < 2:
            log.warning("insufficient data", extra={"position": position, "target": target})
            return None

        feat_cols = [c for c in df.columns if not c.startswith("__")]
        rows_fi: list[dict] = []

        # 1-2) screen + lean selection (this df may be train-only when called
        #      from freeze, keeping any holdout untouched).
        summaries, qmap, selected = self._screen(df, position, feat_cols)

        # 3) Elastic-Net LOSO; baselines scored on the SAME pooled OOS rows for
        #    a fair gate (model OOS vs baseline OOS, not vs baseline in-sample).
        recent_col = f"{base_metric}__mean_1"
        season_col = f"{base_metric}__career_mean"
        pooled = self._loso_elasticnet(df, selected, [recent_col, season_col])
        oos_sp, _ = spearman_ic(pooled["pred"], pooled["y"])
        oos_r = rmse(pooled["y"], pooled["pred"])
        br_sp = self._safe_sp(pooled.get(recent_col), pooled["y"])
        bs_sp = self._safe_sp(pooled.get(season_col), pooled["y"])
        br_rm = rmse(pooled["y"], pooled[recent_col]) if recent_col in pooled else float("nan")
        bs_rm = rmse(pooled["y"], pooled[season_col]) if season_col in pooled else float("nan")
        finite_bases = [v for v in (br_sp, bs_sp) if v is not None and np.isfinite(v)]
        best_base_sp = max(finite_bases) if finite_bases else float("nan")
        beats = bool(np.isfinite(oos_sp) and (not np.isfinite(best_base_sp)
                                              or oos_sp > best_base_sp))

        en_weights = self._fit_final_en(df, selected)
        gbm_imp = self._gbm_importance(df, selected)

        # write feature_importance
        selected_set = set(selected)
        for col in feat_cols:
            summ = summaries[col]
            meta = _parse_feature(position, col)
            rows_fi.append({
                "study_version": self.version, "position": position, "target": target,
                "horizon": horizon, "feature": col,
                "family": meta["family"], "metric": meta["metric"],
                "window_label": meta["window"], "half_life": meta["half_life"],
                "mean_ic": _f(summ.mean_ic), "sd_ic": _f(summ.sd_ic),
                "sign_stability": _f(summ.sign_stability), "n_seasons": summ.n_seasons,
                "fdr_q": _f(qmap.get(col)),
                "en_weight": _f(en_weights.get(col)),
                "gbm_importance": _f(gbm_imp.get(col)),
                "selected": col in selected_set,
            })
        self._write_fi(rows_fi)
        self._write_calibration({
            "study_version": self.version, "position": position, "target": target,
            "horizon": horizon, "n_rows": len(df), "n_seasons": int(df["__season"].nunique()),
            "oos_spearman": _f(oos_sp), "oos_rmse": _f(oos_r),
            "base_recent_spearman": _f(br_sp), "base_season_spearman": _f(bs_sp),
            "base_recent_rmse": _f(br_rm), "base_season_rmse": _f(bs_rm),
            "beats_baseline": beats, "shrink_lambda": None,
            "extra": {"n_selected": len(selected), "selected": selected[:50]},
        })
        log.info("study cell done", extra={"position": position, "target": target,
                                           "horizon": horizon, "oos_spearman": _f(oos_sp),
                                           "beats_baseline": beats, "n_selected": len(selected)})
        return StudyResult(position, target, horizon, len(df),
                           int(df["__season"].nunique()), len(selected),
                           float(oos_sp) if np.isfinite(oos_sp) else float("nan"), beats)

    # -- screen + lean selection --
    def _screen(self, df: pd.DataFrame, position: int, feat_cols: list[str]):
        """Univariate IC screen + FDR, then a lean per-metric-capped selection.

        Returns (summaries, qmap, selected). Operates only on the rows in ``df``
        so a train-only df yields a holdout-clean selection.
        """
        y = df["__y"].to_numpy()
        season = df["__season"].to_numpy()
        summaries: dict = {}
        pvals: list[float] = []
        for col in feat_cols:
            xv = df[col].to_numpy()
            _, p = spearman_ic(xv, y)
            summaries[col] = per_season_ic(xv, y, season)
            pvals.append(p)
        qvals = benjamini_hochberg(np.array(pvals))
        qmap = {col: qvals[i] for i, col in enumerate(feat_cols)}

        candidates = [
            col for col in feat_cols
            if np.isfinite(qmap[col]) and qmap[col] < FDR_Q
            and np.isfinite(summaries[col].mean_ic)
            and abs(summaries[col].mean_ic) >= MIN_ABS_IC
            and summaries[col].sign_stability >= MIN_SIGN_STABILITY
        ]
        selected = self._collapse_per_metric(position, candidates, summaries)
        if len(selected) < 2:  # fallback: best representation per metric overall
            all_cands = [c for c in feat_cols if np.isfinite(summaries[c].mean_ic)]
            selected = self._collapse_per_metric(position, all_cands, summaries, per_metric=1)[:10]
        return summaries, qmap, selected

    @staticmethod
    def _collapse_per_metric(position, cols, summaries, per_metric=MAX_PER_METRIC):
        """Keep the strongest ``per_metric`` windows of each metric (they are
        collinear), then cap the total by |mean_ic| -> a lean, decorrelated set."""
        by_metric: dict[str, list[str]] = {}
        for col in cols:
            metric = _parse_feature(position, col)["metric"]
            by_metric.setdefault(metric, []).append(col)
        kept: list[str] = []
        for metric_cols in by_metric.values():
            ranked = sorted(metric_cols, key=lambda c: abs(summaries[c].mean_ic), reverse=True)
            kept.extend(ranked[:per_metric])
        kept.sort(key=lambda c: abs(summaries[c].mean_ic), reverse=True)
        return kept[:MAX_SELECTED]

    # -- modelling helpers --
    @staticmethod
    def _pipeline() -> Pipeline:
        return Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("en", ElasticNetCV(l1_ratio=[0.2, 0.5, 0.8],
                                cv=3, max_iter=5000, random_state=0)),
        ])

    def _loso_elasticnet(self, df: pd.DataFrame, cols: list[str],
                         base_cols: list[str] | None = None) -> dict[str, np.ndarray]:
        """Pooled leave-one-season-out predictions, plus the baseline feature
        values for the SAME held-out rows so baselines are scored OOS too."""
        base_cols = base_cols or []
        seasons = sorted(df["__season"].unique())
        acc: dict[str, list[float]] = {"y": [], "pred": []}
        for b in base_cols:
            acc[b] = []
        for hold in seasons:
            train = df[df["__season"] != hold]
            test = df[df["__season"] == hold]
            if len(train) < 50 or test.empty:
                continue
            pipe = self._pipeline()
            try:
                pipe.fit(train[cols].to_numpy(), train["__y"].to_numpy())
                pred = pipe.predict(test[cols].to_numpy())
            except Exception as exc:  # pragma: no cover - degenerate folds
                log.warning("loso fold failed", extra={"hold": hold, "error": str(exc)})
                continue
            acc["y"].extend(test["__y"].tolist())
            acc["pred"].extend(pred.tolist())
            for b in base_cols:
                vals = test[b].tolist() if b in test.columns else [float("nan")] * len(test)
                acc[b].extend(vals)
        return {k: np.asarray(v, dtype=float) for k, v in acc.items()}

    def _fit_final_en(self, df: pd.DataFrame, cols: list[str]) -> dict[str, float]:
        pipe = self._pipeline()
        try:
            pipe.fit(df[cols].to_numpy(), df["__y"].to_numpy())
        except Exception:  # pragma: no cover
            return {}
        coefs = pipe.named_steps["en"].coef_
        return {c: float(w) for c, w in zip(cols, coefs)}

    def _gbm_importance(self, df: pd.DataFrame, cols: list[str]) -> dict[str, float]:
        try:
            import lightgbm as lgb
        except Exception:
            return {}
        try:
            X = df[cols].fillna(df[cols].median()).to_numpy()
            model = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.05,
                                      num_leaves=31, verbose=-1, random_state=0)
            model.fit(X, df["__y"].to_numpy())
            total = float(model.feature_importances_.sum()) or 1.0
            return {c: float(v) / total for c, v in zip(cols, model.feature_importances_)}
        except Exception as exc:  # pragma: no cover
            log.warning("gbm importance failed", extra={"error": str(exc)})
            return {}

    @staticmethod
    def _safe_sp(arr, y) -> float:
        if arr is None or len(arr) == 0:
            return float("nan")
        rho, _ = spearman_ic(np.asarray(arr, dtype=float), y)
        return rho

    # -- persistence --
    def _write_fi(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self._sm() as s:
            for i in range(0, len(rows), 500):
                chunk = rows[i:i + 500]
                stmt = insert(feature_importance).values(chunk)
                update = {c: stmt.excluded[c] for c in chunk[0] if c not in
                          ("study_version", "position", "target", "horizon", "feature")}
                s.execute(stmt.on_conflict_do_update(
                    index_elements=["study_version", "position", "target", "horizon", "feature"],
                    set_=update))
            s.commit()

    def _write_calibration(self, row: dict) -> None:
        with self._sm() as s:
            stmt = insert(model_calibration).values(row)
            update = {c: stmt.excluded[c] for c in row if c not in
                      ("study_version", "position", "target", "horizon")}
            s.execute(stmt.on_conflict_do_update(
                index_elements=["study_version", "position", "target", "horizon"],
                set_=update))
            s.commit()

    def run(self, positions: Iterable[int] = (1, 2, 3, 4),
            targets: Iterable[tuple] = TARGET_SPECS,
            seasons: Iterable[str] | None = None) -> list[StudyResult]:
        out: list[StudyResult] = []
        for position in positions:
            for target, horizon, col, base in targets:
                res = self.run_one(position, target, horizon, col, base, seasons)
                if res is not None:
                    out.append(res)
        return out


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v) if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None
