# Evidence Critic Agent의 structured output 계약.
# 참고: 01_production_5_agent_agentic_rag_design.md §10.4
from typing import Literal

from pydantic import BaseModel

from app.agents.report_generation.models.evidence import AcceptedEvidence, RejectedEvidence


class EvidenceCriticOutput(BaseModel):
    decision: Literal["ACCEPT", "RESEARCH_MORE", "HUMAN_REVIEW"]
    accepted_evidence: list[AcceptedEvidence] = []
    rejected_evidence: list[RejectedEvidence] = []
    conflicting_evidence: list[str] = []
    requirement_coverage: dict[str, bool] = {}
    missing_requirement_ids: list[str] = []
    search_feedback: str | None = None
