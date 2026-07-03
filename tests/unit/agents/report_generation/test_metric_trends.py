from app.agents.report_generation.metric_trends import compute_trend_direction


def test_insufficient_data_below_min_points():
    assert compute_trend_direction([2.0, 2.1]) == "INSUFFICIENT_DATA"


def test_improving_trend():
    assert compute_trend_direction([2.1, 2.3, 2.5, 2.7, 2.8]) == "IMPROVING"


def test_declining_trend():
    assert compute_trend_direction([2.8, 2.7, 2.5, 2.3, 2.1]) == "DECLINING"


def test_stable_trend_within_threshold():
    assert compute_trend_direction([2.0, 2.0, 2.0, 2.01]) == "STABLE"


def test_lower_is_better_flips_direction():
    # 반응 지연은 낮을수록 좋음 - 값이 내려가면 IMPROVING이어야 한다
    assert compute_trend_direction(
        [2000, 1900, 1800, 1200], higher_is_better=False
    ) == "IMPROVING"
    assert compute_trend_direction(
        [1200, 1300, 1400, 2000], higher_is_better=False
    ) == "DECLINING"


def test_zero_baseline_does_not_crash():
    assert compute_trend_direction([0, 0, 0, 0]) == "STABLE"
