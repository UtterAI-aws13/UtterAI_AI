# 여러 Agent/노드가 함께 참조하는 공유 enum과 LOAD_CONTEXT 산출물 모델.
# 참고: 01_production_5_agent_agentic_rag_design.md §7.3, §26.3
from enum import StrEnum

from pydantic import BaseModel


class RunStatus(StrEnum):
    """report_generation_runs.status / API 상태 조회 응답에 쓰는 값."""
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RESEARCHING = "RESEARCHING"
    WRITING = "WRITING"
    VALIDATING = "VALIDATING"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class FailureCode(StrEnum):
    """failure_code 컬럼에 저장하는 안정적인 실패 사유 enum."""
    FAILED_CONTEXT_ANALYSIS = "FAILED_CONTEXT_ANALYSIS"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    CONFLICTING_CLINICAL_EVIDENCE = "CONFLICTING_CLINICAL_EVIDENCE"
    METRIC_TREND_MISMATCH = "METRIC_TREND_MISMATCH"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_SESSION_STATE = "INVALID_SESSION_STATE"
    MISSING_CONFIRMED_TRANSCRIPT = "MISSING_CONFIRMED_TRANSCRIPT"
    CORRUPTED_METRICS = "CORRUPTED_METRICS"
    SCHEMA_VERSION_INCOMPATIBLE = "SCHEMA_VERSION_INCOMPATIBLE"
    MALICIOUS_PAYLOAD = "MALICIOUS_PAYLOAD"
    RETRY_BUDGET_EXHAUSTED = "RETRY_BUDGET_EXHAUSTED"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class CurrentSessionMetrics(BaseModel):
    MLU: float | None = None
    TTR: float | None = None
    NDW: int | None = None
    NTW: int | None = None
    response_latency_avg_ms: float | None = None


class CurrentSession(BaseModel):
    """LOAD_CONTEXT가 조회하는 현재 세션 정보. §7.3 current_session."""
    session_id: str
    selected_analysis: list[str]
    transcript: str
    metrics: CurrentSessionMetrics
    session_conditions: list[str] = []


class PatientHistory(BaseModel):
    """LOAD_CONTEXT가 조회하는 환자 longitudinal context. §7.3 patient_history.

    정량 지표는 RDS deterministic query 결과만 담는다.
    AgentCore Memory를 source of truth로 쓰지 않는다.
    """
    recent_session_count: int
    metric_trends: dict[str, list[float]] = {}
    current_goal: str | None = None
    goal_progress_summary: str | None = None
    clinician_cautions: list[str] = []
