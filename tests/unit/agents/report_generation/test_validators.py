"""DETERMINISTIC_VALIDATION의 5개 validator. 참고: §12.1, §25.1."""
from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput
from app.agents.report_generation.graph_state import GraphStatus
from app.agents.report_generation.models.report import (
    MetricFinding,
    ReportClaim,
    SoapDraft,
    SoapReasoningPlan,
)
from app.agents.report_generation.validators.citation_validator import validate_citations
from app.agents.report_generation.validators.metric_validator import validate_metric_consistency
from app.agents.report_generation.validators.safety_rule_validator import validate_safety
from app.agents.report_generation.validators.schema_validator import validate_schema
from app.agents.report_generation.validators.state_transition_validator import (
    validate_no_foreign_ids,
    validate_payload_size,
    validate_status_transition,
)

_PLAN = SoapReasoningPlan(S=[], O=[], A=[], P=[])
_SOAP = SoapDraft(S="s", O="o", A="a", P="p")


def _report(claims: list[ReportClaim]) -> ClinicalReportOutput:
    return ClinicalReportOutput(reasoning_plan=_PLAN, soap=_SOAP, claims=claims)


def test_schema_validator_flags_duplicate_claim_ids():
    claims = [
        ReportClaim(claim_id="A1", section="A", text="x", claim_strength="OBSERVATION"),
        ReportClaim(claim_id="A1", section="A", text="y", claim_strength="OBSERVATION"),
    ]
    issues = validate_schema(_report(claims))
    assert any("중복" in i for i in issues)


def test_schema_validator_flags_empty_soap_section():
    report = ClinicalReportOutput(
        reasoning_plan=_PLAN, soap=SoapDraft(S="", O="o", A="a", P="p"), claims=[]
    )
    issues = validate_schema(report)
    assert any("S 섹션" in i for i in issues)


def test_schema_validator_passes_clean_report():
    claims = [ReportClaim(claim_id="A1", section="A", text="x", claim_strength="OBSERVATION")]
    assert validate_schema(_report(claims)) == []


def test_citation_validator_requires_evidence_for_ap_claims():
    claims = [ReportClaim(claim_id="A1", section="A", text="x", claim_strength="OBSERVATION")]
    issues = validate_citations(_report(claims), accepted_evidence_ids=set())
    assert any("근거 참조가 없습니다" in i for i in issues)


def test_citation_validator_rejects_unapproved_evidence():
    claims = [
        ReportClaim(
            claim_id="A1", section="A", text="x",
            literature_evidence_refs=["ev_unknown"], claim_strength="INTERPRETATION",
        )
    ]
    issues = validate_citations(_report(claims), accepted_evidence_ids={"ev_approved"})
    assert any("승인되지 않은" in i for i in issues)


def test_citation_validator_s_o_sections_do_not_require_evidence():
    claims = [ReportClaim(claim_id="S1", section="S", text="x", claim_strength="OBSERVATION")]
    assert validate_citations(_report(claims), accepted_evidence_ids=set()) == []


def test_metric_validator_flags_insufficient_data_claim():
    context = ClinicalContextOutput(
        primary_findings=[
            MetricFinding(
                metric="MLU", current_value=3.0, trend_direction="INSUFFICIENT_DATA",
                observation="x", priority="HIGH", confidence=0.5,
            )
        ]
    )
    claims = [
        ReportClaim(
            claim_id="A1", section="A", text="개선됨",
            patient_evidence_refs=["metric_trend:MLU:recent_5"], claim_strength="INTERPRETATION",
        )
    ]
    issues = validate_metric_consistency(_report(claims), context)
    assert any("INSUFFICIENT_DATA" in i for i in issues)


def test_metric_validator_passes_when_trend_matches():
    context = ClinicalContextOutput(
        primary_findings=[
            MetricFinding(
                metric="MLU", current_value=3.0, trend_direction="IMPROVING",
                observation="x", priority="HIGH", confidence=0.9,
            )
        ]
    )
    claims = [
        ReportClaim(
            claim_id="A1", section="A", text="개선됨",
            patient_evidence_refs=["metric_trend:MLU:recent_5"], claim_strength="INTERPRETATION",
        )
    ]
    assert validate_metric_consistency(_report(claims), context) == []


def test_safety_validator_flags_diagnostic_assertion():
    claims = [ReportClaim(claim_id="A1", section="A", text="자폐로 확진됨", claim_strength="INTERPRETATION")]
    issues = validate_safety(_report(claims))
    assert len(issues) == 1


def test_safety_validator_passes_hedged_language():
    claims = [ReportClaim(claim_id="A1", section="A", text="개선을 시사한다", claim_strength="INTERPRETATION")]
    assert validate_safety(_report(claims)) == []


def test_validate_no_foreign_ids_flags_other_patient():
    other_id = "99999999-9999-9999-9999-999999999999"
    claims = [
        ReportClaim(claim_id="A1", section="A", text=f"환자 {other_id} 관련", claim_strength="OBSERVATION")
    ]
    issues = validate_no_foreign_ids(
        _report(claims), session_id="11111111-1111-1111-1111-111111111111",
        patient_ref_id="22222222-2222-2222-2222-222222222222",
    )
    assert len(issues) == 1


def test_validate_payload_size_flags_oversized_claim():
    claims = [ReportClaim(claim_id="A1", section="A", text="x" * 3000, claim_strength="OBSERVATION")]
    issues = validate_payload_size(_report(claims), max_length=2000)
    assert len(issues) == 1


def test_validate_status_transition_allows_known_paths():
    assert validate_status_transition(GraphStatus.INITIALIZED, GraphStatus.CONTEXT_LOADED) is True
    assert validate_status_transition(GraphStatus.INITIALIZED, GraphStatus.SAVED) is False
    assert validate_status_transition(GraphStatus.SAVED, GraphStatus.CONTEXT_LOADED) is False
