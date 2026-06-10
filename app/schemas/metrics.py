# 언어 지표 계산 결과 스키마
# 아동 발화를 대상으로 계산하며, speaker_role이 미확정인 경우 전체 화자별로 출력한다
from pydantic import BaseModel


class LanguageMetrics(BaseModel):
    """특정 화자 기준으로 계산된 언어 지표 모음.

    - mlu_morpheme: 형태소 기준 MLU (한국어 특성상 단어 기준 대신 형태소 기준 사용)
    - ntw: Number of Total Words - 총 단어(토큰) 수
    - ndw: Number of Different Words - 중복 제거 후 서로 다른 단어 수
    - ttr: Type Token Ratio (= NDW / NTW) - 발화량이 늘수록 낮아지므로 단독 판단 금지
    - avg_response_latency_sec: SLP 발화 종료 → PATIENT 발화 시작까지의 평균 간격
    """
    session_id: str
    target_speaker: str                              # 지표 계산 대상 화자 (예: PATIENT, SPEAKER_00)
    total_utterances: int
    ntw: int
    ndw: int
    ttr: float
    mlu_morpheme: float
    avg_response_latency_sec: float | None = None    # PATIENT/SLP 쌍이 없으면 None
    warnings: list[str] = []                         # 예: speaker_role_auto_detected


class SpeakerMetrics(BaseModel):
    """화자 식별 정보와 해당 화자의 언어 지표를 함께 묶은 컨테이너."""
    speaker_id: str      # pyannote 원본 레이블
    speaker_role: str    # 역할 (PATIENT / SLP / UNKNOWN 등)
    metrics: LanguageMetrics
