"""Pluggable, backtestable points predictors + ensembles.

Two scoring entry points:
  * ``score(features, element_type)``  — one player (scale-as-is signal);
  * ``score_frame(items)``             — a whole GW's player cohort at once,
    where ``items`` is ``[(eid, features, element_type), ...]`` -> ``{eid: xp}``.

The cohort form lets *ensembles* normalise each component across the GW (z-score
or rank) before combining — essential when blending signals on different scales
(points vs ICT vs xGI). Ensembles also support **bounded influence**: a per-model
z-score clip (upper/lower limit so no single model dominates a GW) and a
non-positive-IC gate (a model with no edge gets zero weight).

Everything consumes the strictly-causal ``training_rows`` panel, so any feature,
model or ensemble is comparable head-to-head in the backtester.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Iterable, Protocol, runtime_checkable

from .freeze import load_spec
from .predict import _apply_cell
from .stats import spearman_ic


@runtime_checkable
class Predictor(Protocol):
    name: str

    def score(self, features: dict, element_type: int) -> float: ...

    def score_frame(self, items: list[tuple[int, dict, int]]) -> dict[int, float]: ...


class BasePredictor:
    """Default cohort scoring = per-player ``score`` over the GW."""

    def score_frame(self, items: list[tuple[int, dict, int]]) -> dict[int, float]:
        return {eid: self.score(feats, et) for eid, feats, et in items}


@dataclass
class FeaturePredictor(BasePredictor):
    name: str
    feature_key: str
    default: float = 0.0

    def score(self, features: dict, element_type: int) -> float:
        v = features.get(self.feature_key)
        try:
            return float(v) if v is not None else self.default
        except (TypeError, ValueError):
            return self.default


@dataclass
class FrozenModelPredictor(BasePredictor):
    version: str = "v1"
    target: str = "points"
    horizon: str = "next1"
    name: str = ""
    _cells: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self.name = self.name or f"model:{self.version}"
        spec = load_spec(self.version)
        if spec is None:
            raise ValueError(f"no frozen spec for version {self.version!r}")
        self._cells = {(c["position"], c["target"], c["horizon"]): c
                       for c in spec["cells"]}

    def score(self, features: dict, element_type: int) -> float:
        cell = self._cells.get((element_type, self.target, self.horizon))
        if cell is None:
            return 0.0
        return _apply_cell(cell, features) or 0.0


# -- recency-weighted rate (shared with the component model) --
RECENCY_K = 4.0


def _feat_first(feats: dict, keys: tuple[str, ...]) -> float | None:
    for k in keys:
        v = feats.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def recency_weighted_rate(feats: dict, metric: str, *, k: float = RECENCY_K) -> float:
    """Empirical-Bayes blend of a *fresh* short-EWMA rate and a *stable* long-run
    level for ``metric``. The fresh weight ``n/(n+k)`` grows with the number of
    recent observations, so thin data leans on the stable prior and rich/recent
    data (incl. accumulating current-season form) leans on fresh form."""
    fresh = _feat_first(feats, (f"{metric}__ewma_hl2", f"{metric}__ewma_hl5",
                                f"{metric}__mean_3"))
    stable = _feat_first(feats, (f"{metric}__mean_38", f"{metric}__career_mean",
                                 f"{metric}__mean_19", f"{metric}__mean_5"))
    n = _feat_first(feats, (f"{metric}__n",)) or 0.0
    if fresh is None and stable is None:
        return 0.0
    if fresh is None:
        return stable
    if stable is None:
        return fresh
    w = n / (n + k)
    return w * fresh + (1.0 - w) * stable


@dataclass
class RecencyPredictor(BasePredictor):
    """Recency-adaptive points signal: blends fresh form with a stable long-run
    level, leaning fresher as observations accumulate. A points-scale predictor,
    so it joins the IC-weighted / points blends and freshens the ensemble."""
    name: str = "recency"
    metric: str = "total_points"
    k: float = RECENCY_K

    def score(self, features: dict, element_type: int) -> float:
        return recency_weighted_rate(features, self.metric, k=self.k)


# -- cohort normalisation helpers --
def _zscores(scores: dict[int, float]) -> dict[int, float]:
    vals = list(scores.values())
    if len(vals) < 2:
        return {k: 0.0 for k in scores}
    mean = statistics.fmean(vals)
    sd = statistics.pstdev(vals) or 1.0
    return {k: (v - mean) / sd for k, v in scores.items()}


def _ranks(scores: dict[int, float]) -> dict[int, float]:
    """Percentile rank in [0, 1] across the cohort (ties share mid-rank)."""
    n = len(scores)
    if n < 2:
        return {k: 0.5 for k in scores}
    order = sorted(scores, key=lambda k: scores[k])
    out: dict[int, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        mid = (i + j) / 2.0 / (n - 1)
        for k in range(i, j + 1):
            out[order[k]] = mid
        i = j + 1
    return out


@dataclass
class ZBlend(BasePredictor):
    """Weighted blend of components' per-GW z-scores, each clipped to ±clip."""
    name: str
    parts: list[tuple[Predictor, float]]
    clip: float = 2.5

    def score(self, features: dict, element_type: int) -> float:  # degenerate fallback
        return sum(w * p.score(features, element_type) for p, w in self.parts)

    def score_frame(self, items):
        agg = {eid: 0.0 for eid, _, _ in items}
        for pred, w in self.parts:
            if w == 0:
                continue
            z = _zscores(pred.score_frame(items))
            for eid, zv in z.items():
                agg[eid] += w * max(-self.clip, min(self.clip, zv))
        return agg


@dataclass
class RankBlend(BasePredictor):
    """Weighted blend of components' per-GW percentile ranks (scale-free)."""
    name: str
    parts: list[tuple[Predictor, float]]

    def score(self, features: dict, element_type: int) -> float:
        return sum(w * p.score(features, element_type) for p, w in self.parts)

    def score_frame(self, items):
        agg = {eid: 0.0 for eid, _, _ in items}
        for pred, w in self.parts:
            if w == 0:
                continue
            r = _ranks(pred.score_frame(items))
            for eid, rv in r.items():
                agg[eid] += w * rv
        return agg


@dataclass
class PointsBlend(BasePredictor):
    """Weighted average of points-scale components, output in POINTS units and
    **cohort-independent** (scored per player) so the served value equals the
    backtested value exactly and downstream points semantics (captain x2, bench,
    EV) stay meaningful. Each component is winsorised to [0, clip_hi] to bound a
    single model's influence; non-positive weights are gated out."""
    name: str
    parts: list[tuple[Predictor, float]]
    clip_hi: float = 15.0

    def score(self, features: dict, element_type: int) -> float:
        num = den = 0.0
        for p, w in self.parts:
            if w <= 0:
                continue
            v = max(0.0, min(self.clip_hi, float(p.score(features, element_type))))
            num += w * v
            den += w
        return num / den if den else 0.0


@dataclass
class PerPositionZBlend(BasePredictor):
    """Z-clip blend with weights that differ by position (a model can fill a
    hole for only some positions). ``pos_weights[pos]`` -> list[(predictor, w)]."""
    name: str
    pos_weights: dict[int, list[tuple[Predictor, float]]]
    clip: float = 2.5

    def score(self, features: dict, element_type: int) -> float:
        return sum(w * p.score(features, element_type)
                   for p, w in self.pos_weights.get(element_type, []))

    def score_frame(self, items):
        # z-score each distinct predictor once over the whole cohort
        preds = {id(p): p for parts in self.pos_weights.values() for p, _ in parts}
        zcache = {pid: _zscores(p.score_frame(items)) for pid, p in preds.items()}
        agg = {eid: 0.0 for eid, _, _ in items}
        for eid, _feats, et in items:
            for p, w in self.pos_weights.get(et, []):
                zv = zcache[id(p)][eid]
                agg[eid] += w * max(-self.clip, min(self.clip, zv))
        return agg


class OnlineHedgeBlend(BasePredictor):
    """Exponentially-weighted (Hedge) z-blend whose component weights adapt online
    to each model's realised per-GW skill.

    LEAKAGE-SAFE BY CONSTRUCTION: the weights used to score GW *t* derive only
    from ``observe()`` calls for GWs < *t* (results known before the deadline).
    Initial weights come from the TRAIN season (a different season); ``reset()``
    restores them at the start of each backtest run so state never carries over.
    """

    def __init__(self, name: str, parts: list[tuple[Predictor, float]],
                 eta: float = 0.5, clip: float = 2.5):
        self.name = name
        self.parts = parts                       # [(predictor, initial_weight)]
        self.eta = eta
        self.clip = clip
        self._init = self._normalise([max(0.0, w) for _, w in parts])
        self._w = list(self._init)

    @staticmethod
    def _normalise(ws: list[float]) -> list[float]:
        s = sum(ws)
        n = len(ws) or 1
        return [w / s for w in ws] if s > 0 else [1.0 / n] * len(ws)

    def reset(self) -> None:
        self._w = list(self._init)

    def score_frame(self, items):
        agg = {eid: 0.0 for eid, _, _ in items}
        for (pred, _), w in zip(self.parts, self._w):
            if w == 0:
                continue
            z = _zscores(pred.score_frame(items))
            for eid, zv in z.items():
                agg[eid] += w * max(-self.clip, min(self.clip, zv))
        return agg

    def observe(self, items, actuals: dict[int, float]) -> None:
        """Update weights from a *completed* GW's realised points (Hedge step).
        Called by the backtester AFTER scoring the GW, so it only ever informs
        FUTURE GWs — never the GW it is computed from."""
        if len(items) < 3:
            return
        ys = [float(actuals.get(eid, 0.0)) for eid, _, _ in items]
        if max(ys) == min(ys):
            return
        new_w: list[float] = []
        for (pred, _), w in zip(self.parts, self._w):
            scored = pred.score_frame(items)
            xs = [float(scored[eid]) for eid, _, _ in items]
            ic, _ = spearman_ic(xs, ys)
            if ic != ic:                          # NaN guard
                ic = 0.0
            loss = (1.0 - ic) / 2.0               # [0,1]; high IC -> low loss
            new_w.append(w * math.exp(-self.eta * loss))
        self._w = self._normalise(new_w)

    def score(self, features: dict, element_type: int) -> float:  # degenerate fallback
        return sum(w * p.score(features, element_type)
                   for (p, _), w in zip(self.parts, self._w))


def ict_heavy_blend(version: str = "v1", ict_weight: float = 0.65,
                    model_weight: float = 0.35, clip: float = 2.5,
                    include_model: bool = True) -> ZBlend:
    """ICT-form-leaning blend: ICT EWMA dominant, trained model as support.

    ``include_model=False`` makes it pure ICT — used for a leakage-free read,
    since the frozen model was fit on some evaluated seasons.
    """
    parts: list[tuple[Predictor, float]] = [
        (FeaturePredictor("ict", "ict_index__ewma_hl5"), ict_weight),
    ]
    if include_model:
        try:
            parts.append((FrozenModelPredictor(version), model_weight))
        except Exception:
            parts = [(FeaturePredictor("ict", "ict_index__ewma_hl5"), 1.0)]
    return ZBlend("ict_heavy", parts, clip=clip)


# Points-scale predictors eligible for the points-calibrated blend (excludes ICT
# index / xGI rate, which are not in points units). ``recency`` is deliberately
# omitted: it is redundant with the short-form signals already here, so it
# dilutes the simple IC-weighted *average* (it still contributes to the
# IC-/per-position z-blends and is the core of the component model, where it
# adds skill — backtest-verified).
POINTS_SCALE_KEYS = {"last1", "recent3", "recent5", "form_ewma5", "season38",
                     "ppg_career"}


def _is_points_scale(name: str) -> bool:
    # points-scale: the form windows + the frozen linear model (FPL-points-scale).
    # Excludes ICT/xGI rates, and the component model — backtests showed adding
    # the latter dilutes this simple IC-weighted *average* (it differs in scale
    # / minutes-gating); the stack/z-blends can use it instead.
    return name in POINTS_SCALE_KEYS or name.startswith("model:")


def points_blend(ic_weights: dict[str, float], predictors: dict[str, Predictor],
                 floor: float = 0.0, clip_hi: float = 15.0) -> PointsBlend:
    """IC-weighted average of the points-scale models -> a calibrated, cohort-
    independent points signal."""
    parts = [(predictors[n], max(0.0, ic - floor))
             for n, ic in ic_weights.items()
             if n in predictors and ic > floor and _is_points_scale(n)]
    if not parts:
        parts = [(p, 1.0) for n, p in predictors.items() if _is_points_scale(n)]
    return PointsBlend("points_blend", parts, clip_hi=clip_hi)


def ic_weighted_blend(ic_weights: dict[str, float], predictors: dict[str, Predictor],
                      floor: float = 0.0, clip: float = 2.5) -> ZBlend:
    """Blend weighting each model by its (train) IC, gating out IC <= floor
    (the lower limit on whether a model may influence the consensus)."""
    parts = [(predictors[name], max(0.0, ic - floor))
             for name, ic in ic_weights.items() if name in predictors and ic > floor]
    if not parts:  # degenerate: fall back to equal weights
        parts = [(p, 1.0) for p in predictors.values()]
    return ZBlend("ic_weighted", parts, clip=clip)


FEATURE_CANDIDATES: dict[str, str] = {
    "last1": "total_points__mean_1",
    "recent3": "total_points__mean_3",
    "recent5": "total_points__mean_5",
    "form_ewma5": "total_points__ewma_hl5",
    "season38": "total_points__mean_38",
    "ppg_career": "total_points__career_mean",
    "ict": "ict_index__ewma_hl5",
    "xgi90": "xgi90",
}


def feature_predictors() -> dict[str, FeaturePredictor]:
    return {name: FeaturePredictor(name, key) for name, key in FEATURE_CANDIDATES.items()}


def select_decorrelated(report, predictors: dict[str, Predictor],
                        max_corr: float = 0.9) -> list[str]:
    """Greedily keep the highest-IC predictors that aren't near-duplicates of an
    already-kept one (signal correlation < ``max_corr``). Uses ONLY the train
    report (signal_correlation + overall_ic), so it is leakage-free."""
    overall = getattr(report, "overall_ic", {}) or {}
    corr = getattr(report, "signal_correlation", {}) or {}
    ranked = sorted(predictors, key=lambda n: overall.get(n, 0.0), reverse=True)
    kept: list[str] = []
    for n in ranked:
        row = corr.get(n, {})
        if all(abs(row.get(k, 0.0)) < max_corr for k in kept):
            kept.append(n)
    return kept


def build_ensembles(report, predictors: dict[str, Predictor]) -> dict[str, Predictor]:
    """Construct ensembles from an analysis report (duck-typed: needs
    ``ic_weights``, ``overall_ic``, ``per_position_ic``). Weights come from the
    TRAIN report, so this stays causal when the report is built pre-window."""
    ens: dict[str, Predictor] = {}
    ens["ic_weighted"] = ic_weighted_blend(report.ic_weights, predictors, floor=0.0)
    ens["points_blend"] = points_blend(report.ic_weights, predictors, floor=0.0)
    # Only let ict_heavy pull in the frozen model when a model is actually in the
    # predictor set (keeps it leakage-free under --no-model evaluation).
    has_model = any(n.startswith("model:") for n in predictors)
    try:
        ens["ict_heavy"] = ict_heavy_blend(include_model=has_model)
    except Exception:
        pass
    top = sorted(report.overall_ic, key=lambda n: report.overall_ic[n],
                 reverse=True)[:3]
    ens["rank_top3"] = RankBlend("rank_top3",
                                 [(predictors[n], 1.0) for n in top if n in predictors])
    pos_w: dict[int, list[tuple[Predictor, float]]] = {}
    for pos in (1, 2, 3, 4):
        ranked = sorted(
            ((n, report.per_position_ic.get(n, {}).get(pos, float("nan")))
             for n in predictors),
            key=lambda kv: (kv[1] if kv[1] == kv[1] else -9.0), reverse=True)
        parts = [(predictors[n], ic) for n, ic in ranked[:2]
                 if ic == ic and ic > 0 and n in predictors]
        if not parts and ranked:
            parts = [(predictors[ranked[0][0]], 1.0)]
        pos_w[pos] = parts
    ens["per_position"] = PerPositionZBlend("per_position", pos_w)
    # Online Hedge: seeds from the train-season IC, then adapts within the eval
    # season from realised results (leakage-safe — see OnlineHedgeBlend docs).
    hedge_parts = [(predictors[n], max(0.0, report.ic_weights.get(n, 0.0)))
                   for n in predictors]
    ens["online_hedge"] = OnlineHedgeBlend("online_hedge", hedge_parts)
    # Decorrelated IC-weighted blend: prune near-duplicate members (e.g. the
    # several short-form signals) so the blend isn't diluted by collinearity.
    kept = select_decorrelated(report, predictors, max_corr=0.9)
    ens["decorr"] = ic_weighted_blend(report.ic_weights,
                                      {n: predictors[n] for n in kept}, floor=0.0)
    return ens


# -- serialise / reconstruct ensembles (for freezing as a versioned model) --
def _component_spec(p) -> dict:
    if isinstance(p, RecencyPredictor):
        return {"kind": "recency", "name": p.name, "metric": p.metric, "k": p.k}
    if isinstance(p, FeaturePredictor):
        return {"kind": "feature", "name": p.name, "feature_key": p.feature_key,
                "default": p.default}
    if isinstance(p, FrozenModelPredictor):
        return {"kind": "model", "name": p.name, "version": p.version,
                "target": p.target, "horizon": p.horizon}
    raise ValueError(f"cannot serialise component {type(p).__name__}")


def _component_from_spec(c: dict):
    if c["kind"] == "recency":
        return RecencyPredictor(c.get("name", "recency"), c.get("metric", "total_points"),
                                c.get("k", RECENCY_K))
    if c["kind"] == "feature":
        return FeaturePredictor(c["name"], c["feature_key"], c.get("default", 0.0))
    if c["kind"] == "model":
        return FrozenModelPredictor(version=c["version"], target=c.get("target", "points"),
                                    horizon=c.get("horizon", "next1"), name=c.get("name", ""))
    raise ValueError(f"unknown component kind {c.get('kind')!r}")


def ensemble_to_spec(name: str, ens) -> dict:
    """Serialise an ensemble predictor to a reloadable JSON spec."""
    if isinstance(ens, RankBlend):
        return {"type": "ensemble", "ensemble": "rank_blend", "name": name,
                "parts": [{"component": _component_spec(p), "weight": w}
                          for p, w in ens.parts]}
    if isinstance(ens, PointsBlend):
        return {"type": "ensemble", "ensemble": "points_blend", "name": name,
                "clip_hi": ens.clip_hi,
                "parts": [{"component": _component_spec(p), "weight": w}
                          for p, w in ens.parts]}
    if isinstance(ens, ZBlend):
        return {"type": "ensemble", "ensemble": "z_blend", "name": name, "clip": ens.clip,
                "parts": [{"component": _component_spec(p), "weight": w}
                          for p, w in ens.parts]}
    if isinstance(ens, PerPositionZBlend):
        return {"type": "ensemble", "ensemble": "per_position", "name": name,
                "clip": ens.clip,
                "pos_parts": {str(pos): [{"component": _component_spec(p), "weight": w}
                                         for p, w in parts]
                              for pos, parts in ens.pos_weights.items()}}
    raise ValueError(f"cannot serialise ensemble {type(ens).__name__}")


def predictor_from_spec(spec: dict) -> Predictor:
    """Reconstruct an ensemble predictor from its frozen spec."""
    kind = spec.get("ensemble")
    name = spec.get("name", kind or "ensemble")
    if kind == "rank_blend":
        return RankBlend(name, [(_component_from_spec(pt["component"]), pt["weight"])
                                for pt in spec["parts"]])
    if kind == "points_blend":
        return PointsBlend(name, [(_component_from_spec(pt["component"]), pt["weight"])
                                  for pt in spec["parts"]], clip_hi=spec.get("clip_hi", 15.0))
    if kind == "z_blend":
        return ZBlend(name, [(_component_from_spec(pt["component"]), pt["weight"])
                             for pt in spec["parts"]], clip=spec.get("clip", 2.5))
    if kind == "per_position":
        return PerPositionZBlend(
            name,
            {int(pos): [(_component_from_spec(pt["component"]), pt["weight"]) for pt in parts]
             for pos, parts in spec["pos_parts"].items()},
            clip=spec.get("clip", 2.5))
    raise ValueError(f"unknown ensemble spec {kind!r}")


def default_predictors(include_model: bool = True) -> dict[str, Predictor]:
    preds: dict[str, Predictor] = dict(feature_predictors())
    # Recency-adaptive points signal, available to the ensemble + comparisons.
    preds["recency"] = RecencyPredictor()
    if include_model:
        try:
            mp = FrozenModelPredictor("v1")
            preds[mp.name] = mp
        except Exception:
            pass
    return preds
