"""Unit tests for the study's statistical primitives (no DB)."""

import numpy as np

from fpl_engine.model.stats import (
    benjamini_hochberg,
    per_season_ic,
    rmse,
    spearman_ic,
)


def test_spearman_detects_monotonic_relationship():
    x = np.arange(50, dtype=float)
    y = x ** 2  # monotonic -> rho ~ 1
    rho, p = spearman_ic(x, y)
    assert rho > 0.99
    assert p < 1e-6


def test_spearman_handles_nans_pairwise():
    x = np.array([1, 2, 3, 4, 5, np.nan, 7], dtype=float)
    y = np.array([2, 4, 6, 8, 10, 100, 14], dtype=float)
    rho, _ = spearman_ic(x, y)
    assert rho > 0.99  # the NaN pair is dropped, rest perfectly monotonic


def test_benjamini_hochberg_matches_known_values():
    # Classic BH example.
    p = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
    q = benjamini_hochberg(p)
    # q_i = p_i * m / i, then monotone from the end
    expected = np.array([0.05, 0.05, 0.05, 0.05, 0.05])
    assert np.allclose(q, expected)


def test_benjamini_hochberg_controls_discoveries():
    # 5 strong signals + 95 nulls; BH should keep the strong ones at q<0.1
    rng = np.random.default_rng(0)
    p = np.concatenate([np.full(5, 1e-6), rng.uniform(0, 1, 95)])
    q = benjamini_hochberg(p)
    assert (q[:5] < 0.1).all()
    # very few nulls should sneak under 0.1
    assert (q[5:] < 0.1).sum() <= 5


def test_benjamini_hochberg_preserves_nan():
    q = benjamini_hochberg(np.array([0.01, np.nan, 0.5]))
    assert np.isnan(q[1])
    assert np.isfinite(q[0]) and np.isfinite(q[2])


def test_per_season_ic_sign_stability():
    rng = np.random.default_rng(1)
    feat, targ, seas = [], [], []
    for s in range(4):
        x = rng.normal(size=40)
        feat.append(x)
        targ.append(2 * x + rng.normal(scale=0.3, size=40))  # consistent + sign
        seas.append([f"s{s}"] * 40)
    summ = per_season_ic(np.concatenate(feat), np.concatenate(targ),
                         np.concatenate(seas))
    assert summ.n_seasons == 4
    assert summ.mean_ic > 0.5
    assert summ.sign_stability == 1.0  # same sign every season


def test_rmse():
    assert rmse(np.array([1.0, 2, 3]), np.array([1.0, 2, 3])) == 0.0
    assert rmse(np.array([0.0, 0]), np.array([2.0, 2])) == 2.0  # sqrt(mean(4,4))
