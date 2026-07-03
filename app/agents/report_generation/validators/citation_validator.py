# DETERMINISTIC_VALIDATION §12.1 항목 4-5, §11.6 claim trace 규칙.
# A/P 섹션 핵심 claim은 반드시 근거 참조가 있어야 하고, 인용된 문헌 근거는
# Evidence Critic이 승인한 evidence_id 집합에 포함되어야 한다.
from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput

_REQUIRES_EVIDENCE_SECTIONS = ("A", "P")


def validate_citations(
    report: ClinicalReportOutput, accepted_evidence_ids: set[str]
) -> list[str]:
    issues: list[str] = []

    for claim in report.claims:
        if claim.section in _REQUIRES_EVIDENCE_SECTIONS:
            if not claim.patient_evidence_refs and not claim.literature_evidence_refs:
                issues.append(
                    f"{claim.claim_id}: {claim.section} 섹션 claim에 근거 참조가 없습니다."
                )
        for ref in claim.literature_evidence_refs:
            if ref not in accepted_evidence_ids:
                issues.append(
                    f"{claim.claim_id}: 승인되지 않은 문헌 근거({ref})를 인용했습니다."
                )

    return issues
