"""Persist normalised odds and build consensus true probabilities (plan 5.3).

``write_market`` devigs a provider's decimal-odds market on the way in;
``write_betfair`` stores exchange back/lay with a normalised fair probability;
``build_consensus`` reads the latest quote per provider for an (event, market)
and writes one source-weighted ``true_probabilities`` row per selection.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import odds_snapshots, true_probabilities
from ..logging_setup import get_logger
from .consensus import SHARP_PROVIDERS, ConsensusBuilder, ConsensusResult, Quote
from .devig import betfair_fair_prob, devig

log = get_logger(__name__)


class OddsStore:
    def __init__(self, sm: sessionmaker[Session] | None = None,
                 builder: ConsensusBuilder | None = None):
        self._sm = sm or get_sessionmaker()
        self._builder = builder or ConsensusBuilder()

    def write_market(self, provider: str, event_ref: str, market: str,
                     odds: dict[str, float], *, method: str = "proportional",
                     sharp: bool | None = None,
                     captured_at: datetime | None = None) -> int:
        probs = devig(odds, method=method)
        is_sharp = provider in SHARP_PROVIDERS if sharp is None else sharp
        ts = captured_at or datetime.now(timezone.utc)
        rows = [{
            "provider": provider, "event_ref": event_ref, "market": market,
            "selection": sel, "decimal_odds": odds[sel],
            "no_vig_prob": round(probs[sel], 6), "sharp": is_sharp, "captured_at": ts,
        } for sel in odds]
        with self._sm() as s:
            s.execute(odds_snapshots.insert(), rows)
            s.commit()
        return len(rows)

    def write_betfair(self, event_ref: str, market: str,
                      quotes: dict[str, tuple[float, float]], *,
                      provider: str = "betfair",
                      captured_at: datetime | None = None) -> int:
        """quotes: selection -> (back_price, lay_price). Fair probs normalised."""
        fair = {sel: betfair_fair_prob(b, l) for sel, (b, l) in quotes.items()}
        total = sum(fair.values()) or 1.0
        ts = captured_at or datetime.now(timezone.utc)
        rows = [{
            "provider": provider, "event_ref": event_ref, "market": market,
            "selection": sel, "back_price": quotes[sel][0], "lay_price": quotes[sel][1],
            "no_vig_prob": round(fair[sel] / total, 6), "sharp": True, "captured_at": ts,
        } for sel in quotes]
        with self._sm() as s:
            s.execute(odds_snapshots.insert(), rows)
            s.commit()
        return len(rows)

    def _latest_quotes(self, s: Session, event_ref: str, market: str) -> list[Quote]:
        o = odds_snapshots.c
        rows = s.execute(
            select(o.provider, o.selection, o.no_vig_prob, o.sharp, o.captured_at)
            .where(o.event_ref == event_ref, o.market == market,
                   o.no_vig_prob.isnot(None))
            .order_by(o.captured_at.desc())
        ).all()
        latest_ts: dict[str, datetime] = {}
        by_provider: dict[str, dict[str, float]] = {}
        sharp_flag: dict[str, bool] = {}
        for r in rows:
            # keep only the most recent capture per provider
            if r.provider not in latest_ts:
                latest_ts[r.provider] = r.captured_at
            if r.captured_at != latest_ts[r.provider]:
                continue
            by_provider.setdefault(r.provider, {})[r.selection] = float(r.no_vig_prob)
            sharp_flag[r.provider] = bool(r.sharp)
        return [Quote(provider=p, probs=probs, sharp=sharp_flag[p])
                for p, probs in by_provider.items()]

    def build_consensus(self, event_ref: str, market: str,
                        captured_at: datetime | None = None) -> ConsensusResult:
        ts = captured_at or datetime.now(timezone.utc)
        with self._sm() as s:
            quotes = self._latest_quotes(s, event_ref, market)
            result = self._builder.combine(quotes)
            rows = [{
                "event_ref": event_ref, "market": market, "selection": sel,
                "captured_at": ts, "true_prob": round(prob, 6),
                "n_sources": result.n_sources, "sharp_present": result.sharp_present,
                "method": result.method,
            } for sel, prob in result.probs.items()]
            if rows:
                s.execute(true_probabilities.insert(), rows)
                s.commit()
        log.info("consensus built", extra={"event": event_ref, "market": market,
                                           "n_sources": result.n_sources,
                                           "sharp_present": result.sharp_present})
        return result
