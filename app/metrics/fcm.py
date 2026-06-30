# FCM (Functional Communication Measure) — 기능적 의사소통 척도
#
# ASHA FCM 발화 표현(Spoken Language Expression) 도메인 기준 1–7 척도.
# 임상 주의: FCM는 SLP가 직접 평가하는 척도다. 아래 estimate_fcm_range()는
# 정량 지표(MLU·disfluency·CIU)로 예측 범위를 제시할 뿐이며,
# 최종 FCM은 반드시 임상가가 확정해야 한다.
#
# 척도 정의 (Spoken Language Expression):
#   1 — 기능적 표현 없음
#   2 — 기본 필요만 전달 (예/아니오 수준)
#   3 — 일부 기본 필요 전달 가능
#   4 — 단순 상황에서 비일관적 의사소통
#   5 — 단순 상황에서 일관적 의사소통
#   6 — 복잡한 상황에서 독립적 의사소통
#   7 — 발화 이전 수준의 완전한 의사소통
from dataclasses import dataclass


@dataclass(frozen=True)
class FCMEstimate:
    """FCM 예측 범위. SLP가 확정하기 전까지 활용한다."""
    low: int           # 예측 범위 하한 (1–7)
    high: int          # 예측 범위 상한 (1–7)
    note: str          # 예측 근거 요약


def estimate_fcm_range(
    mlu_morpheme: float,
    disfluency_rate: float,
    ciu_rate: float,
) -> FCMEstimate:
    """정량 지표를 바탕으로 FCM 예측 범위를 반환한다.

    가중 점수(0–10) → FCM 범위 매핑:
      mlu_score   — MLU ≥ 4 이면 높게 기여
      ciu_score   — CIU 비율이 높을수록 높게 기여
      dis_penalty — 비유창성 비율이 높을수록 감점
    """
    mlu_score = min(mlu_morpheme / 8.0, 1.0) * 4      # 0–4점
    ciu_score = ciu_rate * 3                             # 0–3점
    dis_penalty = min(disfluency_rate * 10, 3.0)        # 0–3점 감점

    raw = mlu_score + ciu_score - dis_penalty            # -3 ~ 7

    # raw → FCM 중앙값
    if raw >= 6:
        center = 7
    elif raw >= 4.5:
        center = 6
    elif raw >= 3:
        center = 5
    elif raw >= 1.5:
        center = 4
    elif raw >= 0:
        center = 3
    elif raw >= -1.5:
        center = 2
    else:
        center = 1

    low = max(1, center - 1)
    high = min(7, center + 1)
    return FCMEstimate(
        low=low,
        high=high,
        note=f"mlu={mlu_morpheme:.1f}, ciu_rate={ciu_rate:.2f}, disfluency_rate={disfluency_rate:.2f}",
    )