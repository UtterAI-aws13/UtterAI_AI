# Clinical Context / Clinical Report Agent가 공유하는 임상 소견·SOAP 도메인 모델.
# 참고: 01_production_5_agent_agentic_rag_design.md §8.4, §11.4
from typing import Literal

from pydantic import BaseModel, Field


class MetricFinding(BaseModel):
    metric: str
    current_value: float | int | str | None
    trend_direction: Literal[
        "IMPROVING", "DECLINING", "STABLE", "INSUFFICIENT_DATA"
    ]
    observation: str
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    confidence: float = Field(ge=0.0, le=1.0)


class ReasoningItem(BaseModel):
    finding_id: str
    patient_basis: list[str]
    literature_basis: list[str]
    allowed_interpretation: str
    prohibited_overstatement: str | None = None


class SoapReasoningPlan(BaseModel):
    S: list[str]
    O: list[str]  # noqa: E741 -- SOAP Objective section, not a variable
    A: list[ReasoningItem]
    P: list[ReasoningItem]


class ReportClaim(BaseModel):
    claim_id: str
    section: Literal["S", "O", "A", "P"]
    text: str
    patient_evidence_refs: list[str] = []
    literature_evidence_refs: list[str] = []
    claim_strength: Literal["OBSERVATION", "INTERPRETATION", "SUGGESTION"]


class SoapDraft(BaseModel):
    S: str
    O: str  # noqa: E741 -- SOAP Objective section, not a variable
    A: str
    P: str
