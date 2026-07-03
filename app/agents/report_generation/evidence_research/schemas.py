# Evidence Research Agent의 structured output 계약.
# 참고: 01_production_5_agent_agentic_rag_design.md §9.5
from pydantic import BaseModel

from app.agents.report_generation.models.evidence import (
    EvidenceChunk,
    EvidenceRequirement,
    ResearchQueryRecord,
)


class EvidenceResearchOutput(BaseModel):
    requirements: list[EvidenceRequirement]
    queries: list[ResearchQueryRecord]
    candidates: list[EvidenceChunk]
    search_coverage: dict[str, int] = {}
    unresolved_requirements: list[str] = []
