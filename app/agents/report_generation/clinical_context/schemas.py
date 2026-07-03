# Clinical Context Agent의 structured output 계약.
# 참고: 01_production_5_agent_agentic_rag_design.md §8.4
from pydantic import BaseModel

from app.agents.report_generation.models.report import MetricFinding


class ClinicalContextOutput(BaseModel):
    primary_findings: list[MetricFinding]
    secondary_findings: list[MetricFinding] = []
    contextual_conditions: list[str] = []
    longitudinal_patterns: list[str] = []
    clinical_priorities: list[str] = []
    evidence_needs: list[str] = []
    insufficient_data_flags: list[str] = []
