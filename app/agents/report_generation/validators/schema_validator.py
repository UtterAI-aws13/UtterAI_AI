# DETERMINISTIC_VALIDATION §12.1 항목 1-3: schema, 필수 SOAP section, claim ID 유일성.
# Pydantic이 타입/필수 필드는 이미 강제하므로, 여기서는 그 이상의 구조 규칙만 검사한다.
from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput

_SOAP_SECTIONS = ("S", "O", "A", "P")


def validate_schema(report: ClinicalReportOutput) -> list[str]:
    issues: list[str] = []

    claim_ids = [c.claim_id for c in report.claims]
    if len(claim_ids) != len(set(claim_ids)):
        duplicates = {cid for cid in claim_ids if claim_ids.count(cid) > 1}
        issues.append(f"claim_id가 중복되었습니다: {sorted(duplicates)}")

    for section in _SOAP_SECTIONS:
        if not getattr(report.soap, section).strip():
            issues.append(f"SOAP {section} 섹션이 비어 있습니다.")

    return issues
