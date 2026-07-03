# Clinical Report Agent의 structured output 계약.
# reasoning_plan과 soap를 한 번에 생성하되 schema에서 명확히 분리한다.
# 참고: 01_production_5_agent_agentic_rag_design.md §11.4
from pydantic import BaseModel

from app.agents.report_generation.models.report import ReportClaim, SoapDraft, SoapReasoningPlan


class ClinicalReportOutput(BaseModel):
    reasoning_plan: SoapReasoningPlan
    soap: SoapDraft
    claims: list[ReportClaim]
    limitations: list[str] = []
    clinician_review_points: list[str] = []
