"""Devigging: recover true probabilities from bookmaker odds (plan B.8.1).

A bookmaker's decimal odds imply probabilities that sum to > 1 (the overround /
vig). Removing it recovers the bookmaker's true probability estimate.

  * ``proportional`` (a.k.a. multiplicative/normalisation): p_i = (1/o_i) / Σ(1/o_j)
  * ``shin``: solves for the insider-trading proportion z, a sharper devig used
    on two-/three-way markets.

For an exchange (Betfair) the fair price sits between the available back and lay
prices; ``betfair_fair_prob`` returns the mid implied probability.
"""

from __future__ import annotations

import math


def implied_prob(decimal_odds: float) -> float:
    """Raw implied probability of a single decimal-odds quote."""
    if decimal_odds is None or decimal_odds <= 1.0:
        raise ValueError(f"decimal odds must be > 1.0, got {decimal_odds!r}")
    return 1.0 / decimal_odds


def overround(odds: dict[str, float]) -> float:
    """Bookmaker margin: Σ implied probs (>1 means vig present)."""
    return sum(implied_prob(o) for o in odds.values())


def devig_proportional(odds: dict[str, float]) -> dict[str, float]:
    raw = {sel: implied_prob(o) for sel, o in odds.items()}
    total = sum(raw.values())
    return {sel: p / total for sel, p in raw.items()}


def devig_shin(odds: dict[str, float], tol: float = 1e-12,
               iterations: int = 200) -> dict[str, float]:
    """Shin (1992) devig: solve for the insider-trading proportion z.

    With book implied probs ``b_i = 1/o_i`` and ``B = Σ b_i``, the true
    probability is
        p_i(z) = ( sqrt(z^2 + 4(1-z) b_i^2 / B) - z ) / (2(1-z)).
    ``z`` is chosen so ``Σ p_i(z) = 1``. ``S(z)`` is monotonically decreasing
    from ``S(0)=sqrt(B) > 1`` toward 1, so we bisect on z ∈ [0, 0.5]. Falls back
    to proportional for degenerate inputs (single selection or no overround).
    """
    b = {sel: implied_prob(o) for sel, o in odds.items()}
    booksum = sum(b.values())
    if len(odds) < 2 or booksum <= 1.0:
        return devig_proportional(odds)

    def p_of(z: float, bi: float) -> float:
        denom = 2.0 * (1.0 - z)
        return (math.sqrt(z * z + 4.0 * (1.0 - z) * bi * bi / booksum) - z) / denom

    def total(z: float) -> float:
        return sum(p_of(z, bi) for bi in b.values())

    lo, hi = 0.0, 0.5
    if total(hi) > 1.0:  # extreme overround: root beyond 0.5, clamp
        z = hi
    else:
        for _ in range(iterations):
            mid = 0.5 * (lo + hi)
            if total(mid) > 1.0:   # S decreasing -> need larger z
                lo = mid
            else:
                hi = mid
            if hi - lo < tol:
                break
        z = 0.5 * (lo + hi)

    probs = {sel: max(p_of(z, b[sel]), 0.0) for sel in odds}
    s = sum(probs.values()) or 1.0
    return {sel: v / s for sel, v in probs.items()}


def devig(odds: dict[str, float], method: str = "proportional") -> dict[str, float]:
    """Devig a market's decimal odds -> true probabilities summing to 1."""
    if not odds:
        return {}
    if method == "proportional":
        return devig_proportional(odds)
    if method == "shin":
        return devig_shin(odds)
    raise ValueError(f"unknown devig method: {method!r}")


def betfair_fair_prob(back_price: float, lay_price: float) -> float:
    """Fair probability from an exchange back/lay pair (mid implied prob).

    Back odds are the best available to back (lower), lay odds the best to lay
    (higher); the fair price sits between them.
    """
    if back_price and lay_price:
        return (implied_prob(back_price) + implied_prob(lay_price)) / 2.0
    if back_price:
        return implied_prob(back_price)
    if lay_price:
        return implied_prob(lay_price)
    raise ValueError("need at least one of back_price / lay_price")
