# 지표 시계열로부터 추세 방향을 결정론적으로 계산한다.
# Clinical Context Agent가 MetricFinding.trend_direction을 스스로 지어내지 않고
# 이 계산 결과를 입력으로 받아 관찰문만 작성하도록 하기 위한 deterministic 계산기.
from typing import Literal

TrendDirection = Literal["IMPROVING", "DECLINING", "STABLE", "INSUFFICIENT_DATA"]

DEFAULT_MIN_DATA_POINTS = 3
DEFAULT_RELATIVE_THRESHOLD = 0.05  # 최근값이 이전 평균 대비 ±5% 이상 변해야 추세로 본다


def compute_trend_direction(
    values: list[float],
    *,
    min_data_points: int = DEFAULT_MIN_DATA_POINTS,
    relative_threshold: float = DEFAULT_RELATIVE_THRESHOLD,
    higher_is_better: bool = True,
) -> TrendDirection:
    """values는 시간순(오래된 것 -> 최신)으로 정렬된 지표 값이다.

    데이터가 min_data_points 미만이면 INSUFFICIENT_DATA를 반환한다 (§8.5:
    이것도 정상적인 결과로 허용한다). 마지막 값과 그 이전 값들의 평균을
    relative_threshold 기준으로 비교해 STABLE/IMPROVING/DECLINING을 정한다.

    higher_is_better=False로 지정하면 반응 지연처럼 값이 낮을수록 좋은
    지표의 방향을 뒤집는다.
    """
    if len(values) < min_data_points:
        return "INSUFFICIENT_DATA"

    *history, latest = values
    baseline = sum(history) / len(history)

    if baseline == 0:
        return "STABLE" if latest == 0 else ("IMPROVING" if higher_is_better == (latest > 0) else "DECLINING")

    relative_change = (latest - baseline) / abs(baseline)

    if abs(relative_change) < relative_threshold:
        return "STABLE"

    improved = relative_change > 0 if higher_is_better else relative_change < 0
    return "IMPROVING" if improved else "DECLINING"
