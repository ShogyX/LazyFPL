"""Unit tests for the window bank (no DB)."""

from fpl_engine.features.windows import _ewma, per90, window_features


def test_levels_use_last_n_appearances():
    # oldest -> newest
    series = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    f = window_features(series)
    assert f["mean_3"] == (8 + 9 + 10) / 3
    assert f["mean_5"] == (6 + 7 + 8 + 9 + 10) / 5
    assert f["sum_3"] == 27
    assert f["n"] == 10
    assert f["career_mean"] == sum(series) / 10


def test_short_series_uses_what_exists():
    f = window_features([4, 6])  # fewer than smallest window
    assert f["mean_3"] == 5
    assert f["mean_38"] == 5
    assert f["n"] == 2


def test_empty_series_is_null():
    f = window_features([])
    assert f["mean_3"] is None
    assert f["career_mean"] is None
    assert f["n"] == 0
    assert f["momentum_5_38"] is None


def test_ewma_weights_recent_more():
    rising = [0, 0, 0, 0, 10]
    falling = [10, 0, 0, 0, 0]
    assert _ewma(rising, halflife=2) > _ewma(falling, halflife=2)
    # equal series -> equals the level
    assert _ewma([5, 5, 5], halflife=5) == 5


def test_injury_gap_does_not_break_sequence():
    # windows are over the appearance sequence, so a long real-time gap is
    # invisible: only the order of appearances matters.
    before_gap = [2, 2, 2]
    after_gap = [8, 8]
    f = window_features(before_gap + after_gap)
    assert f["mean_5"] == (2 + 2 + 2 + 8 + 8) / 5
    assert f["mean_3"] == (2 + 8 + 8) / 3  # last 3 appearances span the gap


def test_career_passed_in_overrides_recent():
    # recent slice is short, but career totals reflect full history
    f = window_features([5, 5], career_sum=300.0, career_n=40)
    assert f["career_mean"] == 7.5
    assert f["career_sum"] == 300.0


def test_momentum_short_minus_long():
    series = [1] * 38 + [9] * 5  # long avg pulled down, short avg high
    f = window_features(series)
    assert f["momentum_5_38"] == f["mean_5"] - f["mean_38"]
    assert f["momentum_5_38"] > 0


def test_per90():
    assert per90(4.0, 360.0) == 1.0   # 4 goals in 360 mins -> 1.0/90
    assert per90(None, 360.0) is None
    assert per90(4.0, 0) is None
