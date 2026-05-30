"""Prediction service (plan 6.x): serve expected points from frozen weights.

Loads a frozen ``model_registry`` spec and applies each per-position cell
(impute -> standardise -> Elastic-Net linear combination -> shrinkage blend
toward the season baseline) to the strictly-causal ``training_rows`` features
for a given (season, GW). Writes ``serving.predictions_player_gw``.

This is the v1 points-direct predictor; a component-wise decomposition (C.1)
is a later refinement that swaps in component sub-models behind the same API.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import predictions_player_gw, training_rows
from ..logging_setup import get_logger
from .freeze import load_spec

log = get_logger(__name__)


@dataclass
class PredictResult:
    model_version: str
    season: str
    gw: int
    n_players: int


def _apply_cell(cell: dict, feats: dict) -> float | None:
    """Apply a frozen linear cell to a feature dict, with shrinkage blend."""
    cols = cell["features"]
    coef = cell["coef"]
    med = cell["impute_median"]
    mean = cell["scale_mean"]
    std = cell["scale_std"]
    pred = float(cell.get("intercept") or 0.0)
    for j, col in enumerate(cols):
        v = feats.get(col)
        if v is None:
            v = med[j]
        if v is None:  # all-NaN guard (shouldn't happen post-freeze)
            continue
        s = std[j] if std[j] not in (None, 0) else 1.0
        m = mean[j] if mean[j] is not None else 0.0
        scaled = (float(v) - m) / s
        c = coef[j] if coef[j] is not None else 0.0
        pred += c * scaled

    lam = float(cell.get("shrink_lambda") or 0.0)
    base_feat = cell.get("baseline_feature")
    if lam > 0 and base_feat is not None and feats.get(base_feat) is not None:
        pred = (1 - lam) * pred + lam * float(feats[base_feat])
    return pred


class Predictor:
    def __init__(self, sm: sessionmaker[Session] | None = None, version: str = "v1"):
        self._sm = sm or get_sessionmaker()
        self.version = version
        spec = load_spec(version, sm=self._sm)
        if spec is None:
            raise ValueError(f"no frozen spec for model version {version!r}")
        self._cells = {
            (c["position"], c["target"], c["horizon"]): c for c in spec["cells"]
        }

    def predict_gw(self, season: str, gw: int) -> PredictResult:
        tr = training_rows.c
        with self._sm() as s:
            rows = s.execute(
                select(tr.player_key, tr.element_id, tr.element_type, tr.features).where(
                    tr.season == season, tr.gw == gw,
                    tr.element_type.in_([1, 2, 3, 4]),
                )
            ).all()

            out: list[dict] = []
            for r in rows:
                et = r.element_type
                feats = r.features
                xp1 = self._cell_pred(et, "points", "next1", feats)
                xp6 = self._cell_pred(et, "points", "next6", feats)
                mins = self._cell_pred(et, "minutes", "next1", feats)
                out.append({
                    "model_version": self.version, "season": season, "gw": gw,
                    "player_key": r.player_key, "element_id": r.element_id,
                    "element_type": et,
                    "xp_next1": _round(xp1), "xp_next6": _round(xp6),
                    "pred_minutes": _clamp_minutes(mins),
                    "breakdown": {"xp_next1": _round(xp1), "xp_next6": _round(xp6),
                                  "pred_minutes": _round(mins)},
                })
            self._write(s, out)
            s.commit()
        log.info("predictions written", extra={"version": self.version, "season": season,
                                               "gw": gw, "players": len(out)})
        return PredictResult(self.version, season, gw, len(out))

    def _cell_pred(self, position: int, target: str, horizon: str, feats: dict):
        cell = self._cells.get((position, target, horizon))
        if cell is None:
            return None
        return _apply_cell(cell, feats)

    def _write(self, s: Session, rows: list[dict]) -> None:
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            if not chunk:
                continue
            stmt = insert(predictions_player_gw).values(chunk)
            update = {c: stmt.excluded[c] for c in chunk[0] if c not in
                      ("model_version", "season", "gw", "player_key")}
            s.execute(stmt.on_conflict_do_update(
                index_elements=["model_version", "season", "gw", "player_key"], set_=update))


class EnsembleServer:
    """Serve an ensemble (v2) model: cohort-normalised xP over the GW's players,
    with minutes borrowed from the linear ``minutes_version`` (default v1)."""

    def __init__(self, sm: sessionmaker[Session] | None = None, version: str = "v2"):
        from .predictors import FrozenModelPredictor, predictor_from_spec
        self._sm = sm or get_sessionmaker()
        self.version = version
        spec = load_spec(version, sm=self._sm)
        if spec is None or spec.get("type") != "ensemble":
            raise ValueError(f"no ensemble spec for version {version!r}")
        self._predictor = predictor_from_spec(spec)
        self._calib = spec.get("calibration") or {}  # {str(pos): [intercept, slope]}
        try:  # minutes from the linear model if present, else omit
            self._minutes = FrozenModelPredictor(version=spec.get("minutes_version", "v1"),
                                                 target="minutes", horizon="next1")
        except Exception:
            self._minutes = None

    def predict_gw(self, season: str, gw: int) -> PredictResult:
        tr = training_rows.c
        with self._sm() as s:
            rows = s.execute(
                select(tr.element_id, tr.player_key, tr.element_type, tr.features).where(
                    tr.season == season, tr.gw == gw, tr.element_type.in_([1, 2, 3, 4]))
            ).all()
            items = [(r.element_id, r.features, r.element_type) for r in rows]
            scores = self._predictor.score_frame(items)
            # xP is in points units if the model is a PointsBlend or carries a
            # fitted score->points calibration (rank/z blends).
            calibrated = (self._predictor.__class__.__name__ == "PointsBlend"
                          or bool(self._calib))
            out = []
            for r in rows:
                xp = scores.get(r.element_id)
                cal = self._calib.get(str(r.element_type))
                if cal is not None and xp is not None:
                    xp = max(0.0, cal[0] + cal[1] * xp)   # raw score -> points
                mins = (self._minutes.score(r.features, r.element_type)
                        if self._minutes is not None else None)
                out.append({
                    "model_version": self.version, "season": season, "gw": gw,
                    "player_key": r.player_key, "element_id": r.element_id,
                    "element_type": r.element_type,
                    "xp_next1": _round(xp),
                    # no separate 6-GW signal; planner sums per-GW xp_next1
                    "xp_next6": None,
                    "pred_minutes": _clamp_minutes(mins),
                    "breakdown": {"ensemble_score": _round(xp),
                                  "calibrated_points": calibrated},
                })
            Predictor._write(self, s, out)  # reuse the upsert
            s.commit()
        log.info("ensemble predictions written", extra={
            "version": self.version, "season": season, "gw": gw, "players": len(out)})
        return PredictResult(self.version, season, gw, len(out))


def prediction_server(version: str = "v1", sm: sessionmaker[Session] | None = None):
    """Return the right server for a model version: linear (v1-style cells) or
    ensemble (v2-style spec)."""
    spec = load_spec(version, sm=sm)
    if spec is not None and spec.get("type") == "ensemble":
        return EnsembleServer(sm=sm, version=version)
    return Predictor(sm=sm, version=version)


def _round(v) -> float | None:
    if v is None:
        return None
    f = float(v)
    if f != f:  # NaN -> None, so a degenerate feature/weight never reaches the
        return None  # stored prediction or the MILP optimiser as NaN
    return round(f, 4)


def _clamp_minutes(v) -> float | None:
    if v is None:
        return None
    f = float(v)
    if f != f:  # NaN guard
        return None
    return round(min(max(f, 0.0), 120.0), 2)
