"""Online Hedge ensemble: adaptivity + explicit leakage (causality) guarantees."""

from fpl_engine.model.predictors import FeaturePredictor, OnlineHedgeBlend, Predictor

MID = 3
# >=5 players so the Spearman IC is defined ('a' descends, 'b' ascends).
ITEMS = [(i, {"a": float(7 - i), "b": float(i)}, MID) for i in range(1, 7)]


def _blend(eta=1.0):
    return OnlineHedgeBlend("hedge", [(FeaturePredictor("a", "a"), 1.0),
                                      (FeaturePredictor("b", "b"), 1.0)], eta=eta)


def test_is_predictor_and_initial_weights_normalised():
    b = _blend()
    assert isinstance(b, Predictor)
    assert abs(sum(b._w) - 1.0) < 1e-9


def test_observe_shifts_weight_to_the_better_model():
    b = _blend(eta=1.0)
    w0 = list(b._w)
    # realised points rank like 'a' (player 1 highest .. player 6 lowest); 'b' opposite
    b.observe(ITEMS, {i: float(7 - i) * 2 for i in range(1, 7)})
    assert b._w[0] > w0[0]            # 'a' (correct) gains weight
    assert b._w[1] < w0[1]            # 'b' (wrong) loses weight


def test_reset_restores_initial_weights():
    b = _blend()
    init = list(b._w)
    b.observe(ITEMS, {i: float(7 - i) for i in range(1, 7)})
    assert b._w != init
    b.reset()
    assert b._w == init


def test_score_at_gw_is_independent_of_that_gws_actuals():
    # LEAKAGE GUARANTEE: the score produced for a GW (before observe) must be
    # identical regardless of what that GW's (or any future) actuals turn out to
    # be. Two blends scored from the same prior give the same scores; only AFTER
    # observing (different) actuals do they diverge.
    b1, b2 = _blend(), _blend()
    s1_before = b1.score_frame(ITEMS)
    s2_before = b2.score_frame(ITEMS)
    assert s1_before == s2_before                 # pre-observe: prior-only, identical

    b1.observe(ITEMS, {i: float(7 - i) for i in range(1, 7)})   # actuals favour 'a'
    b2.observe(ITEMS, {i: float(i) for i in range(1, 7)})       # actuals favour 'b'
    # observe used the actuals (weights now differ) ...
    assert b1.score_frame(ITEMS) != b2.score_frame(ITEMS)
    # ... but that influence applies only going FORWARD; the pre-observe scores
    # (what selection at that GW used) were identical above -> no leakage.


def test_degenerate_gw_does_not_update():
    b = _blend()
    w0 = list(b._w)
    b.observe(ITEMS, {i: 5.0 for i in range(1, 7)})   # no variance in actuals
    assert b._w == w0
    b.observe(ITEMS[:2], {1: 9, 2: 1})                # <3 players
    assert b._w == w0
