"""Distributional captaincy (plan T5).

The component model produces *expected* rates (E[goals], E[assists], clean-sheet
probability, …). Collapsing those to a single xP loses the shape of the outcome
distribution — and, because the FPL scoring function is non-linear (the −1 per
two conceded is a floor, clean-sheet/appearance are step functions, bonus is
discrete), the linear expectation is a slightly biased estimate of the true
mean. This module Monte-Carlo samples each player's match from count models
(Negative-Binomial goals/assists, Poisson concessions/saves) and scores every
draw with the real rules, yielding:

* a non-linear-accurate EV,
* the ceiling / floor (90th / 10th percentile) and haul probability that a
  captaincy decision actually cares about.

Selection stays expected-value based (rank by ``ev``); we surface ceiling/floor
for transparency, not to chase variance — risk-taking captaincy is iced.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import training_rows
from .components import ExpectedComponents, build_components
from .scoring import CURRENT, DEF, GK, ScoringRules, dc_threshold

# A captained "haul" is a double-digit base return (≥10 → ≥20 with the armband);
# a "blank" is appearance-only or a no-show (≤2).
HAUL_PTS = 10
BLANK_PTS = 2
# Negative-Binomial dispersion (number of successes r): larger → closer to a
# Poisson. Match-to-match goal/assist counts are mildly overdispersed, so a
# moderate r keeps the mean exact while widening the ceiling tail realistically.
_R_GOALS = 6.0
_R_ASSISTS = 6.0
_DRAWS = 4000


@dataclass(frozen=True)
class CaptainDist:
    ev: float        # MC mean base points (non-linear-accurate, not ×2)
    floor: float     # 10th percentile
    median: float
    ceiling: float   # 90th percentile
    std: float
    haul: float      # P(base points >= HAUL_PTS)
    blank: float     # P(base points <= BLANK_PTS)
    n: int


def _nb(rng: np.random.Generator, mean: float, r: float, n: int) -> np.ndarray:
    """Negative-Binomial counts with the given mean and dispersion r.

    numpy's negative_binomial(r, p) counts failures before r successes with
    mean r(1−p)/p; setting p = r/(r+mean) makes the mean exactly ``mean`` and the
    variance mean + mean²/r (overdispersed relative to Poisson)."""
    mean = max(0.0, float(mean))
    if mean <= 1e-9:
        return np.zeros(n, dtype=int)
    return rng.negative_binomial(r, r / (r + mean), size=n)


def simulate(c: ExpectedComponents, rules: ScoringRules = CURRENT,
             n: int = _DRAWS, seed: int = 0) -> CaptainDist:
    """Monte-Carlo a single player's match and score every draw with ``rules``."""
    rng = np.random.default_rng(seed)
    et = c.element_type

    # Appearance ladder from one uniform so 60+ ⊆ appeared: u<p60 → 90', u<p_appear
    # → a ~30' cameo, else a no-show. (p60 ≤ p_appear by construction.)
    u = rng.random(n)
    appeared = u < c.p_appear
    long60 = u < c.p60
    ai = appeared.astype(int)

    goals = _nb(rng, c.e_goals, _R_GOALS, n) * ai
    assists = _nb(rng, c.e_assists, _R_ASSISTS, n) * ai

    # On-pitch concession rate; clean sheet ⇔ none conceded while playing 60+.
    lam = c.e_conceded / c.p_appear if c.p_appear > 1e-9 else 0.0
    conceded = rng.poisson(max(lam, 0.0), n) * ai
    clean = (conceded == 0) & long60

    pts = np.where(long60, rules.appearance_long,
                   np.where(appeared, rules.appearance_short, 0)).astype(float)
    pts += rules.goal.get(et, 0) * goals
    pts += rules.assist * assists
    pts += rules.clean_sheet.get(et, 0) * clean

    if et == GK:
        saves = rng.poisson(max(c.e_saves, 0.0), n) * ai
        pts += saves // rules.saves_per_point
    if et in (GK, DEF):
        pts -= conceded // rules.conceded_per_minus

    if rules.dc_enabled and dc_threshold(rules, et) is not None and c.p60 > 1e-9:
        # dc_prob = P(threshold & 60+); recover the conditional then re-gate on 60+.
        p_dc = min(1.0, c.dc_prob / c.p60)
        pts += rules.dc_points * ((rng.random(n) < p_dc) & long60)

    if c.e_bonus > 0:
        pts += np.minimum(rng.poisson(c.e_bonus, n), 3) * ai
    if c.e_yellow > 0:
        pts += rules.yellow * ((rng.random(n) < min(1.0, c.e_yellow)) * ai)

    return CaptainDist(
        ev=round(float(pts.mean()), 3),
        floor=round(float(np.percentile(pts, 10)), 1),
        median=round(float(np.percentile(pts, 50)), 1),
        ceiling=round(float(np.percentile(pts, 90)), 1),
        std=round(float(pts.std()), 3),
        haul=round(float((pts >= HAUL_PTS).mean()), 4),
        blank=round(float((pts <= BLANK_PTS).mean()), 4),
        n=n)


def captain_distributions(season: str, gw: int, ids: set[int], *,
                          sm: sessionmaker[Session] | None = None,
                          rules: ScoringRules = CURRENT, n: int = _DRAWS,
                          seed: int = 0) -> dict[int, CaptainDist]:
    """MC captain distribution for each of ``ids`` at ``(season, gw)``.

    Rates come from the same component model the served xP uses (causal trailing
    features + the minutes model). Each player gets a deterministic, decorrelated
    seed so results are stable across refreshes but independent across players.
    """
    from ..db.engine import get_sessionmaker
    from .minutes import MinutesModel, MinutesPrediction

    sm = sm or get_sessionmaker()
    minutes = MinutesModel(sm=sm).predict_gw(season, gw)
    tr = training_rows.c
    with sm() as s:
        rows = s.execute(
            select(tr.element_id, tr.element_type, tr.features).where(
                tr.season == season, tr.gw == gw, tr.element_id.in_(ids))
        ).all()
    out: dict[int, CaptainDist] = {}
    for r in rows:
        mins = minutes.get(r.element_id) or MinutesPrediction(0, 0, 0, 0)
        comps = build_components(r.element_type, r.features or {}, mins, rules)
        out[r.element_id] = simulate(comps, rules, n=n, seed=seed + int(r.element_id))
    return out
