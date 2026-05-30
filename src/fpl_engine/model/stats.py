"""Statistical primitives for the predictive-validity study (plan 4.1).

Spearman rank information coefficient (IC), per-season IC stability, and
Benjamini-Hochberg false-discovery-rate control. Pure, dependency-light
(numpy + scipy), unit-tested independently of the DB.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


def spearman_ic(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Spearman rho and p-value over pairwise-complete observations."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 5 or np.all(x[mask] == x[mask][0]):
        return float("nan"), float("nan")
    rho, p = stats.spearmanr(x[mask], y[mask])
    return float(rho), float(p)


def benjamini_hochberg(pvals: np.ndarray) -> np.ndarray:
    """BH-FDR adjusted q-values. NaN p-values map to NaN q-values."""
    p = np.asarray(pvals, dtype=float)
    out = np.full(p.shape, np.nan)
    finite = np.isfinite(p)
    m = int(finite.sum())
    if m == 0:
        return out
    idx = np.where(finite)[0]
    pv = p[idx]
    order = np.argsort(pv)
    ranked = pv[order]
    q = ranked * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]  # enforce monotonicity
    q = np.clip(q, 0.0, 1.0)
    adjusted = np.empty(m)
    adjusted[order] = q
    out[idx] = adjusted
    return out


@dataclass
class ICSummary:
    mean_ic: float
    sd_ic: float
    sign_stability: float  # fraction of seasons agreeing with the mean sign
    n_seasons: int


def per_season_ic(
    feature: np.ndarray, target: np.ndarray, seasons: np.ndarray
) -> ICSummary:
    """IC computed within each season, then summarised across seasons."""
    feature = np.asarray(feature, dtype=float)
    target = np.asarray(target, dtype=float)
    seasons = np.asarray(seasons)
    ics: list[float] = []
    for s in np.unique(seasons):
        m = seasons == s
        rho, _ = spearman_ic(feature[m], target[m])
        if np.isfinite(rho):
            ics.append(rho)
    if not ics:
        return ICSummary(float("nan"), float("nan"), float("nan"), 0)
    arr = np.array(ics)
    mean_ic = float(arr.mean())
    sd_ic = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    if mean_ic == 0:
        stability = 0.5
    else:
        stability = float(np.mean(np.sign(arr) == np.sign(mean_ic)))
    return ICSummary(mean_ic, sd_ic, stability, len(arr))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if mask.sum() == 0:
        return float("nan")
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))
