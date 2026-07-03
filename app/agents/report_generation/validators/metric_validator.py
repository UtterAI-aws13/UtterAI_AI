# DETERMINISTIC_VALIDATION §12.1 항목 6-7: 현재 지표와 trend 문장 일치,
# 미측정 지표 언급 여부.
#
# patient_evidence_refs가 "metric_trend:{METRIC}:..." 형식(§17 예시)일 때만
# 검증 가능하다. 자유 텍스트에서 "개선/악화" 여부를 NLP로 판정하지 않는다 —
# 그건 Quality Assurance Agent(§13)의 몫이고, 여기서는 구조화된 참조만 대조한다.
from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput

_METRIC_TREND_REF_PREFIX = "metric_trend"


def validate_metric_consistency(
    report: ClinicalReportOutput, context: ClinicalContextOutput
) -> list[str]:
    issues: list[str] = []
    trend_by_metric = {
        finding.metric: finding.trend_direction
        for finding in [*context.primary_findings, *context.secondary_findings]
    }

    for claim in report.claims:
        for ref in claim.patient_evidence_refs:
            parts = ref.split(":")
            if len(parts) < 2 or parts[0] != _METRIC_TREND_REF_PREFIX:
                continue
            metric = parts[1]
            trend = trend_by_metric.get(metric)
            if trend is None:
                issues.append(
                    f"{claim.claim_id}: {metric}는 Clinical Context Agent가 다루지 않은 지표입니다."
                )
            elif trend == "INSUFFICIENT_DATA":
                issues.append(
                    f"{claim.claim_id}: {metric}는 INSUFFICIENT_DATA인데 추세를 서술했습니다."
                )

    return issues
