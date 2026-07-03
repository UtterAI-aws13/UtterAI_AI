"""Graph edge routing predicates. 참고: 01_production_5_agent_agentic_rag_design.md §25.1."""
from app.agents.report_generation import routing
from app.agents.report_generation.graph_state import (
    STATE_KEY,
    GraphStatus,
    ReportGenerationState,
    RetryBudget,
)


def _state(**overrides) -> ReportGenerationState:
    defaults = dict(
        run_id="r1", session_id="s1", patient_ref_id="p1", therapist_id="t1"
    )
    defaults.update(overrides)
    return ReportGenerationState(**defaults)


def _inv(state: ReportGenerationState) -> dict:
    return {STATE_KEY: state}


def test_not_failed_true_when_not_failed():
    state = _state(status=GraphStatus.CONTEXT_LOADED)
    assert routing.not_failed(None, invocation_state=_inv(state)) is True


def test_not_failed_false_when_failed():
    state = _state(status=GraphStatus.FAILED)
    assert routing.not_failed(None, invocation_state=_inv(state)) is False


def test_critic_accepted():
    state = _state(critic_result={"decision": "ACCEPT"})
    assert routing.critic_accepted(None, invocation_state=_inv(state)) is True
    state2 = _state(critic_result={"decision": "RESEARCH_MORE"})
    assert routing.critic_accepted(None, invocation_state=_inv(state2)) is False


def test_critic_research_more_within_budget():
    state = _state(
        critic_result={"decision": "RESEARCH_MORE"},
        retry_budget=RetryBudget(research_round=1, max_research_rounds=3),
    )
    assert routing.critic_needs_more_research_within_budget(None, invocation_state=_inv(state)) is True


def test_critic_research_more_exhausted_routes_to_human_review():
    state = _state(
        critic_result={"decision": "RESEARCH_MORE"},
        retry_budget=RetryBudget(research_round=3, max_research_rounds=3),
    )
    assert routing.critic_needs_more_research_within_budget(None, invocation_state=_inv(state)) is False
    assert routing.critic_needs_human_review(None, invocation_state=_inv(state)) is True


def test_critic_human_review_decision_routes_directly():
    state = _state(critic_result={"decision": "HUMAN_REVIEW"})
    assert routing.critic_needs_human_review(None, invocation_state=_inv(state)) is True


def test_validation_passed():
    state = _state(deterministic_validation={"passed": True, "critical_issues": [], "rewrite_issues": []})
    assert routing.validation_passed(None, invocation_state=_inv(state)) is True


def test_validation_critical_issue_routes_to_failure():
    state = _state(
        deterministic_validation={"passed": False, "critical_issues": ["foreign id"], "rewrite_issues": []}
    )
    assert routing.validation_has_critical_issue(None, invocation_state=_inv(state)) is True
    assert routing.validation_needs_rewrite_within_budget(None, invocation_state=_inv(state)) is False


def test_validation_rewrite_within_budget_vs_exhausted():
    within = _state(
        deterministic_validation={"passed": False, "critical_issues": [], "rewrite_issues": ["bad claim"]},
        retry_budget=RetryBudget(report_revision_round=0, max_report_revisions=2),
    )
    assert routing.validation_needs_rewrite_within_budget(None, invocation_state=_inv(within)) is True
    assert routing.validation_needs_rewrite_exhausted(None, invocation_state=_inv(within)) is False

    exhausted = _state(
        deterministic_validation={"passed": False, "critical_issues": [], "rewrite_issues": ["bad claim"]},
        retry_budget=RetryBudget(report_revision_round=2, max_report_revisions=2),
    )
    assert routing.validation_needs_rewrite_within_budget(None, invocation_state=_inv(exhausted)) is False
    assert routing.validation_needs_rewrite_exhausted(None, invocation_state=_inv(exhausted)) is True


def test_qa_decision_routing():
    passed = _state(qa_result={"decision": "PASS"})
    assert routing.qa_passed(None, invocation_state=_inv(passed)) is True

    failed = _state(qa_result={"decision": "FAIL"})
    assert routing.qa_fail(None, invocation_state=_inv(failed)) is True

    research_more = _state(
        qa_result={"decision": "RESEARCH_MORE"},
        retry_budget=RetryBudget(qa_route_count=0, max_qa_routes=3),
    )
    assert routing.qa_needs_more_research_within_budget(None, invocation_state=_inv(research_more)) is True

    rewrite = _state(
        qa_result={"decision": "REWRITE"},
        retry_budget=RetryBudget(qa_route_count=0, max_qa_routes=3),
    )
    assert routing.qa_needs_rewrite_within_budget(None, invocation_state=_inv(rewrite)) is True


def test_qa_budget_exhausted_routes_to_human_review():
    state = _state(
        qa_result={"decision": "REWRITE"},
        retry_budget=RetryBudget(qa_route_count=3, max_qa_routes=3),
    )
    assert routing.qa_needs_rewrite_within_budget(None, invocation_state=_inv(state)) is False
    assert routing.qa_needs_human_review(None, invocation_state=_inv(state)) is True


def test_final_validation_routing():
    passed = _state(deterministic_validation={"passed": True})
    assert routing.final_validation_passed(None, invocation_state=_inv(passed)) is True
    assert routing.final_validation_failed(None, invocation_state=_inv(passed)) is False

    failed = _state(deterministic_validation={"passed": False})
    assert routing.final_validation_passed(None, invocation_state=_inv(failed)) is False
    assert routing.final_validation_failed(None, invocation_state=_inv(failed)) is True
