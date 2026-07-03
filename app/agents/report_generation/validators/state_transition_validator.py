# DETERMINISTIC_VALIDATION §12.1 항목 9-12: report status transition 가능 여부,
# payload 크기, HTML/script 제거.
#
# "허용되지 않은 patient/session ID 포함 여부"(항목 9)는 claim 텍스트에서
# UUID 패턴을 찾아 이번 run의 session_id/patient_ref_id와 다른 값이 섞여
# 있는지만 확인한다 (다른 환자 정보 유출/프롬프트 인젝션 흔적 탐지).
import re

from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput
from app.agents.report_generation.graph_state import GraphStatus

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
MAX_CLAIM_TEXT_LENGTH = 2000

_ALLOWED_TRANSITIONS: dict[GraphStatus, set[GraphStatus]] = {
    GraphStatus.INITIALIZED: {GraphStatus.CONTEXT_LOADED, GraphStatus.FAILED},
    GraphStatus.CONTEXT_LOADED: {GraphStatus.CONTEXT_ANALYZED, GraphStatus.FAILED},
    GraphStatus.CONTEXT_ANALYZED: {GraphStatus.EVIDENCE_RESEARCHED, GraphStatus.FAILED},
    GraphStatus.EVIDENCE_RESEARCHED: {
        GraphStatus.EVIDENCE_ACCEPTED,
        GraphStatus.EVIDENCE_RESEARCHED,
        GraphStatus.HUMAN_REVIEW,
        GraphStatus.FAILED,
    },
    GraphStatus.EVIDENCE_ACCEPTED: {GraphStatus.REPORT_WRITTEN, GraphStatus.FAILED},
    GraphStatus.REPORT_WRITTEN: {
        GraphStatus.QA_PASSED,
        GraphStatus.REPORT_WRITTEN,
        GraphStatus.EVIDENCE_RESEARCHED,
        GraphStatus.HUMAN_REVIEW,
        GraphStatus.FAILED,
    },
    GraphStatus.QA_PASSED: {GraphStatus.SAVED, GraphStatus.FAILED},
    GraphStatus.HUMAN_REVIEW: set(),
    GraphStatus.FAILED: set(),
    GraphStatus.SAVED: set(),
}


def validate_status_transition(current: GraphStatus, new: GraphStatus) -> bool:
    return new in _ALLOWED_TRANSITIONS.get(current, set())


def sanitize_text(text: str) -> str:
    """claim 텍스트에서 HTML/script 태그를 제거한다."""
    return _HTML_TAG_RE.sub("", text)


def validate_payload_size(
    report: ClinicalReportOutput, max_length: int = MAX_CLAIM_TEXT_LENGTH
) -> list[str]:
    return [
        f"{claim.claim_id}: 길이가 {max_length}자를 초과했습니다."
        for claim in report.claims
        if len(claim.text) > max_length
    ]


def validate_no_foreign_ids(
    report: ClinicalReportOutput, session_id: str, patient_ref_id: str
) -> list[str]:
    allowed = {session_id, patient_ref_id}
    issues: list[str] = []
    for claim in report.claims:
        found = set(_UUID_RE.findall(claim.text))
        foreign = found - allowed
        if foreign:
            issues.append(f"{claim.claim_id}: 허용되지 않은 ID가 포함되어 있습니다: {sorted(foreign)}")
    return issues
