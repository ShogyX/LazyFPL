"""Recency-adaptive signal is part of the ensemble (default set, blend, freeze)."""

from types import SimpleNamespace

from fpl_engine.model.predictors import (
    Predictor,
    RankBlend,
    RecencyPredictor,
    build_ensembles,
    default_predictors,
    ensemble_to_spec,
    points_blend,
    predictor_from_spec,
)

MID = 3
_FRESH = {"total_points__ewma_hl5": 9.0, "total_points__mean_38": 2.0,
          "total_points__n": 40.0}
_THIN = {"total_points__ewma_hl5": 9.0, "total_points__mean_38": 2.0,
         "total_points__n": 1.0}


def test_recency_predictor_protocol_and_adaptivity():
    rp = RecencyPredictor()
    assert isinstance(rp, Predictor)
    assert rp.score(_FRESH, MID) > 8.0      # rich recent data -> tracks fresh form
    assert rp.score(_THIN, MID) < 4.0       # thin data -> leans on stable prior


def test_default_predictors_includes_recency():
    preds = default_predictors(include_model=False)
    assert "recency" in preds and isinstance(preds["recency"], RecencyPredictor)


def test_points_blend_excludes_redundant_recency():
    preds = default_predictors(include_model=False)
    ic = {"recency": 0.5, "recent5": 0.4, "ict": 0.6, "xgi90": 0.3}
    blend = points_blend(ic, preds, floor=0.0)
    # recency is omitted from the simple points average (redundant with the
    # short-form signals it would dilute); recent5 stays, ICT/xGI excluded.
    names = {p.name for p, w in blend.parts}
    assert "recency" not in names and "recent5" in names and "ict" not in names


def test_recency_survives_ensemble_freeze_roundtrip():
    ens = RankBlend("r", [(RecencyPredictor(), 1.0),
                          (RecencyPredictor("recency_pp", "total_points", 8.0), 2.0)])
    back = predictor_from_spec(ensemble_to_spec("r", ens))
    assert isinstance(back, RankBlend)
    parts = dict((p.name, p) for p, _ in back.parts)
    assert isinstance(parts["recency"], RecencyPredictor)
    assert parts["recency_pp"].k == 8.0       # tunable preserved
    items = [(1, _FRESH, MID), (2, _THIN, MID)]
    assert back.score_frame(items) == ens.score_frame(items)


def test_build_ensembles_blends_recency():
    preds = default_predictors(include_model=False)
    report = SimpleNamespace(
        ic_weights={n: 0.3 for n in preds},
        overall_ic={n: 0.3 for n in preds},
        per_position_ic={n: {1: 0.3, 2: 0.3, 3: 0.3, 4: 0.3} for n in preds},
    )
    ens = build_ensembles(report, preds)
    # recency contributes to the IC-weighted z-blend but is kept out of the
    # simple points average (where it would be a redundant 5th form signal).
    assert "recency" in {p.name for p, w in ens["ic_weighted"].parts}
    assert "recency" not in {p.name for p, w in ens["points_blend"].parts}


def test_select_decorrelated_drops_near_duplicates():
    from fpl_engine.model.predictors import select_decorrelated
    preds = {"a": RecencyPredictor("a"), "b": RecencyPredictor("b"),
             "c": RecencyPredictor("c")}
    report = SimpleNamespace(
        overall_ic={"a": 0.5, "b": 0.4, "c": 0.3},
        signal_correlation={"a": {"a": 1.0, "b": 0.95, "c": 0.1},
                            "b": {"a": 0.95, "b": 1.0, "c": 0.1},
                            "c": {"a": 0.1, "b": 0.1, "c": 1.0}})
    kept = select_decorrelated(report, preds, max_corr=0.9)
    assert "a" in kept and "c" in kept       # top-IC 'a' + decorrelated 'c'
    assert "b" not in kept                   # 0.95-correlated with 'a', lower IC
