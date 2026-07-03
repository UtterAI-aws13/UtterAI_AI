# Strands Graph 노드 어댑터. Agent와 deterministic 로직을 MultiAgentBase로 감싼다.
#
# 실제 도메인 데이터(ReportGenerationState)는 Strands의 ContentBlock 기반
# task-passing이 아니라 invocation_state 딕셔너리로 공유한다 (§6.1). 노드는
# invocation_state[STATE_KEY]를 읽고, 갱신된 상태를 같은 키에 다시 써 넣는다.
# MultiAgentResult 자체는 Strands 프레임워크 북키핑용이라 도메인 데이터를
# 담지 않는다 — 라우팅 조건(routing.py)도 invocation_state를 직접 읽는다.
from __future__ import annotations

import time
from typing import Any

from loguru import logger
from strands.multiagent.base import MultiAgentBase, MultiAgentResult
from strands.multiagent.base import Status as MultiAgentStatus

from app.agents.report_generation.clinical_context.agent import analyze_clinical_context
from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
from app.agents.report_generation.clinical_report.agent import write_report
from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput
from app.agents.report_generation.context_loader import load_context
from app.agents.report_generation.errors import ReportGenerationError
from app.agents.report_generation.evidence_critic.agent import critique_evidence
from app.agents.report_generation.evidence_critic.schemas import EvidenceCriticOutput
from app.agents.report_generation.evidence_research.agent import research_evidence
from app.agents.report_generation.evidence_research.schemas import EvidenceResearchOutput
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
    FailureCode,
    PatientHistory,
    RunStatus,
)
from app.agents.report_generation.quality_assurance.agent import assess_quality
from app.agents.report_generation.validators.citation_validator import validate_citations
from app.agents.report_generation.validators.metric_validator import validate_metric_consistency
from app.agents.report_generation.validators.safety_rule_validator import validate_safety
from app.agents.report_generation.validators.schema_validator import validate_schema
from app.agents.report_generation.validators.state_transition_validator import (
    validate_no_foreign_ids,
    validate_payload_size,
)


def _get_state(invocation_state: dict[str, Any]) -> ReportGenerationState:
    return invocation_state[STATE_KEY]


def _set_state(invocation_state: dict[str, Any], state: ReportGenerationState) -> None:
    invocation_state[STATE_KEY] = state


def _ok() -> MultiAgentResult:
    return MultiAgentResult(status=MultiAgentStatus.COMPLETED)


async def _record(invocation_state: dict[str, Any], node_name: str, **kwargs: Any) -> None:
    from app.repositories.report_generation_run_repository import record_event

    state = _get_state(invocation_state)
    try:
        await record_event(run_id=state.run_id, node_name=node_name, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 관측성 실패로 본 실행을 막지 않는다
        logger.warning(f"[report_generation_graph] record_event 실패 node={node_name}: {exc}")


class LoadContextNode(MultiAgentBase):
    """LOAD_CONTEXT deterministic node. 참고: §7"""

    id = "load_context"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]

        start = time.monotonic()
        try:
            current_session, patient_history = await load_context(
                session_id=state.session_id,
                patient_ref_id=state.patient_ref_id,
                therapist_id=state.therapist_id,
                selected_analysis=invocation_state[SELECTED_ANALYSIS_KEY],
                history_session_count=invocation_state[HISTORY_SESSION_COUNT_KEY],
                session_repo=invocation_state[SESSION_REPO_KEY],
                patient_history_repo=invocation_state[PATIENT_HISTORY_REPO_KEY],
            )
        except ReportGenerationError as exc:
            state = state.model_copy(
                update={
                    "status": GraphStatus.FAILED,
                    "failure_code": exc.failure_code.value,
                    "failure_detail": exc.detail,
                }
            )
            _set_state(invocation_state, state)
            await run_repo.mark_failed(
                run_id=state.run_id, failure_code=exc.failure_code, failure_detail=exc.detail
            )
            await _record(
                invocation_state, self.id, event_type="NODE_FAILED", decision=exc.failure_code.value,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return _ok()

        state = state.model_copy(
            update={
                "status": GraphStatus.CONTEXT_LOADED,
                "current_session": current_session.model_dump(),
                "patient_history": patient_history.model_dump(),
            }
        )
        _set_state(invocation_state, state)
        await run_repo.update_progress(
            run_id=state.run_id,
            status=RunStatus.RUNNING,
            current_node=self.id,
            retry_budget=state.retry_budget.model_dump(),
        )
        await _record(
            invocation_state, self.id, event_type="NODE_COMPLETED",
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return _ok()


class ClinicalContextNode(MultiAgentBase):
    """Clinical Context Agent node. 참고: §8"""

    id = "clinical_context"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]
        start = time.monotonic()

        current_session = CurrentSession.model_validate(state.current_session)
        patient_history = PatientHistory.model_validate(state.patient_history)

        try:
            output = analyze_clinical_context(current_session, patient_history)
        except Exception as exc:  # noqa: BLE001 - 재시도까지 소진된 뒤의 실패
            state = state.model_copy(
                update={
                    "status": GraphStatus.FAILED,
                    "failure_code": FailureCode.FAILED_CONTEXT_ANALYSIS.value,
                    "failure_detail": str(exc),
                }
            )
            _set_state(invocation_state, state)
            await run_repo.mark_failed(
                run_id=state.run_id,
                failure_code=FailureCode.FAILED_CONTEXT_ANALYSIS,
                failure_detail=str(exc),
            )
            await _record(invocation_state, self.id, event_type="NODE_FAILED")
            return _ok()

        state = state.model_copy(
            update={"status": GraphStatus.CONTEXT_ANALYZED, "clinical_context": output.model_dump()}
        )
        _set_state(invocation_state, state)
        await run_repo.update_progress(
            run_id=state.run_id, status=RunStatus.RUNNING, current_node=self.id,
            retry_budget=state.retry_budget.model_dump(),
        )
        await _record(
            invocation_state, self.id, event_type="NODE_COMPLETED",
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return _ok()


class EvidenceResearchNode(MultiAgentBase):
    """Evidence Research Agent node. 재검색 cycle의 진입점이기도 하다. 참고: §9"""

    id = "evidence_research"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]
        start = time.monotonic()

        is_revisit = state.research_result is not None
        retry_budget = state.retry_budget
        if is_revisit:
            retry_budget = retry_budget.model_copy(
                update={"research_round": retry_budget.research_round + 1}
            )

        clinical_context = ClinicalContextOutput.model_validate(state.clinical_context)
        search_feedback = None
        if is_revisit and state.critic_result:
            critic = EvidenceCriticOutput.model_validate(state.critic_result)
            search_feedback = {
                "missing_requirement_ids": critic.missing_requirement_ids,
                "search_feedback": critic.search_feedback,
            }

        output = research_evidence(clinical_context, search_feedback=search_feedback)

        state = state.model_copy(
            update={
                "status": GraphStatus.EVIDENCE_RESEARCHED,
                "research_result": output.model_dump(),
                "retry_budget": retry_budget,
            }
        )
        _set_state(invocation_state, state)
        await run_repo.update_progress(
            run_id=state.run_id, status=RunStatus.RESEARCHING, current_node=self.id,
            retry_budget=state.retry_budget.model_dump(),
        )
        await _record(
            invocation_state, self.id, event_type="NODE_COMPLETED",
            retry_count=retry_budget.research_round,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return _ok()


class EvidenceCriticNode(MultiAgentBase):
    """Evidence Critic Agent node. Research Agent와 다른 Agent 객체를 사용한다 (§10.1)."""

    id = "evidence_critic"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]
        start = time.monotonic()

        research_result = EvidenceResearchOutput.model_validate(state.research_result)
        output = critique_evidence(research_result)

        new_status = (
            GraphStatus.EVIDENCE_ACCEPTED if output.decision == "ACCEPT" else state.status
        )
        state = state.model_copy(
            update={"status": new_status, "critic_result": output.model_dump()}
        )
        _set_state(invocation_state, state)
        await run_repo.update_progress(
            run_id=state.run_id, status=RunStatus.RESEARCHING, current_node=self.id,
            retry_budget=state.retry_budget.model_dump(),
        )
        await _record(
            invocation_state, self.id, event_type="NODE_COMPLETED", decision=output.decision,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return _ok()


class ClinicalReportNode(MultiAgentBase):
    """Clinical Report Agent node. 참고: §11"""

    id = "clinical_report"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]
        start = time.monotonic()

        is_revisit = state.report_result is not None
        retry_budget = state.retry_budget
        if is_revisit:
            retry_budget = retry_budget.model_copy(
                update={"report_revision_round": retry_budget.report_revision_round + 1}
            )

        clinical_context = ClinicalContextOutput.model_validate(state.clinical_context)
        current_session = CurrentSession.model_validate(state.current_session)
        patient_history = PatientHistory.model_validate(state.patient_history)
        critic_result = EvidenceCriticOutput.model_validate(state.critic_result)

        rewrite_feedback = None
        if is_revisit:
            feedback_parts = []
            if state.deterministic_validation:
                feedback_parts.append(f"[검증 실패 사유] {state.deterministic_validation.get('issues')}")
            if state.qa_result:
                feedback_parts.append(f"[QA 피드백] {state.qa_result.get('route_reason')}")
            rewrite_feedback = "\n".join(feedback_parts) or None

        output = write_report(
            clinical_context, current_session, patient_history, critic_result,
            rewrite_feedback=rewrite_feedback,
        )

        state = state.model_copy(
            update={
                "status": GraphStatus.REPORT_WRITTEN,
                "report_result": output.model_dump(),
                "retry_budget": retry_budget,
                # 재작성 사이클에서는 이전 검증/QA 결과를 새 초안 기준으로 다시 평가해야 한다.
                "deterministic_validation": None,
                "qa_result": None,
            }
        )
        _set_state(invocation_state, state)
        await run_repo.update_progress(
            run_id=state.run_id, status=RunStatus.WRITING, current_node=self.id,
            retry_budget=state.retry_budget.model_dump(),
        )
        await _record(
            invocation_state, self.id, event_type="NODE_COMPLETED",
            retry_count=retry_budget.report_revision_round,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return _ok()


class DeterministicValidationNode(MultiAgentBase):
    """DETERMINISTIC_VALIDATION node. 참고: §12"""

    id = "deterministic_validation"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]
        start = time.monotonic()

        report = ClinicalReportOutput.model_validate(state.report_result)
        context = ClinicalContextOutput.model_validate(state.clinical_context)
        critic = EvidenceCriticOutput.model_validate(state.critic_result)
        accepted_ids = {e.evidence_id for e in critic.accepted_evidence}

        # 항목 9/11: 허용되지 않은 ID, injection/과대 payload -> 즉시 FAILURE 대상.
        critical_issues = [
            *validate_no_foreign_ids(report, state.session_id, state.patient_ref_id),
            *validate_payload_size(report),
        ]
        # 항목 1-8: schema/citation/metric/safety -> Clinical Report Agent 재작성 대상.
        rewrite_issues = [
            *validate_schema(report),
            *validate_citations(report, accepted_ids),
            *validate_metric_consistency(report, context),
            *validate_safety(report),
        ]

        passed = not critical_issues and not rewrite_issues
        validation = {
            "passed": passed,
            "critical_issues": critical_issues,
            "rewrite_issues": rewrite_issues,
        }
        state = state.model_copy(update={"deterministic_validation": validation})
        _set_state(invocation_state, state)
        await run_repo.update_progress(
            run_id=state.run_id, status=RunStatus.VALIDATING, current_node=self.id,
            retry_budget=state.retry_budget.model_dump(),
        )
        await _record(
            invocation_state, self.id, event_type="NODE_COMPLETED",
            decision="PASS" if passed else ("FAIL" if critical_issues else "REWRITE"),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return _ok()


class QualityAssuranceNode(MultiAgentBase):
    """Quality Assurance Agent node. 참고: §13"""

    id = "quality_assurance"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]
        start = time.monotonic()

        is_revisit = state.qa_result is not None
        retry_budget = state.retry_budget
        if is_revisit:
            retry_budget = retry_budget.model_copy(
                update={"qa_route_count": retry_budget.qa_route_count + 1}
            )

        clinical_context = ClinicalContextOutput.model_validate(state.clinical_context)
        current_session = CurrentSession.model_validate(state.current_session)
        patient_history = PatientHistory.model_validate(state.patient_history)
        critic_result = EvidenceCriticOutput.model_validate(state.critic_result)
        report = ClinicalReportOutput.model_validate(state.report_result)

        output = assess_quality(clinical_context, current_session, patient_history, critic_result, report)

        new_status = GraphStatus.QA_PASSED if output.decision == "PASS" else state.status
        state = state.model_copy(
            update={
                "status": new_status,
                "qa_result": output.model_dump(),
                "retry_budget": retry_budget,
            }
        )
        _set_state(invocation_state, state)
        await run_repo.update_progress(
            run_id=state.run_id, status=RunStatus.VALIDATING, current_node=self.id,
            retry_budget=state.retry_budget.model_dump(),
        )
        await _record(
            invocation_state, self.id, event_type="NODE_COMPLETED", decision=output.decision,
            retry_count=retry_budget.qa_route_count,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return _ok()


class FinalValidationNode(MultiAgentBase):
    """FINAL_VALIDATION node. QA PASS 이후 저장 직전 마지막 재확인 (§14.1)."""

    id = "final_validation"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]
        start = time.monotonic()

        # 여러 LLM 왕복으로 시간이 지났을 수 있으므로 권한을 마지막으로 재확인한다
        # (TOCTOU 방지). 세션 접근권이 사라졌으면 저장하지 않는다.
        from app.services.authorization_service import AuthorizationService
        from app.storage.rds import get_be_engine
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.agents.report_generation.errors import UnauthorizedError

        report = ClinicalReportOutput.model_validate(state.report_result)
        schema_issues = validate_schema(report)

        passed = not schema_issues
        if passed:
            try:
                async with AsyncSession(get_be_engine()) as db:
                    await AuthorizationService().ensure_session_access(
                        db, state.session_id, state.therapist_id
                    )
            except UnauthorizedError:
                passed = False
                schema_issues = ["권한이 최종 확인 단계에서 취소되었습니다."]

        state = state.model_copy(
            update={"deterministic_validation": {"passed": passed, "critical_issues": [], "rewrite_issues": schema_issues}}
        )
        _set_state(invocation_state, state)
        await run_repo.update_progress(
            run_id=state.run_id, status=RunStatus.VALIDATING, current_node=self.id,
            retry_budget=state.retry_budget.model_dump(),
        )
        await _record(
            invocation_state, self.id, event_type="NODE_COMPLETED",
            decision="PASS" if passed else "FAIL",
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return _ok()


class SaveDraftNode(MultiAgentBase):
    """SAVE_DRAFT node. 여기 도달했다는 것은 모든 validation을 통과했다는 뜻이다 (§17, §18.2)."""

    id = "save_draft"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]
        report_repo = invocation_state[REPORT_REPO_KEY]
        start = time.monotonic()

        report = ClinicalReportOutput.model_validate(state.report_result)
        critic = EvidenceCriticOutput.model_validate(state.critic_result)

        literature_evidence = [
            {
                "evidence_id": e.evidence_id,
                "supported_scope": e.supported_claim_scope,
                "limitations": e.limitations,
            }
            for e in critic.accepted_evidence
        ]
        patient_evidence_ids = {
            ref
            for claim in report.claims
            for ref in claim.patient_evidence_refs
        }
        patient_evidence = [{"evidence_id": ref, "type": "metric_trend"} for ref in patient_evidence_ids]

        evidence_trace = {
            "claims": [c.model_dump() for c in report.claims],
            "literature_evidence": literature_evidence,
            "patient_evidence": patient_evidence,
        }

        report_draft_id = await report_repo.save_draft(
            generation_run_id=state.run_id,
            session_id=state.session_id,
            patient_ref_id=state.patient_ref_id,
            therapist_id=state.therapist_id,
            soap=report.soap.model_dump(),
            reasoning_summary=report.reasoning_plan.model_dump(),
            claims=[c.model_dump() for c in report.claims],
            evidence_trace=evidence_trace,
            validation=state.deterministic_validation or {},
            quality_scores=(state.qa_result or {}).get("scores", {}),
        )

        state = state.model_copy(update={"status": GraphStatus.SAVED})
        _set_state(invocation_state, state)
        await run_repo.mark_succeeded(
            run_id=state.run_id, quality_scores=(state.qa_result or {}).get("scores", {})
        )
        await _record(
            invocation_state, self.id, event_type="NODE_COMPLETED",
            metadata={"report_draft_id": report_draft_id},
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return _ok()


class HumanReviewNode(MultiAgentBase):
    """SAVE_HUMAN_REVIEW_STATE node. 자동 승인 대신 사람 검토로 안전하게 격하한다 (§14.2)."""

    id = "human_review"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]

        state = state.model_copy(update={"status": GraphStatus.HUMAN_REVIEW})
        _set_state(invocation_state, state)
        await run_repo.update_progress(
            run_id=state.run_id, status=RunStatus.HUMAN_REVIEW, current_node=self.id,
            retry_budget=state.retry_budget.model_dump(),
        )
        await _record(invocation_state, self.id, event_type="NODE_COMPLETED")
        return _ok()


class FailureNode(MultiAgentBase):
    """FAILURE node."""

    id = "failure"

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        invocation_state = invocation_state or {}
        state = _get_state(invocation_state)
        run_repo = invocation_state[RUN_REPO_KEY]

        failure_code = FailureCode(state.failure_code) if state.failure_code else FailureCode.SYSTEM_ERROR
        state = state.model_copy(update={"status": GraphStatus.FAILED, "failure_code": failure_code.value})
        _set_state(invocation_state, state)
        await run_repo.mark_failed(
            run_id=state.run_id, failure_code=failure_code,
            failure_detail=state.failure_detail or "unspecified failure",
        )
        await _record(invocation_state, self.id, event_type="NODE_COMPLETED")
        return _ok()
