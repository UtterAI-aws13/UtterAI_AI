"""Golden set 스캐폴딩. 참고: §24.3, §25.5.

15개 케이스의 fixture 입력만 관리한다 - 실제 LLM 출력과의 정확한 일치 비교는
하지 않는다(모델 비결정성 때문에 비현실적). 대신 각 케이스가 무엇을 검증해야
하는지(focus)를 명시하고, 그 검증 로직 자체(우리 validator)가 대표 케이스에서
실제로 동작하는지를 mock 데이터로 증명한다.

실제 리포트 생성 결과로 골든 회귀를 돌리려면:
  python -m app.agents.report_generation.runtime_entrypoint --fixture tests/golden/report_generation/cases/<case>.json
그 출력을 이 파일의 invariant 체크 함수에 통과시켜 회귀 여부를 판단한다.
"""
import json
from pathlib import Path

import pytest

from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput
from app.agents.report_generation.models.report import ReportClaim, SoapDraft, SoapReasoningPlan
from app.agents.report_generation.validators.citation_validator import validate_citations
from app.agents.report_generation.validators.safety_rule_validator import validate_safety

_CASES_DIR = Path(__file__).parent / "cases"
_REQUIRED_FIELDS = {
    "scenario", "focus", "session_id", "patient_ref_id", "therapist_id",
    "selected_analysis", "history_session_count",
}


def _load_cases() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(_CASES_DIR.glob("*.json"))]


def test_exactly_15_golden_cases_defined():
    """§24.3이 요구하는 최소 15개 대표 케이스."""
    assert len(_load_cases()) == 15


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["scenario"])
def test_case_fixture_has_required_fields_and_valid_input_shape(case):
    from app.agents.report_generation.runtime_entrypoint import invoke  # noqa: F401 (shape reference)

    assert _REQUIRED_FIELDS <= case.keys()
    assert isinstance(case["selected_analysis"], list) and case["selected_analysis"]
    assert case["history_session_count"] >= 0


class TestInvariantCheckerCatchesRealFailureModes:
    """golden case 09/15가 요구하는 검증 로직이 실제로 동작하는지 mock 리포트로 증명."""

    def test_case_09_diagnostic_assertion_is_caught(self):
        report = ClinicalReportOutput(
            reasoning_plan=SoapReasoningPlan(S=[], O=[], A=[], P=[]),
            soap=SoapDraft(S="s", O="o", A="자폐가 의심됩니다", P="p"),
            claims=[
                ReportClaim(
                    claim_id="A1", section="A", text="자폐가 의심됩니다", claim_strength="INTERPRETATION"
                )
            ],
        )
        issues = validate_safety(report)
        assert len(issues) > 0, "진단 단정 표현이 safety validator를 통과해서는 안 된다"

    def test_case_15_unapproved_citation_is_caught(self):
        report = ClinicalReportOutput(
            reasoning_plan=SoapReasoningPlan(S=[], O=[], A=[], P=[]),
            soap=SoapDraft(S="s", O="o", A="a", P="p"),
            claims=[
                ReportClaim(
                    claim_id="A1", section="A", text="근거 기반 해석",
                    literature_evidence_refs=["ev_not_accepted"], claim_strength="INTERPRETATION",
                )
            ],
        )
        issues = validate_citations(report, accepted_evidence_ids={"ev_accepted_only"})
        assert len(issues) > 0, "미승인 근거를 인용한 claim은 REWRITE 대상이어야 한다"
