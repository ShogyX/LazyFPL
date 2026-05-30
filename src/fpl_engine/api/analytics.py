"""Predicted-vs-actual analytics for the Model Performance page (plan 10.2 / F4+).

Everything here reads *stored* serving predictions (``serving.predictions_player_gw``)
and joins them to realised outcomes (``normalised.targets.actual_points``), so the
numbers are honest backward-looking measures of how the served model actually did:

* :func:`prediction_accuracy` — per-GW rank IC / RMSE / MAE, per-position IC and a
  calibration (reliability) curve binning predicted xP against mean realised points.
* :func:`optimal_xi_history` — for each stored GW, the model's optimal XI (solved on
  predicted xP) vs the points that XI actually scored (captain doubled).
* :func:`hedge_weights` — the OnlineHedge ensemble's member-weight trajectory across a
  season, replayed with the exact leakage-safe update used in production.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from sqlalchemy import func, select

from ..db.engine import get_sessionmaker
from ..db.models import predictions_player_gw, targets
from ..model.stats import spearman_ic
from ..optimise import SquadOptimizer, load_candidates

_POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _sm():
    return get_sessionmaker()


def _actuals(season: str) -> dict[tuple[int, int], float]:
    """{(gw, element_id): summed realised points} — summed over DGW fixtures."""
    t = targets.c
    with _sm()() as s:
        rows = s.execute(
            select(t.gw, t.element_id, func.sum(t.actual_points))
            .where(t.season == season, t.actual_points.isnot(None))
            .group_by(t.gw, t.element_id)
        ).all()
    return {(int(r[0]), int(r[1])): float(r[2]) for r in rows}


def _stored_gws(season: str, version: str) -> list[int]:
    p = predictions_player_gw.c
    with _sm()() as s:
        rows = s.execute(
            select(p.gw).distinct()
            .where(p.model_version == version, p.season == season)
            .order_by(p.gw)
        ).all()
    return [int(r[0]) for r in rows]


def prediction_accuracy(season: str, version: str = "v1") -> dict:
    """Per-GW + per-position accuracy and a calibration curve from predictions⨝actuals."""
    p = predictions_player_gw.c
    with _sm()() as s:
        rows = s.execute(
            select(p.gw, p.element_id, p.element_type, p.xp_next1)
            .where(p.model_version == version, p.season == season,
                   p.xp_next1.isnot(None))
        ).all()
    actuals = _actuals(season)
    # Assemble aligned (pred, actual, gw, pos) — only players with a realised row.
    preds, acts, gws, poss = [], [], [], []
    for r in rows:
        key = (int(r.gw), int(r.element_id))
        if key not in actuals:
            continue
        preds.append(float(r.xp_next1))
        acts.append(actuals[key])
        gws.append(int(r.gw))
        poss.append(int(r.element_type) if r.element_type else 0)
    if not preds:
        return {"season": season, "version": version, "per_gw": [],
                "per_position": [], "calibration": [], "overall": None}

    P, A, G, Pos = (np.array(x) for x in (preds, acts, gws, poss))

    per_gw = []
    for gw in sorted(set(gws)):
        m = G == gw
        ic, _ = spearman_ic(P[m], A[m])
        err = P[m] - A[m]
        per_gw.append({
            "gw": int(gw), "n": int(m.sum()),
            "ic": _r(ic), "rmse": _r(float(np.sqrt(np.mean(err ** 2)))),
            "mae": _r(float(np.mean(np.abs(err)))),
            "mean_pred": _r(float(P[m].mean())), "mean_actual": _r(float(A[m].mean())),
        })

    per_position = []
    for pos in (1, 2, 3, 4):
        m = Pos == pos
        if m.sum() < 5:
            continue
        ic, _ = spearman_ic(P[m], A[m])
        err = P[m] - A[m]
        per_position.append({
            "position": _POS[pos], "n": int(m.sum()), "ic": _r(ic),
            "rmse": _r(float(np.sqrt(np.mean(err ** 2)))),
            "bias": _r(float(np.mean(err))),
        })

    # Calibration / reliability: bin predicted xP, compare mean predicted vs mean
    # realised. A well-calibrated model tracks the diagonal.
    calibration = []
    edges = [0, 1, 2, 3, 4, 5, 6, 8, 100]
    for lo, hi in zip(edges, edges[1:]):
        m = (P >= lo) & (P < hi)
        if m.sum() == 0:
            continue
        calibration.append({
            "bucket": f"{lo}–{hi if hi < 100 else '+'}", "n": int(m.sum()),
            "mean_pred": _r(float(P[m].mean())), "mean_actual": _r(float(A[m].mean())),
        })

    ic_all, _ = spearman_ic(P, A)
    err_all = P - A
    overall = {
        "n": int(P.size), "n_gws": len(set(gws)), "ic": _r(ic_all),
        "rmse": _r(float(np.sqrt(np.mean(err_all ** 2)))),
        "mae": _r(float(np.mean(np.abs(err_all)))),
        "bias": _r(float(np.mean(err_all))),
    }
    return {"season": season, "version": version, "per_gw": per_gw,
            "per_position": per_position, "calibration": calibration,
            "overall": overall}


def optimal_xi_history(season: str, version: str = "v1", budget: int = 1000) -> dict:
    """For each stored GW: optimal XI on predicted xP vs the points it actually scored."""
    actuals = _actuals(season)
    out = []
    for gw in _stored_gws(season, version):
        cands = load_candidates(season, gw, model_version=version)
        if not cands:
            continue
        sol = SquadOptimizer(budget=budget).solve(cands)
        if not sol.feasible:
            continue
        xi = [pk for pk in sol.picks if pk.is_start]
        cap = next((pk for pk in sol.picks if pk.is_captain), None)
        realised = 0.0
        for pk in xi:
            pts = actuals.get((gw, pk.id), 0.0)
            realised += pts * (2 if (cap and pk.id == cap.id) else 1)
        cap_pred = next((pk.xp for pk in xi if cap and pk.id == cap.id), 0.0)
        out.append({
            "gw": gw,
            "predicted_xi_xp": _r(float(sol.xi_xp)),
            "actual_points": _r(realised),
            "captain": cap.name if cap else None,
            "captain_pred": _r(float(cap_pred)),
            "captain_actual": _r(actuals.get((gw, cap.id), 0.0) if cap else 0.0),
        })
    totals = {
        "sum_predicted": _r(sum(o["predicted_xi_xp"] for o in out)),
        "sum_actual": _r(sum(o["actual_points"] for o in out)),
        "n_gws": len(out),
    } if out else None
    return {"season": season, "version": version, "gws": out, "totals": totals}


def _prior_season(season: str) -> str | None:
    try:
        a, b = season.split("-")
        return f"{int(a) - 1}-{int(b) - 1:02d}"
    except Exception:
        return None


@lru_cache(maxsize=16)
def hedge_weights(eval_season: str, train_season: str | None = None,
                  lo: int = 1, hi: int = 38, eta: float = 0.5) -> dict:
    """Replay the OnlineHedge member weights GW-by-GW across ``eval_season``.

    Mirrors production exactly: weights are seeded from the TRAIN season IC and
    each GW's weights are updated only from *earlier* GWs' realised results, so
    the trajectory shown is the leakage-safe one used to score live GWs.
    """
    from ..backtest.engine import Backtester
    from ..model.analysis import PredictorAnalysis
    from ..model.predictors import OnlineHedgeBlend, default_predictors

    train_season = train_season or _prior_season(eval_season)
    predictors = default_predictors(include_model=False)
    names = list(predictors)

    # Seed weights from the train-season IC (falls back to equal weights).
    ic_weights = {n: 0.0 for n in names}
    if train_season:
        try:
            rep = PredictorAnalysis().analyse(train_season, list(range(1, 39)), predictors)
            ic_weights = {n: rep.ic_weights.get(n, 0.0) for n in names}
        except Exception:
            pass

    hedge = OnlineHedgeBlend(
        "online_hedge", [(predictors[n], max(0.0, ic_weights.get(n, 0.0))) for n in names])
    hedge.reset()

    frames = Backtester(get_sessionmaker())._frames(eval_season, list(range(1, 39)))
    series = []
    for gw in sorted(frames):
        fr = frames[gw]
        items = [(eid, f.features, f.pos) for eid, f in fr.items()]
        if lo <= gw <= hi:
            series.append({"gw": int(gw),
                           "weights": {n: _r(w) for n, w in zip(names, hedge._w)}})
        hedge.observe(items, {eid: float(f.actual) for eid, f in fr.items()})
    return {"eval_season": eval_season, "train_season": train_season,
            "members": names, "series": series}


def _r(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if f == f else None  # NaN -> None
