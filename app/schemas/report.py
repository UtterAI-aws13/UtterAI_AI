from pydantic import BaseModel


class SOAPNote(BaseModel):
    subjective: str
    objective: str
    assessment: str
    plan: str


class ClinicalFlag(BaseModel):
    type: str
    description: str
    evidence_chunk_ids: list[str]


class ModelVersions(BaseModel):
    vad: str
    diarization: str
    asr: str
    embedding: str
    llm: str


class ReportDraft(BaseModel):
    report_id: str
    job_id: str
    session_id: str
    report_type: str = "SOAP_NOTE_DRAFT"
    model_versions: ModelVersions
    soap_note: SOAPNote
    clinical_flags: list[ClinicalFlag] = []
    recommended_review_points: list[str] = []
    evidence_chunk_ids: list[str] = []
    disclaimer: str = "치료사 검토가 필요한 AI 생성 초안입니다."
    requires_human_review: bool = True
