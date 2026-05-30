"""Source-weighted consensus true probabilities (plan B.8.3).

Combine each provider's devigged probabilities for a market into one consensus,
weighting the sharpest sources (Pinnacle no-vig, Betfair exchange) above soft
books. Sharp-vs-soft disagreement is itself signal; each consensus is tagged
with ``n_sources`` and ``sharp_present``.
"""

from __future__ import annotations

from dataclasses import dataclass

# Sources treated as sharp (Pinnacle no-vig / exchange / sharp aggregators).
SHARP_PROVIDERS = {"sharpapi", "betfair", "oddspapi", "sgo"}


@dataclass
class Quote:
    """One provider's devigged probabilities for a market (selection -> prob)."""
    provider: str
    probs: dict[str, float]
    sharp: bool | None = None  # inferred from provider if None

    def is_sharp(self) -> bool:
        return self.provider in SHARP_PROVIDERS if self.sharp is None else self.sharp


@dataclass
class ConsensusResult:
    probs: dict[str, float]
    n_sources: int
    sharp_present: bool
    method: str = "weighted"


class ConsensusBuilder:
    def __init__(self, sharp_weight: float = 3.0, soft_weight: float = 1.0):
        self.sharp_weight = sharp_weight
        self.soft_weight = soft_weight

    def combine(self, quotes: list[Quote]) -> ConsensusResult:
        if not quotes:
            return ConsensusResult({}, 0, False)
        selections: set[str] = set()
        for q in quotes:
            selections |= set(q.probs)

        num: dict[str, float] = {s: 0.0 for s in selections}
        den: dict[str, float] = {s: 0.0 for s in selections}
        for q in quotes:
            w = self.sharp_weight if q.is_sharp() else self.soft_weight
            for sel, p in q.probs.items():
                num[sel] += w * p
                den[sel] += w

        consensus = {sel: num[sel] / den[sel] for sel in selections if den[sel] > 0}
        total = sum(consensus.values())
        if total > 0:  # renormalise so the market's probabilities sum to 1
            consensus = {sel: p / total for sel, p in consensus.items()}

        return ConsensusResult(
            probs=consensus,
            n_sources=len(quotes),
            sharp_present=any(q.is_sharp() for q in quotes),
        )
