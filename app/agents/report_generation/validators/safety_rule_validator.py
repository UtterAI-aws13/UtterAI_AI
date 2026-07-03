# DETERMINISTIC_VALIDATION §12.1 항목 8: 금지 표현 rule-based 검사.
# report_editing_chatbot이 이미 갖고 있는 정규식 기반 검사를 그대로 재사용한다
# (진단 단정/근거 없는 단정 표현 패턴을 두 곳에서 따로 관리하지 않는다).
from app.agents.report_editing_chatbot.validators import check_clinical_safety
from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput


def validate_safety(report: ClinicalReportOutput) -> list[str]:
    issues: list[str] = []
    for claim in report.claims:
        is_safe, reason = check_clinical_safety(claim.text)
        if not is_safe:
            issues.append(f"{claim.claim_id}: {reason}")
    return issues
