"""Window bank over a player's appearance sequence (plan B.11).

Windows are computed over the player's ordered *match* sequence (skill travels
with matches, not calendar dates), so an injury gap simply means the trailing
window reaches further back in time. All aggregates use only the values passed
in — the panel builder is responsible for passing a strictly-causal prefix
(matches before the prediction deadline).

Representations (B.11): (a) multi-window levels; (b) level(38) + momentum
[short - long]. Career totals are passed in as running sums so the per-point
cost stays bounded (no O(n^2) rescans).
"""

from __future__ import annotations

from dataclasses import dataclass

LEVEL_WINDOWS: tuple[int, ...] = (1, 3, 5, 8, 12, 19, 38)  # 1 = last GW (baseline)
EWMA_HALFLIVES: tuple[int, ...] = (2, 5, 10, 20)
# Enough trailing points for the longest EWMA half-life to be accurate.
EWMA_LOOKBACK = 80


@dataclass(frozen=True)
class WindowConfig:
    levels: tuple[int, ...] = LEVEL_WINDOWS
    halflives: tuple[int, ...] = EWMA_HALFLIVES


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _ewma(values_newest_last: list[float], halflife: float) -> float | None:
    """EWMA over an appearance sequence, newest observation weighted most.

    ``values_newest_last`` is ordered oldest -> newest. Weight of the
    observation ``age`` steps before the newest is ``0.5 ** (age / halflife)``.
    """
    if not values_newest_last:
        return None
    decay = 0.5 ** (1.0 / halflife)
    weight = 1.0
    wsum = 0.0
    vsum = 0.0
    for x in reversed(values_newest_last):  # newest first, age 0,1,2,...
        vsum += weight * float(x)  # tolerate Decimal from Numeric columns
        wsum += weight
        weight *= decay
    return vsum / wsum if wsum else None


def window_features(
    recent_newest_last: list[float],
    *,
    career_sum: float | None = None,
    career_n: int | None = None,
    config: WindowConfig = WindowConfig(),
) -> dict[str, float | None]:
    """Compute the window bank for one metric.

    ``recent_newest_last`` holds the trailing values (oldest -> newest), at
    least the last ``EWMA_LOOKBACK``. ``career_sum``/``career_n`` carry the full
    history totals; if omitted they are derived from ``recent_newest_last``.
    """
    feats: dict[str, float | None] = {}
    n = len(recent_newest_last)
    feats["n"] = float(n)

    for w in config.levels:
        last = recent_newest_last[-w:] if n else []
        feats[f"mean_{w}"] = _mean(last)
        feats[f"sum_{w}"] = float(sum(last)) if last else None

    for h in config.halflives:
        feats[f"ewma_hl{h}"] = _ewma(recent_newest_last[-EWMA_LOOKBACK:], h)

    if career_sum is None or career_n is None:
        career_sum = float(sum(recent_newest_last))
        career_n = n
    feats["career_sum"] = float(career_sum) if career_n else None
    feats["career_mean"] = (career_sum / career_n) if career_n else None

    # Representation (b): momentum = short level - long level.
    short, long = feats.get("mean_5"), feats.get("mean_38")
    feats["momentum_5_38"] = (short - long) if (short is not None and long is not None) else None
    return feats


def per90(metric_sum: float | None, minutes_sum: float | None) -> float | None:
    if metric_sum is None or not minutes_sum:
        return None
    return metric_sum / minutes_sum * 90.0
