"""Free-tier odds provider integrations (plan B.8.2).

Each ingestor is **key-gated**: disabled (a no-op that logs) until the operator
adds that provider's free-tier key to the secrets vault (.env, ``FPL_*``). When
enabled it fetches through the shared budget-aware :class:`FetchClient`, parses
the provider's response into per-bookmaker quotes, and writes them to the odds
layer (devig on write) via :class:`OddsStore`. Consensus is then built per
event/market.

Auth schemes (free tiers):
  * api_football  — header ``x-apisports-key``
  * oddsapi_io    — query param ``apiKey``      (The-Odds-API-compatible shape)
  * sharpapi      — header ``Authorization: Bearer`` (Pinnacle no-vig)
  * sgo           — header ``X-Api-Key``         (player props)
  * oddspapi      — query param ``apiKey``
  * betfair       — headers ``X-Application`` + ``X-Authentication`` (session)

Parsers target each provider's documented response shape; verify against a live
response when first activating a provider.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings, get_settings
from ..logging_setup import get_logger
from ..odds.store import OddsStore
from .fetch import FetchClient

log = get_logger(__name__)

# Bookmaker names treated as sharp for consensus weighting. NB: quotes are
# stored with provider=<book name>, and the `sharp` boolean computed here is
# persisted and honoured by the consensus builder, so this book-level set —
# not consensus.SHARP_PROVIDERS (which is aggregator-level) — governs sharpness
# for provider-ingested rows.
SHARP_BOOK_NAMES = {"pinnacle", "betfair", "betfair exchange"}
_DRAW_LABELS = {"draw", "tie", "x"}

# 1X2 selection name normalisation.
_SEL = {"home": "Home", "draw": "Draw", "away": "Away"}


def auth_for(provider: str, settings: Settings) -> tuple[dict, dict, bool]:
    """Return (extra_headers, extra_params, key_present) for a provider."""
    def secret(v):
        return v.get_secret_value() if v is not None else None

    if provider == "api_football":
        k = secret(settings.api_football_key)
        return ({"x-apisports-key": k} if k else {}), {}, bool(k)
    if provider == "sharpapi":
        k = secret(settings.sharpapi_key)
        return ({"Authorization": f"Bearer {k}"} if k else {}), {}, bool(k)
    if provider == "sgo":
        k = secret(settings.sgo_key)
        return ({"X-Api-Key": k} if k else {}), {}, bool(k)
    if provider == "oddspapi":
        k = secret(settings.oddspapi_key)
        return {}, ({"apiKey": k} if k else {}), bool(k)
    if provider == "oddsapi_io":
        k = secret(settings.oddsapi_io_key)
        return {}, ({"apiKey": k} if k else {}), bool(k)
    if provider == "betfair":
        # Betfair Exchange also needs an interactive-login session token
        # (X-Authentication); the delayed app key alone is not sufficient, so a
        # login flow must be added before this provider is fully live.
        app = secret(settings.betfair_app_key)
        return ({"X-Application": app} if app else {}), {}, bool(app)
    return {}, {}, False


@dataclass
class Quote:
    event_ref: str
    book: str
    market: str
    odds: dict[str, float]
    sharp: bool


def parse_api_football_1x2(payload: dict) -> list[Quote]:
    """API-Football /odds response -> per-bookmaker 1X2 quotes."""
    out: list[Quote] = []
    for entry in payload.get("response", []):
        fixture = entry.get("fixture", {}).get("id") or entry.get("fixture")
        if fixture is None:
            continue
        for bm in entry.get("bookmakers", []):
            book = str(bm.get("name", "")).lower()
            for bet in bm.get("bets", []):
                if str(bet.get("name", "")).lower() not in ("match winner", "1x2"):
                    continue
                odds: dict[str, float] = {}
                for v in bet.get("values", []):
                    label = str(v.get("value", "")).lower()
                    sel = _SEL.get(label)
                    try:
                        if sel:
                            odds[sel] = float(v.get("odd"))
                    except (TypeError, ValueError):
                        continue
                if len(odds) >= 2:
                    out.append(Quote(str(fixture), book, "1x2", odds,
                                     book in SHARP_BOOK_NAMES))
    return out


def parse_theoddsapi_h2h(payload: list, *, market: str = "1x2") -> list[Quote]:
    """The-Odds-API / odds-api.io h2h response -> per-bookmaker 1X2 quotes."""
    out: list[Quote] = []
    for event in payload or []:
        ev = str(event.get("id", ""))
        home, away = event.get("home_team"), event.get("away_team")
        for bm in event.get("bookmakers", []):
            book = str(bm.get("key") or bm.get("title", "")).lower()
            for mk in bm.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                odds: dict[str, float] = {}
                for o in mk.get("outcomes", []):
                    name, price = o.get("name"), o.get("price")
                    try:
                        price = float(price)
                    except (TypeError, ValueError):
                        continue
                    if name == home:
                        odds["Home"] = price
                    elif name == away:
                        odds["Away"] = price
                    elif str(name).strip().lower() in _DRAW_LABELS:
                        odds["Draw"] = price
                    else:  # unrecognised name: skip rather than mislabel as Draw
                        log.warning("unmapped odds outcome", extra={
                            "event": ev, "book": book, "outcome_name": name})
                if len(odds) >= 2:
                    out.append(Quote(ev, book, market, odds, book in SHARP_BOOK_NAMES))
    return out


class OddsIngestor:
    """Key-gated odds ingestor for one provider."""

    def __init__(self, provider: str, parser, *, fetch: FetchClient | None = None,
                 store: OddsStore | None = None, settings: Settings | None = None):
        self.provider = provider
        self._parser = parser
        self._settings = settings or get_settings()
        self._fetch = fetch or FetchClient()
        self._store = store or OddsStore()
        self._headers, self._params, self.enabled = auth_for(provider, self._settings)

    def ingest(self, path: str, *, params: dict | None = None) -> int:
        """Fetch + parse + store. Returns the number of quotes written."""
        if not self.enabled:
            log.info("odds provider disabled (no key)", extra={"provider": self.provider})
            return 0
        merged = {**self._params, **(params or {})}
        res = self._fetch.get(self.provider, path, params=merged,
                              extra_headers=self._headers)
        if res.status_code != 200:
            log.warning("odds fetch failed", extra={"provider": self.provider,
                                                    "status": res.status_code})
            return 0
        return self.store_quotes(self._parser(res.payload))

    def store_quotes(self, quotes: list[Quote]) -> int:
        """Write parsed quotes to the odds layer (devig on write)."""
        n = 0
        for q in quotes:
            self._store.write_market(q.book, q.event_ref, q.market, q.odds,
                                     sharp=q.sharp)
            n += 1
        return n


def build_enabled(fetch: FetchClient, store: OddsStore,
                  settings: Settings | None = None) -> list[OddsIngestor]:
    """All provider ingestors whose key is present."""
    settings = settings or get_settings()
    specs = [
        ("api_football", parse_api_football_1x2),
        ("oddsapi_io", parse_theoddsapi_h2h),
        ("sharpapi", parse_theoddsapi_h2h),
        ("oddspapi", parse_theoddsapi_h2h),
    ]
    out = []
    for provider, parser in specs:
        ing = OddsIngestor(provider, parser, fetch=fetch, store=store, settings=settings)
        if ing.enabled:
            out.append(ing)
    return out
