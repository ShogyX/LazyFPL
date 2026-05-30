"""Provider registry: base URLs, user-agent, and free-tier rate caps.

Rate caps — not data availability — govern the ingest design (plan A.3/B.8.3).
Limits below reflect the documented free tiers; tune as terms change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

USER_AGENT = "fpl-engine/0.1 (+self-hosted; personal non-commercial use)"


@dataclass(frozen=True)
class RateLimits:
    """Free-tier caps. ``None`` means no explicit cap for that window."""

    per_minute: int | None = None
    per_hour: int | None = None
    per_day: int | None = None
    per_month: int | None = None

    def configured(self) -> dict[str, int]:
        out: dict[str, int] = {}
        if self.per_minute is not None:
            out["minute"] = self.per_minute
        if self.per_hour is not None:
            out["hour"] = self.per_hour
        if self.per_day is not None:
            out["day"] = self.per_day
        if self.per_month is not None:
            out["month"] = self.per_month
        return out


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    limits: RateLimits = field(default_factory=RateLimits)
    headers: dict[str, str] = field(default_factory=dict)


# Documented free-tier caps from FPL_MASTER_PLAN_v2.md B.1 / B.8.2.
PROVIDERS: dict[str, ProviderConfig] = {
    # Official FPL API: no published cap; self-rate-limit politely.
    "fpl": ProviderConfig(
        name="fpl",
        base_url="https://fantasy.premierleague.com/api",
        limits=RateLimits(per_minute=30),
    ),
    "sharpapi": ProviderConfig(
        name="sharpapi",
        base_url="https://api.sharpapi.io",
        limits=RateLimits(per_minute=12),
    ),
    "sgo": ProviderConfig(
        name="sgo",
        base_url="https://api.sportsgameodds.com",
        limits=RateLimits(per_day=200),  # conservative; object-limited tier
    ),
    "oddspapi": ProviderConfig(
        name="oddspapi",
        base_url="https://api.oddspapi.io",
        limits=RateLimits(per_month=250),
    ),
    "oddsapi_io": ProviderConfig(
        name="oddsapi_io",
        base_url="https://api.odds-api.io",
        limits=RateLimits(per_hour=100),
    ),
    "api_football": ProviderConfig(
        name="api_football",
        base_url="https://v3.football.api-sports.io",
        limits=RateLimits(per_day=100),
    ),
    "betfair": ProviderConfig(
        name="betfair",
        base_url="https://api.betfair.com/exchange",
        limits=RateLimits(per_minute=20),
    ),
    "clubelo": ProviderConfig(
        name="clubelo",
        base_url="http://api.clubelo.com",
        limits=RateLimits(per_minute=10),
    ),
    "understat": ProviderConfig(
        name="understat",
        base_url="https://understat.com",
        limits=RateLimits(per_minute=6),
    ),
    "fbref": ProviderConfig(
        name="fbref",
        base_url="https://fbref.com",
        limits=RateLimits(per_minute=6),  # polite; FBref rate-limits hard
    ),
    "vaastav": ProviderConfig(
        name="vaastav",
        base_url="https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master",
        limits=RateLimits(per_minute=120),  # static GitHub CDN, no documented cap
    ),
}


def get_provider(name: str) -> ProviderConfig:
    try:
        return PROVIDERS[name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"unknown provider: {name!r}") from exc
