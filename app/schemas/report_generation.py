# 5-Agent 리포트 생성 API/SQS 메시지 스키마.
# 참고: 01_production_5_agent_agentic_rag_design.md §19, §20
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ReportGenerationCreateRequest(BaseModel):
    """POST .../sessions/{session_id}/reports/generate 요청 바디.

    patient_ref_id/therapist_id는 이 API를 호출하는 BE가 이미 인증/인가를
    마친 뒤 전달하는 값이다 (jobs.py의 user_id 전달 방식과 동일한 신뢰 경계).
    """
    patient_ref_id: str
    therapist_id: str
    selected_analysis: list[str]
    history_session_count: int = 5


class ReportGenerationCreateResponse(BaseModel):
    run_id: str
    status: str = "QUEUED"


class ReportGenerationStatusResponse(BaseModel):
    """GET /report-generation-runs/{run_id} 응답.

    환자 원문, 내부 chain-of-thought, 전체 prompt는 반환하지 않는다 (§19.2).
    """
    run_id: str
    status: str
    current_node: str | None = None
    retry_summary: dict[str, int] | None = None
    report_draft_id: str | None = None
    quality_scores: dict[str, float] | None = None
    failure_code: str | None = None
    reason_codes: list[str] | None = None


class ReportGenerationQueueMessage(BaseModel):
    """API가 발행하고 워커가 소비하는 SQS 메시지. idempotency key는 run_id다."""
    run_id: str
    session_id: str
    patient_ref_id: str
    therapist_id: str
    selected_analysis: list[str]
    history_session_count: int = 5
    requested_at: datetime


def build_status_response(run_row: dict[str, Any]) -> ReportGenerationStatusResponse:
    """SqlReportGenerationRunRepository.get_run()의 raw row를 API 응답으로 변환한다."""
    retry_budget = run_row.get("retry_budget_json") or {}
    quality_scores = run_row.get("quality_scores_json")
    status = run_row["status"]

    reason_codes = None
    if status == "HUMAN_REVIEW":
        reason_codes = [run_row["failure_code"]] if run_row.get("failure_code") else []
    elif status == "FAILED":
        reason_codes = [run_row["failure_code"]] if run_row.get("failure_code") else None

    return ReportGenerationStatusResponse(
        run_id=str(run_row["id"]),
        status=status,
        current_node=run_row.get("current_node"),
        report_draft_id=str(run_row["report_draft_id"]) if run_row.get("report_draft_id") else None,
        retry_summary={
            "research_round": retry_budget.get("research_round", 0),
            "report_revision_round": retry_budget.get("report_revision_round", 0),
            "qa_route_count": retry_budget.get("qa_route_count", 0),
        }
        if retry_budget
        else None,
        quality_scores=quality_scores,
        failure_code=run_row.get("failure_code"),
        reason_codes=reason_codes,
    )
