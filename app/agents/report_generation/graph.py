# 5-Agent 리포트 생성 Strands Graph 조립. 참고: §14
#
# 실제 strands-agents(1.x) API는 문서(§14.3)의 pseudo-code(Graph()/add_conditional_edges)와
# 다르다 — 실제로는 GraphBuilder + 노드별 boolean edge condition을 쓴다. 노드는
# MultiAgentBase만 등록 가능해서(plain function 불가) deterministic 로직도
# nodes.py에서 MultiAgentBase로 감쌌다. 이 구조 자체는 문서가 요구한 "구조 계약"
# (조건 분기, cycle, retry, shared invocation_state)을 그대로 만족한다.
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from strands.multiagent.graph import Graph, GraphBuilder

from app.agents.report_generation.graph_state import (
    HISTORY_SESSION_COUNT_KEY,
    PATIENT_HISTORY_REPO_KEY,
    REPORT_REPO_KEY,
    RUN_REPO_KEY,
    SELECTED_ANALYSIS_KEY,
    SESSION_REPO_KEY,
    STATE_KEY,
    GraphStatus,
    ReportGenerationState,
)
from app.agents.report_generation.errors import DuplicateRunError
from app.agents.report_generation.models.common import FailureCode
from app.agents.report_generation.nodes import (
    ClinicalContextNode,
    ClinicalReportNode,
    DeterministicValidationNode,
    EvidenceCriticNode,
    EvidenceResearchNode,
    FailureNode,
    FinalValidationNode,
    HumanReviewNode,
    LoadContextNode,
    QualityAssuranceNode,
    SaveDraftNode,
)
from app.agents.report_generation.routing import (
    critic_accepted,
    critic_needs_human_review,
    critic_needs_more_research_within_budget,
    final_validation_failed,
    final_validation_passed,
    not_failed,
    qa_fail,
    qa_needs_human_review,
    qa_needs_more_research_within_budget,
    qa_needs_rewrite_within_budget,
    qa_passed,
    validation_has_critical_issue,
    validation_needs_rewrite_exhausted,
    validation_needs_rewrite_within_budget,
    validation_passed,
)
from app.repositories.patient_history_repository import PatientHistoryRepository
from app.repositories.report_generation_run_repository import ReportGenerationRunRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.session_repository import SessionRepository

GRAPH_VERSION = "v1"

# 문서 §14.2 retry budget 상한 + 안전망. 정상 흐름에서는 우리 자체 RetryBudget이
# HUMAN_REVIEW/FAILURE로 먼저 격하시키므로 이 값에 도달하지 않는다.
_MAX_NODE_EXECUTIONS = 40


@dataclass
class Dependencies:
    session_repo: SessionRepository
    patient_history_repo: PatientHistoryRepository
    report_repo: ReportRepository
    run_repo: ReportGenerationRunRepository


def build_report_generation_graph() -> Graph:
    builder = GraphBuilder()

    load_context = builder.add_node(LoadContextNode(), "load_context")
    clinical_context = builder.add_node(ClinicalContextNode(), "clinical_context")
    evidence_research = builder.add_node(EvidenceResearchNode(), "evidence_research")
    evidence_critic = builder.add_node(EvidenceCriticNode(), "evidence_critic")
    clinical_report = builder.add_node(ClinicalReportNode(), "clinical_report")
    deterministic_validation = builder.add_node(DeterministicValidationNode(), "deterministic_validation")
    quality_assurance = builder.add_node(QualityAssuranceNode(), "quality_assurance")
    final_validation = builder.add_node(FinalValidationNode(), "final_validation")
    save_draft = builder.add_node(SaveDraftNode(), "save_draft")
    human_review = builder.add_node(HumanReviewNode(), "human_review")
    failure = builder.add_node(FailureNode(), "failure")

    builder.set_entry_point("load_context")

    builder.add_edge(load_context, clinical_context, condition=not_failed)
    builder.add_edge(clinical_context, evidence_research, condition=not_failed)
    builder.add_edge(evidence_research, evidence_critic)

    builder.add_edge(evidence_critic, clinical_report, condition=critic_accepted)
    builder.add_edge(evidence_critic, evidence_research, condition=critic_needs_more_research_within_budget)
    builder.add_edge(evidence_critic, human_review, condition=critic_needs_human_review)

    builder.add_edge(clinical_report, deterministic_validation)

    builder.add_edge(deterministic_validation, quality_assurance, condition=validation_passed)
    builder.add_edge(deterministic_validation, clinical_report, condition=validation_needs_rewrite_within_budget)
    builder.add_edge(deterministic_validation, human_review, condition=validation_needs_rewrite_exhausted)
    builder.add_edge(deterministic_validation, failure, condition=validation_has_critical_issue)

    builder.add_edge(quality_assurance, final_validation, condition=qa_passed)
    builder.add_edge(quality_assurance, evidence_research, condition=qa_needs_more_research_within_budget)
    builder.add_edge(quality_assurance, clinical_report, condition=qa_needs_rewrite_within_budget)
    builder.add_edge(quality_assurance, human_review, condition=qa_needs_human_review)
    builder.add_edge(quality_assurance, failure, condition=qa_fail)

    builder.add_edge(final_validation, save_draft, condition=final_validation_passed)
    builder.add_edge(final_validation, human_review, condition=final_validation_failed)

    builder.set_max_node_executions(_MAX_NODE_EXECUTIONS)
    return builder.build()


async def run_report_generation(
    *,
    session_id: str,
    patient_ref_id: str,
    therapist_id: str,
    selected_analysis: list[str],
    history_session_count: int,
    deps: Dependencies,
    run_id: str | None = None,
) -> ReportGenerationState:
    """리포트 생성 Graph 1회 실행. Phase 5(Runtime/API)의 진입점이 이 함수를 호출한다.

    중복 실행 방지(§7.1)는 report_generation_runs row를 만들기 전에 확인한다
    (만든 후에 확인하면 항상 자기 자신을 중복으로 오판한다).
    """
    if await deps.session_repo.has_existing_report_generation_run(session_id):
        raise DuplicateRunError(
            f"session {session_id} already has an in-flight report generation run"
        )

    run_id = run_id or str(uuid.uuid4())

    initial_state = ReportGenerationState(
        run_id=run_id,
        session_id=session_id,
        patient_ref_id=patient_ref_id,
        therapist_id=therapist_id,
    )

    await deps.run_repo.create_run(
        run_id=run_id,
        session_id=session_id,
        patient_ref_id=patient_ref_id,
        therapist_id=therapist_id,
        graph_version=GRAPH_VERSION,
        model_config={},
    )

    invocation_state: dict[str, Any] = {
        STATE_KEY: initial_state,
        SESSION_REPO_KEY: deps.session_repo,
        PATIENT_HISTORY_REPO_KEY: deps.patient_history_repo,
        REPORT_REPO_KEY: deps.report_repo,
        RUN_REPO_KEY: deps.run_repo,
        SELECTED_ANALYSIS_KEY: selected_analysis,
        HISTORY_SESSION_COUNT_KEY: history_session_count,
    }

    graph = build_report_generation_graph()
    await graph.invoke_async(f"generate report for session {session_id}", invocation_state=invocation_state)

    final_state: ReportGenerationState = invocation_state[STATE_KEY]
    if final_state.status not in (GraphStatus.SAVED, GraphStatus.HUMAN_REVIEW, GraphStatus.FAILED):
        # 그래프가 budget 소진 없이도 안전 상태에 못 도달했다면(버그/max_node_executions
        # 도달 등) 자동 승인하지 않고 안전하게 실패로 남긴다.
        final_state = final_state.model_copy(
            update={
                "status": GraphStatus.FAILED,
                "failure_code": final_state.failure_code or "SYSTEM_ERROR",
                "failure_detail": final_state.failure_detail or "graph did not reach a terminal state",
            }
        )
        await deps.run_repo.mark_failed(
            run_id=run_id,
            failure_code=FailureCode.SYSTEM_ERROR,
            failure_detail=final_state.failure_detail,
        )

    return final_state
