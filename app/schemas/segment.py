from pydantic import BaseModel


class SpeechSegment(BaseModel):
    segment_id: str
    start_time: float
    end_time: float
    duration_sec: float
    confidence: float


class SpeakerRole(str):
    CHILD = "CHILD"
    THERAPIST = "THERAPIST"
    CAREGIVER = "CAREGIVER"
    UNKNOWN = "UNKNOWN"


class SpeakerSegment(BaseModel):
    speaker_segment_id: str
    speaker_id: str
    speaker_role: str = "UNKNOWN"
    start_time: float
    end_time: float


class ASRSegment(BaseModel):
    asr_segment_id: str
    start_time: float
    end_time: float
    text: str
    confidence: float


class ASRResult(BaseModel):
    text: str
    segments: list[ASRSegment]
