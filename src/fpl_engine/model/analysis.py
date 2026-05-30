"""Predictor correlation & complementarity analysis (operator ask).

Are candidate models REDUNDANT (predicting the same thing, just some more
accurate) or COMPLEMENTARY (each right where another is wrong)? This builds a
signal panel over the strictly-causal ``training_rows`` data and reports:

  * signal correlation        — how alike the predictors' rankings are;
  * per-predictor IC          — overall + per position (where each has its edge);
  * per-GW IC matrix          — IC of each predictor each GW;
  * complementarity           — correlation of per-GW ICs (low/negative ⇒ one
                                wins when another loses ⇒ blend-worthy);
  * fraction_best             — how often each predictor is the GW's best;
  * ic_weights                — overall IC, used to weight an IC-blend.

The target is the GW's realised points, paired with strictly-prior features
(equivalent to a one-step-ahead prediction framed from the previous GW).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session, sessionmaker

from ..backtest.engine import Backtester
from ..db.engine import get_sessionmaker
from .stats import spearman_ic


@dataclass
class AnalysisReport:
    names: list[str]
    n_rows: int
    n_gws: int
    overall_ic: dict[str, float]
    per_position_ic: dict[str, dict[int, float]]
    signal_correlation: dict[str, dict[str, float]]
    per_gw_ic_correlation: dict[str, dict[str, float]]
    fraction_best: dict[str, float]
    ic_weights: dict[str, float]
    most_complementary_pair: tuple[str, str, float] | None = None
    panel: pd.DataFrame = field(default=None, repr=False)


class PredictorAnalysis:
    def __init__(self, sm: sessionmaker[Session] | None = None):
        self._sm = sm or get_sessionmaker()

    def build_panel(self, season: str, gws: list[int], predictors: dict,
                    meta_features: tuple[str, ...] = ()) -> pd.DataFrame:
        """One row per (gw, player): each predictor's signal + realised points,
        plus optional causal meta-feature columns (read from training_rows
        features) for feature-augmented stacking."""
        frames = Backtester(self._sm)._frames(season, gws)
        rows: list[dict] = []
        for gw, fr in frames.items():
            items = [(eid, f.features, f.pos) for eid, f in fr.items()]
            sigs = {name: pred.score_frame(items) for name, pred in predictors.items()}
            for eid, f in fr.items():
                row = {"gw": gw, "eid": eid, "pos": f.pos, "y": float(f.actual)}
                for name in predictors:
                    row[name] = sigs[name][eid]
                for mf in meta_features:
                    v = (f.features or {}).get(mf)
                    row[mf] = float(v) if v is not None else 0.0
                rows.append(row)
        return pd.DataFrame(rows)

    def analyse(self, season: str, gws: list[int], predictors: dict) -> AnalysisReport:
        panel = self.build_panel(season, gws, predictors)
        names = list(predictors)
        if panel.empty:
            return AnalysisReport(names, 0, 0, {}, {}, {}, {}, {}, {}, None, panel)

        y = panel["y"].to_numpy()
        overall_ic = {n: _ic(panel[n].to_numpy(), y) for n in names}

        per_position_ic: dict[str, dict[int, float]] = {n: {} for n in names}
        for pos, grp in panel.groupby("pos"):
            yp = grp["y"].to_numpy()
            for n in names:
                per_position_ic[n][int(pos)] = _ic(grp[n].to_numpy(), yp)

        # signal correlation (redundancy)
        sig_corr = panel[names].corr(method="spearman").round(3)
        signal_correlation = {a: {b: float(sig_corr.loc[a, b]) for b in names} for a in names}

        # per-GW IC matrix -> complementarity = correlation of per-GW IC series
        per_gw = {}
        for gw, grp in panel.groupby("gw"):
            yg = grp["y"].to_numpy()
            per_gw[gw] = {n: _ic(grp[n].to_numpy(), yg) for n in names}
        gw_ic = pd.DataFrame(per_gw).T  # index=gw, cols=names
        ic_corr = gw_ic.corr().round(3)
        per_gw_ic_correlation = {a: {b: _safe(ic_corr.loc[a, b]) for b in names} for a in names}

        # fraction of GWs each predictor is the (finite) best
        best_counts = {n: 0 for n in names}
        valid_gws = 0
        for gw, ics in per_gw.items():
            finite = {n: v for n, v in ics.items() if np.isfinite(v)}
            if not finite:
                continue
            valid_gws += 1
            best_counts[max(finite, key=finite.get)] += 1
        fraction_best = {n: round(best_counts[n] / valid_gws, 3) if valid_gws else 0.0
                         for n in names}

        ic_weights = {n: round(v, 4) for n, v in overall_ic.items()}

        # most complementary pair: lowest per-GW IC correlation among decent models
        decent = [n for n in names if overall_ic[n] > 0.05]
        best_pair = None
        for i, a in enumerate(decent):
            for b in decent[i + 1:]:
                c = per_gw_ic_correlation[a][b]
                if c is not None and (best_pair is None or c < best_pair[2]):
                    best_pair = (a, b, c)

        return AnalysisReport(
            names=names, n_rows=len(panel), n_gws=panel["gw"].nunique(),
            overall_ic={n: round(v, 4) for n, v in overall_ic.items()},
            per_position_ic={n: {p: round(v, 4) for p, v in d.items()}
                             for n, d in per_position_ic.items()},
            signal_correlation=signal_correlation,
            per_gw_ic_correlation=per_gw_ic_correlation,
            fraction_best=fraction_best, ic_weights=ic_weights,
            most_complementary_pair=best_pair, panel=panel)


def _ic(x: np.ndarray, y: np.ndarray) -> float:
    rho, _ = spearman_ic(x, y)
    return rho if np.isfinite(rho) else float("nan")


def _safe(v) -> float | None:
    return float(v) if v is not None and np.isfinite(v) else None
