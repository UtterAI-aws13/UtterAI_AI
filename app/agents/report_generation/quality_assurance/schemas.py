# Quality Assurance Agent의 structured output 계약.
# 참고: 01_production_5_agent_agentic_rag_design.md §13.3
from typing import Literal

from pydantic import BaseModel

from app.agents.report_generation.models.quality import QualityIssue, QualityScores


class QualityAssuranceOutput(BaseModel):
    decision: Literal["PASS", "RESEARCH_MORE", "REWRITE", "HUMAN_REVIEW", "FAIL"]
    scores: QualityScores
    issues: list[QualityIssue] = []
    route_reason: str
