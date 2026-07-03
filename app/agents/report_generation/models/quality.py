# Quality Assurance Agent가 생성하고, 저장/관측 레이어가 함께 참조하는 품질 모델.
# 참고: 01_production_5_agent_agentic_rag_design.md §13.3
from typing import Literal

from pydantic import BaseModel, Field


class QualityIssue(BaseModel):
    issue_id: str
    category: Literal[
        "GROUNDING",
        "CITATION",
        "PATIENT_CONTEXT",
        "LONGITUDINAL_CONSISTENCY",
        "SOAP_STRUCTURE",
        "SAFETY",
        "INTERVENTION_LINKAGE",
        "OMISSION",
        "OVERSTATEMENT",
        "INTERNAL_CONSISTENCY",
    ]
    severity: Literal["INFO", "WARNING", "BLOCKING", "CRITICAL"]
    section: Literal["S", "O", "A", "P"] | None = None
    claim_id: str | None = None
    explanation: str
    correction_instruction: str


class QualityScores(BaseModel):
    groundedness: float = Field(ge=0.0, le=1.0)
    citation_correctness: float = Field(ge=0.0, le=1.0)
    patient_context_fidelity: float = Field(ge=0.0, le=1.0)
    longitudinal_consistency: float = Field(ge=0.0, le=1.0)
    soap_compliance: float = Field(ge=0.0, le=1.0)
    safety: float = Field(ge=0.0, le=1.0)
    overall: float = Field(ge=0.0, le=1.0)
