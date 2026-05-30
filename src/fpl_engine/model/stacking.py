"""Per-position stacking meta-learner (research T6).

The IC-weighted / points-average blends weight each base predictor by its own
skill but are blind to **redundancy** between predictors (adding a 5th correlated
form signal dilutes a simple average — observed with the recency signal). A
stacking meta-learner fixes this: it regresses realised points on the base
predictors' outputs, so an L2-regularised fit *learns* to down-weight collinear
inputs and combine them where each is informative.

Trained per position on a strictly-prior season's panel (season-as-fold ⇒ no
leakage into the eval season). Ridge (not a GBM) given the small sample. Falls
back to an equal-weight average for a position with too little data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..logging_setup import get_logger
from .analysis import PredictorAnalysis
from .predictors import BasePredictor, Predictor

log = get_logger(__name__)

_POSITIONS = (1, 2, 3, 4)
_MIN_ROWS = 50           # below this, fall back to equal weights for the position
_ALPHAS = (0.1, 1.0, 10.0, 100.0)


@dataclass
class _Cell:
    names: list[str]              # predictor order
    coef: list[float]
    intercept: float
    mean: list[float]
    std: list[float]
    equal_weight: bool = False    # degenerate fallback


@dataclass
class StackBlend(BasePredictor):
    """Applies per-position fitted weights to base predictors' cohort scores
    (optionally augmented with causal meta-features read from each player's
    feature dict, so the meta-learner can condition on context)."""
    name: str
    parts: dict[str, Predictor]              # base predictor name -> predictor
    cells: dict[int, _Cell] = field(default_factory=dict)
    meta_features: tuple[str, ...] = ()      # extra causal feature keys

    def _meta(self, features: dict) -> dict[str, float]:
        out = {}
        for mf in self.meta_features:
            v = features.get(mf)
            out[mf] = float(v) if v is not None else 0.0
        return out

    def score(self, features: dict, element_type: int) -> float:
        cell = self.cells.get(element_type)
        sigs = {n: p.score(features, element_type) for n, p in self.parts.items()}
        sigs.update(self._meta(features))
        return self._apply(cell, sigs)

    def score_frame(self, items):
        framed = {n: p.score_frame(items) for n, p in self.parts.items()}
        out: dict[int, float] = {}
        for eid, feats, et in items:
            cell = self.cells.get(et)
            sigs = {n: framed[n][eid] for n in self.parts}
            sigs.update(self._meta(feats or {}))
            out[eid] = self._apply(cell, sigs)
        return out

    @staticmethod
    def _apply(cell: _Cell | None, sigs: dict[str, float]) -> float:
        if cell is None:
            return sum(sigs.values()) / len(sigs) if sigs else 0.0
        if cell.equal_weight:
            vals = [sigs[n] for n in cell.names]
            return sum(vals) / len(vals) if vals else 0.0
        pred = cell.intercept
        for j, n in enumerate(cell.names):
            s = cell.std[j] or 1.0
            pred += cell.coef[j] * ((sigs.get(n, 0.0) - cell.mean[j]) / s)
        return pred


def calibrate(predictor: Predictor, season: str, gws: list[int], *,
              name: str | None = None,
              sm: sessionmaker[Session] | None = None) -> StackBlend:
    """Per-position affine calibration of a single predictor — a one-input stack.

    Aligns the predictor's output to realised points *per position* (so a 6-xP
    DEF and a 6-xP MID are comparable, and absolute magnitudes are meaningful for
    transfer-EV/hit decisions). Fit on a strictly-prior season (no leakage).
    """
    return fit_stack({predictor.name: predictor}, season, gws,
                     name=name or f"cal:{predictor.name}", sm=sm)


def fit_stack(predictors: dict[str, Predictor], season: str, gws: list[int], *,
              name: str = "stack", meta_features: tuple[str, ...] = (),
              sm: sessionmaker[Session] | None = None) -> StackBlend:
    """Fit a per-position Ridge meta-learner on (season, gws) base-predictor
    outputs (+ optional causal meta-features) vs realised points. Use a season
    the eval window doesn't include (leakage-free)."""
    from sklearn.linear_model import RidgeCV

    sm = sm or get_sessionmaker()
    panel = PredictorAnalysis(sm).build_panel(season, gws, predictors,
                                              meta_features=meta_features)
    names = list(predictors) + list(meta_features)
    cells: dict[int, _Cell] = {}
    for pos in _POSITIONS:
        grp = panel[panel["pos"] == pos] if not panel.empty else panel
        if panel.empty or len(grp) < _MIN_ROWS:
            cells[pos] = _Cell(names, [], 0.0, [], [], equal_weight=True)
            continue
        X = grp[names].to_numpy(dtype=float)
        y = grp["y"].to_numpy(dtype=float)
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        std[std == 0] = 1.0
        Xs = (X - mean) / std
        model = RidgeCV(alphas=_ALPHAS).fit(Xs, y)
        cells[pos] = _Cell(names, [float(c) for c in model.coef_],
                           float(model.intercept_),
                           [float(m) for m in mean], [float(s) for s in std])
    log.info("stack fitted", extra={"season": season, "rows": len(panel),
                                    "predictors": len(names)})
    return StackBlend(name, dict(predictors), cells, meta_features=tuple(meta_features))
