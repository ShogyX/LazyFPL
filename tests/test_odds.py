"""Odds devig + source-weighted consensus."""

import pytest
from sqlalchemy import select

from fpl_engine.db.models import odds_snapshots, true_probabilities
from fpl_engine.odds import (
    ConsensusBuilder,
    OddsStore,
    Quote,
    betfair_fair_prob,
    devig,
    implied_prob,
    overround,
)
from fpl_engine.odds.devig import devig_shin


def test_implied_prob_and_overround():
    assert implied_prob(2.0) == 0.5
    # a 1X2 market priced with vig sums to > 1
    odds = {"home": 2.0, "draw": 3.5, "away": 4.0}
    assert overround(odds) > 1.0
    with pytest.raises(ValueError):
        implied_prob(1.0)


def test_devig_proportional_sums_to_one_and_removes_vig():
    odds = {"home": 2.0, "draw": 3.5, "away": 4.0}
    p = devig(odds, "proportional")
    assert abs(sum(p.values()) - 1.0) < 1e-9
    # favourite keeps the highest probability; all strictly below raw implied
    assert p["home"] > p["draw"] > p["away"]
    assert p["home"] < implied_prob(2.0)   # vig removed -> lower than raw


def test_devig_shin_sums_to_one():
    odds = {"home": 1.5, "away": 2.6}
    p = devig_shin(odds)
    assert abs(sum(p.values()) - 1.0) < 1e-9
    assert p["home"] > p["away"]


def test_devig_shin_is_small_favourite_longshot_adjustment():
    # Shin should sum to 1 and apply only a SMALL favourite-longshot tilt vs
    # proportional (the broken z-oscillation version inflated the favourite by
    # ~0.1, which this pins against).
    odds = {"home": 2.0, "draw": 3.5, "away": 4.0}
    shin = devig_shin(odds)
    prop = devig(odds, "proportional")
    assert abs(sum(shin.values()) - 1.0) < 1e-9
    # favourite nudged up, longshot down, but only slightly (< 0.03)
    assert shin["home"] >= prop["home"]
    assert abs(shin["home"] - prop["home"]) < 0.03
    assert shin["away"] <= prop["away"]


def test_betfair_fair_prob_between_back_and_lay():
    # back 2.0 (implied .5), lay 2.5 (implied .4) -> fair .45
    fair = betfair_fair_prob(2.0, 2.5)
    assert abs(fair - 0.45) < 1e-9


def test_consensus_weights_sharp_sources_higher():
    # sharp says home 0.60, soft says home 0.40; consensus should lean sharp.
    sharp = Quote("betfair", {"home": 0.60, "away": 0.40}, sharp=True)
    soft = Quote("api_football", {"home": 0.40, "away": 0.60}, sharp=False)
    res = ConsensusBuilder(sharp_weight=3.0, soft_weight=1.0).combine([sharp, soft])
    assert abs(sum(res.probs.values()) - 1.0) < 1e-9
    assert res.n_sources == 2
    assert res.sharp_present is True
    # weighted mean = (3*.6 + 1*.4)/4 = 0.55 for home (pre-renormalisation)
    assert res.probs["home"] > 0.5


def test_consensus_flags_no_sharp():
    soft = Quote("api_football", {"home": 0.5, "away": 0.5}, sharp=False)
    res = ConsensusBuilder().combine([soft])
    assert res.sharp_present is False
    assert res.n_sources == 1


def test_store_builds_consensus_true_probabilities(sm):
    store = OddsStore(sm=sm)
    # soft book (vig) + sharp book (vig) on the same 1X2 market
    store.write_market("api_football", "evt1", "1x2",
                       {"home": 2.1, "draw": 3.4, "away": 3.6})
    store.write_market("sharpapi", "evt1", "1x2",
                       {"home": 1.9, "draw": 3.6, "away": 4.2})
    store.write_betfair("evt1", "1x2",
                        {"home": (1.95, 2.0), "draw": (3.5, 3.6), "away": (4.0, 4.2)})

    res = store.build_consensus("evt1", "1x2")
    assert res.n_sources == 3
    assert res.sharp_present is True
    assert abs(sum(res.probs.values()) - 1.0) < 1e-9

    with sm() as s:
        snaps = s.execute(select(odds_snapshots).where(
            odds_snapshots.c.event_ref == "evt1")).all()
        tps = s.execute(select(true_probabilities).where(
            true_probabilities.c.event_ref == "evt1")).all()
    assert len(snaps) == 9          # 3 providers x 3 selections
    assert len(tps) == 3
    assert all(t.n_sources == 3 and t.sharp_present for t in tps)
    # stored probs are rounded to 6dp each, so allow per-row rounding slack
    assert abs(sum(float(t.true_prob) for t in tps) - 1.0) < 1e-4
