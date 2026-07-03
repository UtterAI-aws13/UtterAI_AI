"""전체 Strands Graph 흐름. 실제 Graph 엔진을 그대로 쓰되 Agent 호출/DB를 mock한다.

Bedrock/실제 DB 없이 §25.3의 핵심 시나리오(수락, 재검색 cycle, 재작성 cycle,
budget 소진, human review 라우팅)를 빠르고 반복 가능하게 검증한다.
Phase 4에서 실제 Bedrock+DB로 검증한 것과 동일한 라우팅 로직을 커버한다.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput
from app.agents.report_generation.evidence_critic.schemas import EvidenceCriticOutput
from app.agents.report_generation.evidence_research.schemas import EvidenceResearchOutput
from app.agents.report_generation.graph import build_report_generation_graph
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
from app.agents.report_generation.models.common import (
    CurrentSession,
    CurrentSessionMetrics,
    PatientHistory,
)
from app.agents.report_generation.models.evidence import AcceptedEvidence
from app.agents.report_generation.models.quality import QualityScores
from app.agents.report_generation.models.report import (
    MetricFinding,
    ReportClaim,
    SoapDraft,
    SoapReasoningPlan,
)
from app.agents.report_generation.quality_assurance.schemas import QualityAssuranceOutput

_SESSION = CurrentSession(
    session_id="s1", selected_analysis=["MLU"], transcript="x",
    metrics=CurrentSessionMetrics(MLU=3.0),
)
_HISTORY = PatientHistory(recent_session_count=5, metric_trends={"MLU": [2.1, 2.3, 2.5, 2.7, 2.8]})
_CONTEXT = ClinicalContextOutput(
    primary_findings=[
        MetricFinding(metric="MLU", current_value=3.0, trend_direction="IMPROVING",
                      observation="x", priority="HIGH", confidence=0.9)
    ],
    clinical_priorities=["MLU 개선 추세 반영"],
)


def _good_report() -> ClinicalReportOutput:
    """모든 validator를 실제로 통과하도록 구성된 리포트 (deterministic validation은 mock하지 않는다)."""
    return ClinicalReportOutput(
        reasoning_plan=SoapReasoningPlan(S=[], O=[], A=[], P=[]),
        soap=SoapDraft(S="s", O="o", A="a", P="p"),
        claims=[
            ReportClaim(
                claim_id="A1", section="A", text="MLU 개선을 시사한다",
                patient_evidence_refs=["metric_trend:MLU:recent_5"],
                literature_evidence_refs=["ev1"], claim_strength="INTERPRETATION",
            )
        ],
    )


def _accepted_critic() -> EvidenceCriticOutput:
    return EvidenceCriticOutput(
        decision="ACCEPT",
        accepted_evidence=[
            AcceptedEvidence(evidence_id="ev1", requirement_ids=["REQ_001"], supported_claim_scope="x",
                              relevance_score=0.8, quality_score=0.8, directness="DIRECT")
        ],
        requirement_coverage={"REQ_001": True},
    )


def _passing_qa() -> QualityAssuranceOutput:
    return QualityAssuranceOutput(
        decision="PASS",
        scores=QualityScores(groundedness=0.95, citation_correctness=0.98, patient_context_fidelity=0.97,
                              longitudinal_consistency=0.97, soap_compliance=0.95, safety=1.0, overall=0.95),
        route_reason="ok",
    )


def _build_invocation_state(therapist_id: str = "t1") -> dict:
    session_repo = AsyncMock()
    session_repo.has_existing_report_generation_run = AsyncMock(return_value=False)
    session_repo.get_current_session = AsyncMock(return_value=_SESSION)

    patient_history_repo = AsyncMock()
    patient_history_repo.get_patient_history = AsyncMock(return_value=_HISTORY)

    report_repo = AsyncMock()
    report_repo.save_draft = AsyncMock(return_value="draft-1")

    run_repo = AsyncMock()
    run_repo.create_run = AsyncMock()
    run_repo.update_progress = AsyncMock()
    run_repo.mark_succeeded = AsyncMock()
    run_repo.mark_failed = AsyncMock()

    state = ReportGenerationState(
        run_id="run1", session_id="s1", patient_ref_id="p1", therapist_id=therapist_id
    )
    return {
        STATE_KEY: state,
        SESSION_REPO_KEY: session_repo,
        PATIENT_HISTORY_REPO_KEY: patient_history_repo,
        REPORT_REPO_KEY: report_repo,
        RUN_REPO_KEY: run_repo,
        SELECTED_ANALYSIS_KEY: ["MLU"],
        HISTORY_SESSION_COUNT_KEY: 5,
    }


def _patched_agents(**overrides):
    """nodes.py가 import한 이름 그대로 patch한다. overrides로 시나리오별 동작을 바꾼다."""
    defaults = dict(
        analyze_clinical_context=lambda *a, **k: _CONTEXT,
        research_evidence=lambda *a, **k: EvidenceResearchOutput(requirements=[], queries=[], candidates=[]),
        critique_evidence=lambda *a, **k: _accepted_critic(),
        write_report=lambda *a, **k: _good_report(),
        assess_quality=lambda *a, **k: _passing_qa(),
    )
    defaults.update(overrides)
    return [
        patch(f"app.agents.report_generation.nodes.{name}", side_effect=fn)
        for name, fn in defaults.items()
    ]


async def _run_graph(invocation_state: dict, patches: list) -> ReportGenerationState:
    for p in patches:
        p.start()
    try:
        with patch(
            "app.services.authorization_service.AuthorizationService.ensure_session_access",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.repositories.report_generation_run_repository.record_event", new=AsyncMock()
        ):
            graph = build_report_generation_graph()
            await graph.invoke_async("test", invocation_state=invocation_state)
    finally:
        for p in patches:
            p.stop()
    return invocation_state[STATE_KEY]


@pytest.mark.asyncio
async def test_happy_path_accept_pass_saves_draft():
    invocation_state = _build_invocation_state()
    final_state = await _run_graph(invocation_state, _patched_agents())

    assert final_state.status == GraphStatus.SAVED
    invocation_state[REPORT_REPO_KEY].save_draft.assert_awaited_once()
    invocation_state[RUN_REPO_KEY].mark_succeeded.assert_awaited_once()


@pytest.mark.asyncio
async def test_critic_research_more_cycles_then_accepts():
    """1번은 RESEARCH_MORE, 2번째부터 ACCEPT - 재검색 cycle이 실제로 도는지 확인."""
    decisions = iter(["RESEARCH_MORE", "ACCEPT"])

    def critique(*a, **k):
        decision = next(decisions)
        if decision == "ACCEPT":
            return _accepted_critic()
        return EvidenceCriticOutput(decision="RESEARCH_MORE", missing_requirement_ids=["REQ_001"])

    invocation_state = _build_invocation_state()
    final_state = await _run_graph(
        invocation_state, _patched_agents(critique_evidence=critique)
    )

    assert final_state.status == GraphStatus.SAVED
    assert final_state.retry_budget.research_round == 1


@pytest.mark.asyncio
async def test_research_budget_exhaustion_routes_to_human_review():
    """critic이 계속 RESEARCH_MORE면 budget 소진 후 자동 승인 없이 HUMAN_REVIEW."""

    def always_research_more(*a, **k):
        return EvidenceCriticOutput(decision="RESEARCH_MORE", missing_requirement_ids=["REQ_001"])

    invocation_state = _build_invocation_state()
    final_state = await _run_graph(
        invocation_state, _patched_agents(critique_evidence=always_research_more)
    )

    assert final_state.status == GraphStatus.HUMAN_REVIEW
    assert final_state.retry_budget.research_round == final_state.retry_budget.max_research_rounds
    invocation_state[REPORT_REPO_KEY].save_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_qa_rewrite_cycles_then_passes():
    """1번은 REWRITE, 2번째부터 PASS - 재작성 cycle이 실제로 도는지 확인."""
    decisions = iter(["REWRITE", "PASS"])

    def qa(*a, **k):
        decision = next(decisions)
        if decision == "PASS":
            return _passing_qa()
        return QualityAssuranceOutput(
            decision="REWRITE",
            scores=QualityScores(groundedness=0.5, citation_correctness=0.5, patient_context_fidelity=0.5,
                                  longitudinal_consistency=0.5, soap_compliance=0.5, safety=1.0, overall=0.5),
            route_reason="표현이 근거보다 강함",
        )

    invocation_state = _build_invocation_state()
    final_state = await _run_graph(invocation_state, _patched_agents(assess_quality=qa))

    assert final_state.status == GraphStatus.SAVED
    assert final_state.retry_budget.report_revision_round == 1


@pytest.mark.asyncio
async def test_qa_fail_routes_to_failure():
    def qa_fail(*a, **k):
        return QualityAssuranceOutput(
            decision="FAIL",
            scores=QualityScores(groundedness=0.0, citation_correctness=0.0, patient_context_fidelity=0.0,
                                  longitudinal_consistency=0.0, soap_compliance=0.0, safety=0.0, overall=0.0),
            route_reason="시스템 오류",
        )

    invocation_state = _build_invocation_state()
    final_state = await _run_graph(invocation_state, _patched_agents(assess_quality=qa_fail))

    assert final_state.status == GraphStatus.FAILED
    invocation_state[RUN_REPO_KEY].mark_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_critic_human_review_decision_routes_directly():
    def critique_human_review(*a, **k):
        return EvidenceCriticOutput(decision="HUMAN_REVIEW", search_feedback="상충되는 근거")

    invocation_state = _build_invocation_state()
    final_state = await _run_graph(
        invocation_state, _patched_agents(critique_evidence=critique_human_review)
    )

    assert final_state.status == GraphStatus.HUMAN_REVIEW
    assert final_state.retry_budget.research_round == 0  # 재검색 없이 바로 라우팅
