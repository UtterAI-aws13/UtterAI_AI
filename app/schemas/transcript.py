from pydantic import BaseModel


class Morpheme(BaseModel):
    form: str
    tag: str


class UtteranceSource(BaseModel):
    vad_segment_id: str | None = None
    speaker_segment_id: str | None = None
    asr_segment_id: str | None = None


class Utterance(BaseModel):
    utterance_id: str
    speaker_id: str
    speaker_role: str
    start_time: float
    end_time: float
    duration_sec: float
    text: str
    asr_confidence: float
    morphemes: list[Morpheme] = []
    tokens: list[str] = []
    source: UtteranceSource | None = None
