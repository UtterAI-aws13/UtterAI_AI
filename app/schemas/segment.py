# VAD, 화자 분리, ASR 각 모델의 출력 단위 스키마
# 세 결과는 alignment 단계에서 Utterance 하나로 합쳐진다
from pydantic import BaseModel


class SpeechSegment(BaseModel):
    """Silero VAD 출력: 음성이 감지된 시간 구간.

    침묵 구간을 제거해 STT 처리량을 줄이고, 반응 지연 시간 계산의 기준이 된다.
    """
    segment_id: str
    start_time: float
    end_time: float
    duration_sec: float
    confidence: float        # VAD가 해당 구간을 음성으로 판단한 확률


class SpeakerRole:
    """pyannote가 출력한 SPEAKER_00, SPEAKER_01을 서비스 역할로 매핑한 결과.

    MVP에서는 치료사가 직접 지정하거나 발화량 규칙으로 추정한다.
    확정 전까지는 UNKNOWN으로 유지한다.
    """
    CHILD = "CHILD"
    THERAPIST = "THERAPIST"
    CAREGIVER = "CAREGIVER"
    UNKNOWN = "UNKNOWN"


class SpeakerSegment(BaseModel):
    """pyannote 화자 분리 출력: 특정 화자가 말한 시간 구간."""
    speaker_segment_id: str
    speaker_id: str          # pyannote 원본 레이블 (예: SPEAKER_00)
    speaker_role: str = "UNKNOWN"  # 역할 매핑 전까지 UNKNOWN
    start_time: float
    end_time: float


class ASRSegment(BaseModel):
    """Whisper STT 출력의 구간 단위. timestamp가 있어야 화자 분리 결과와 정렬할 수 있다."""
    asr_segment_id: str
    start_time: float
    end_time: float
    text: str
    confidence: float


class ASRResult(BaseModel):
    """Whisper 전체 전사 결과. text는 전문, segments는 timestamp 포함 구간 목록."""
    text: str
    segments: list[ASRSegment]
