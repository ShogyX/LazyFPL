"""Ensemble predictors: cohort normalisation, clip bounds, gating (no DB)."""

from fpl_engine.model.predictors import (
    FeaturePredictor,
    PerPositionZBlend,
    PointsBlend,
    RankBlend,
    ZBlend,
    _ranks,
    _zscores,
    ensemble_to_spec,
    ic_weighted_blend,
    ict_heavy_blend,
    predictor_from_spec,
)

MID, FWD = 3, 4


def test_zscores_center_and_spread():
    z = _zscores({1: 1.0, 2: 3.0, 3: 5.0})
    assert abs(z[2]) < 1e-9          # middle ~ 0
    assert z[1] < 0 < z[3]


def test_ranks_percentile():
    r = _ranks({1: 10, 2: 20, 3: 30})
    assert r[1] == 0.0 and r[3] == 1.0 and r[2] == 0.5


def test_zblend_clip_bounds_a_models_impact():
    # player 1 is a massive outlier in feature 'a'; the clip caps its influence.
    A = FeaturePredictor("A", "a")
    items = [(1, {"a": 100.0}, MID), (2, {"a": 0.0}, MID),
             (3, {"a": 0.0}, MID), (4, {"a": 0.0}, MID)]
    big = ZBlend("x", [(A, 1.0)], clip=5.0).score_frame(items)
    small = ZBlend("x", [(A, 1.0)], clip=0.5).score_frame(items)
    assert small[1] <= 0.5 + 1e-9     # clipped to the upper limit
    assert small[1] < big[1]          # tighter clip = less dominance


def test_zblend_zero_weight_ignored():
    A, B = FeaturePredictor("A", "a"), FeaturePredictor("B", "b")
    items = [(1, {"a": 5, "b": 0}, MID), (2, {"a": 0, "b": 5}, MID),
             (3, {"a": 1, "b": 1}, MID)]
    s = ZBlend("x", [(A, 1.0), (B, 0.0)], clip=3).score_frame(items)
    assert s[1] > s[2]                # only A matters


def test_rank_blend_is_scale_free():
    A, B = FeaturePredictor("A", "a"), FeaturePredictor("B", "b")
    # A on a huge scale, B tiny; rank blend treats them equally
    items = [(1, {"a": 1e6, "b": 0.001}, MID), (2, {"a": 0.0, "b": 0.003}, MID),
             (3, {"a": 5e5, "b": 0.002}, MID)]
    s = RankBlend("r", [(A, 1.0), (B, 1.0)]).score_frame(items)
    assert 0.0 <= min(s.values()) and max(s.values()) <= 2.0


def test_ic_weighted_blend_gates_non_positive_ic():
    preds = {"good": FeaturePredictor("good", "g"), "bad": FeaturePredictor("bad", "b")}
    blend = ic_weighted_blend({"good": 0.3, "bad": -0.1}, preds, floor=0.0)
    assert len(blend.parts) == 1     # 'bad' (IC<=0) gated out
    items = [(1, {"g": 5, "b": 0}, MID), (2, {"g": 1, "b": 9}, MID),
             (3, {"g": 3, "b": 3}, MID)]
    s = blend.score_frame(items)
    assert s[1] > s[2]               # ranking follows the positive-IC model


def test_per_position_blend_uses_position_weights():
    A, B = FeaturePredictor("A", "a"), FeaturePredictor("B", "b")
    blend = PerPositionZBlend("pp", {MID: [(A, 1.0)], FWD: [(B, 1.0)]})
    items = [(1, {"a": 5, "b": 0}, MID), (2, {"a": 1, "b": 0}, MID),
             (10, {"a": 0, "b": 5}, FWD), (11, {"a": 0, "b": 1}, FWD)]
    s = blend.score_frame(items)
    assert s[1] > s[2]               # MID ranked by A
    assert s[10] > s[11]             # FWD ranked by B


def test_points_blend_is_points_scaled_and_cohort_independent():
    # weighted average of points-scale components -> stays in points units, and
    # each player's score does NOT depend on the rest of the cohort (so a served
    # value equals the backtested value regardless of pooling).
    A, B = FeaturePredictor("A", "a"), FeaturePredictor("B", "b")
    pb = PointsBlend("pb", [(A, 1.0), (B, 3.0)], clip_hi=15.0)
    # per-player: (1*6 + 3*2)/4 = 3.0
    assert abs(pb.score({"a": 6.0, "b": 2.0}, MID) - 3.0) < 1e-9
    # cohort-independence: score in any cohort == standalone per-player score
    small = [(1, {"a": 6, "b": 2}, MID), (2, {"a": 0, "b": 0}, MID)]
    big = small + [(i, {"a": 100, "b": 100}, MID) for i in range(3, 50)]
    assert pb.score_frame(small)[1] == pb.score_frame(big)[1] == pb.score({"a": 6, "b": 2}, MID)


def test_points_blend_clip_bounds_component():
    A = PointsBlend("pb", [(FeaturePredictor("A", "a"), 1.0)], clip_hi=10.0)
    assert A.score({"a": 1000.0}, MID) == 10.0   # winsorised to clip_hi


def test_points_blend_spec_roundtrip():
    pb = PointsBlend("pb", [(FeaturePredictor("A", "a"), 1.0),
                            (FeaturePredictor("B", "b"), 2.0)], clip_hi=12.0)
    spec = ensemble_to_spec("pb", pb)
    assert spec["ensemble"] == "points_blend" and spec["clip_hi"] == 12.0
    back = predictor_from_spec(spec)
    assert isinstance(back, PointsBlend)
    items = [(1, {"a": 5, "b": 1}, MID), (2, {"a": 1, "b": 9}, MID)]
    assert back.score_frame(items) == pb.score_frame(items)


def test_ict_heavy_blend_falls_back_without_model(sm):
    # no frozen v1 spec in a clean test DB -> ICT-only blend
    blend = ict_heavy_blend()
    assert isinstance(blend, ZBlend)
    assert len(blend.parts) == 1
    assert blend.parts[0][0].feature_key == "ict_index__ewma_hl5"
