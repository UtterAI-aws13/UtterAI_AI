# Strands Graph의 유일한 실행 상태 모델.
# Agent 간에 임의 dictionary를 직접 넘기지 않고 이 GraphState를 통해서만 주고받는다.
# 참고: 01_production_5_agent_agentic_rag_design.md §6
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class GraphStatus(StrEnum):
    INITIALIZED = "INITIALIZED"
    CONTEXT_LOADED = "CONTEXT_LOADED"
    CONTEXT_ANALYZED = "CONTEXT_ANALYZED"
    EVIDENCE_RESEARCHED = "EVIDENCE_RESEARCHED"
    EVIDENCE_ACCEPTED = "EVIDENCE_ACCEPTED"
    REPORT_WRITTEN = "REPORT_WRITTEN"
    QA_PASSED = "QA_PASSED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    FAILED = "FAILED"
    SAVED = "SAVED"


class RetryBudget(BaseModel):
    """근거 재검색/리포트 재작성/QA 라우팅 횟수 상한.

    소진 시 자동 PASS 처리하지 않는다 (HUMAN_REVIEW로 격하한다).
    """
    research_round: int = 0
    report_revision_round: int = 0
    qa_route_count: int = 0
    max_research_rounds: int = 3
    max_report_revisions: int = 2
    max_qa_routes: int = 3
    max_total_model_calls: int = 20


class GraphState(BaseModel):
    """Graph 노드 간에 공유되는 유일한 실행 상태.

    각 stage 결과는 dict로 보관하고, 해당 stage를 사용하는 노드에서
    app.agents.report_generation.models의 타입으로 검증해 읽는다.
    """
    run_id: str
    session_id: str
    patient_ref_id: str
    therapist_id: str

    status: GraphStatus = GraphStatus.INITIALIZED
    retry_budget: RetryBudget = Field(default_factory=RetryBudget)

    current_session: dict[str, Any] | None = None
    patient_history: dict[str, Any] | None = None

    clinical_context: dict[str, Any] | None = None
    research_result: dict[str, Any] | None = None
    critic_result: dict[str, Any] | None = None
    report_result: dict[str, Any] | None = None
    deterministic_validation: dict[str, Any] | None = None
    qa_result: dict[str, Any] | None = None

    failure_code: str | None = None
    failure_detail: str | None = None
