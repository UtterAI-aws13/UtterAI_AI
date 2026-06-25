# 리포트 초안 스키마
# Bedrock Claude가 생성하는 SOAP Note 형식의 임상 기록 초안
# 치료사 검토 전까지는 확정 결과로 취급하지 않는다
from pydantic import BaseModel


class SOAPNote(BaseModel):
    """SOAP 형식 임상 기록 초안.

    - subjective: 보호자/치료사의 주관적 관찰 요약
    - objective: 전사 결과와 정량 지표 기반 객관적 기술
    - assessment: 검색 근거와 지표를 바탕으로 한 해석 초안 (진단 확정 아님)
    - plan: 다음 회기에서 고려할 활동 또는 관찰 포인트
    """
    subjective: str
    objective: str
    assessment: str
    plan: str


class ClinicalFlag(BaseModel):
    """치료사 주의가 필요한 임상 관찰 사항.

    어떤 근거 chunk를 바탕으로 플래그가 생성됐는지 evidence_chunk_ids로 추적한다.
    """
    type: str                        # 예: LOW_MLU, HIGH_RESPONSE_LATENCY
    description: str
    evidence_chunk_ids: list[str]


class ModelVersions(BaseModel):
    """리포트 생성에 사용된 모델 버전 정보.

    결과가 달라졌을 때 어떤 모델로 생성했는지 추적하기 위해 항상 함께 저장한다.
    """
    vad: str
    diarization: str
    asr: str
    embedding: str
    llm: str


class ReportDraft(BaseModel):
    """Bedrock Claude가 생성한 SOAP Note 초안과 부가 정보를 담는 최종 리포트 스키마.

    requires_human_review는 항상 True여야 한다.
    AI 출력은 반드시 치료사 검토 후에만 임상 기록으로 사용 가능하다.
    """
    report_id: str
    job_id: str
    session_id: str
    report_type: str = "SOAP_NOTE_DRAFT"
    model_versions: ModelVersions
    soap_note: SOAPNote
    clinical_flags: list[ClinicalFlag] = []
    recommended_review_points: list[str] = []
    evidence_chunk_ids: list[str] = []       # 리포트 생성에 사용된 RAG 근거 chunk ID 목록
    disclaimer: str = "치료사 검토가 필요한 AI 생성 초안입니다."
    requires_human_review: bool = True
