# Graph edge 조건. 전부 invocation_state[STATE_KEY](ReportGenerationState)만
# 읽는 순수 predicate다 — 여기서 상태를 변경하지 않는다 (변경은 nodes.py의 몫).
# strands GraphEdge는 EdgeConditionWithContext 시그니처
# (state, *, invocation_state) -> bool 을 지원한다.
from __future__ import annotations

from typing import Any

from app.agents.report_generation.graph_state import STATE_KEY, GraphStatus, ReportGenerationState


def _state(invocation_state: dict[str, Any]) -> ReportGenerationState:
    return invocation_state[STATE_KEY]


# ── load_context → clinical_context ─────────────────────────────────────────

def not_failed(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    return _state(invocation_state).status != GraphStatus.FAILED


# ── evidence_critic → {clinical_report | evidence_research | human_review} ──

def critic_accepted(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    return (s.critic_result or {}).get("decision") == "ACCEPT"


def critic_needs_more_research_within_budget(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    decision = (s.critic_result or {}).get("decision")
    return decision == "RESEARCH_MORE" and s.retry_budget.research_round < s.retry_budget.max_research_rounds


def critic_needs_human_review(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    decision = (s.critic_result or {}).get("decision")
    if decision == "HUMAN_REVIEW":
        return True
    if decision == "RESEARCH_MORE":
        return s.retry_budget.research_round >= s.retry_budget.max_research_rounds
    return False


# ── deterministic_validation → {quality_assurance | clinical_report | human_review | failure} ──

def validation_passed(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    return bool((s.deterministic_validation or {}).get("passed"))


def validation_has_critical_issue(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    return bool((s.deterministic_validation or {}).get("critical_issues"))


def validation_needs_rewrite_within_budget(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    v = s.deterministic_validation or {}
    if v.get("passed") or v.get("critical_issues"):
        return False
    return bool(v.get("rewrite_issues")) and (
        s.retry_budget.report_revision_round < s.retry_budget.max_report_revisions
    )


def validation_needs_rewrite_exhausted(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    v = s.deterministic_validation or {}
    if v.get("passed") or v.get("critical_issues"):
        return False
    return bool(v.get("rewrite_issues")) and (
        s.retry_budget.report_revision_round >= s.retry_budget.max_report_revisions
    )


# ── quality_assurance → {final_validation | evidence_research | clinical_report | human_review | failure} ──

def qa_passed(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    return (s.qa_result or {}).get("decision") == "PASS"


def qa_fail(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    return (s.qa_result or {}).get("decision") == "FAIL"


def qa_needs_more_research_within_budget(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    decision = (s.qa_result or {}).get("decision")
    return decision == "RESEARCH_MORE" and s.retry_budget.qa_route_count < s.retry_budget.max_qa_routes


def qa_needs_rewrite_within_budget(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    decision = (s.qa_result or {}).get("decision")
    return decision == "REWRITE" and s.retry_budget.qa_route_count < s.retry_budget.max_qa_routes


def qa_needs_human_review(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    decision = (s.qa_result or {}).get("decision")
    if decision == "HUMAN_REVIEW":
        return True
    if decision in ("RESEARCH_MORE", "REWRITE"):
        return s.retry_budget.qa_route_count >= s.retry_budget.max_qa_routes
    return False


# ── final_validation → {save_draft | human_review} ──────────────────────────

def final_validation_passed(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    s = _state(invocation_state)
    return bool((s.deterministic_validation or {}).get("passed"))


def final_validation_failed(_graph_state, *, invocation_state: dict[str, Any]) -> bool:
    return not final_validation_passed(_graph_state, invocation_state=invocation_state)
