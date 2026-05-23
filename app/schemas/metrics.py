from pydantic import BaseModel


class LanguageMetrics(BaseModel):
    session_id: str
    target_speaker: str
    total_utterances: int
    ntw: int
    ndw: int
    ttr: float
    mlu_morpheme: float
    average_response_latency_sec: float | None = None
    warnings: list[str] = []


class SpeakerMetrics(BaseModel):
    speaker_id: str
    speaker_role: str
    metrics: LanguageMetrics
