# Quality Assurance Agent. tool 없음, 독립 최종 심사자다 (§13.1).
# 참고: 01_production_5_agent_agentic_rag_design.md §13
from __future__ import annotations

from loguru import logger
from strands import Agent
from strands.models import BedrockModel

from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput
from app.agents.report_generation.config import report_generation_settings as cfg
from app.agents.report_generation.evidence_critic.schemas import EvidenceCriticOutput
from app.agents.report_generation.models.common import CurrentSession, PatientHistory
from app.agents.report_generation.quality_assurance.prompt import QUALITY_ASSURANCE_SYSTEM_PROMPT
from app.agents.report_generation.quality_assurance.schemas import QualityAssuranceOutput


def build_quality_assurance_agent() -> Agent:
    model = BedrockModel(
        model_id=cfg.qa_agent_model_id,
        region_name="ap-northeast-2",
        temperature=cfg.qa_agent_temperature,
        max_tokens=4096,
    )
    return Agent(model=model, system_prompt=QUALITY_ASSURANCE_SYSTEM_PROMPT)


def _enforce_pass_gate(output: QualityAssuranceOutput) -> QualityAssuranceOutput:
    """§13.4 PASS gate를 LLM 판정과 무관하게 코드로 재확인한다.

    LLM이 PASS라고 해도 threshold 미달이거나 CRITICAL/BLOCKING issue가 있으면
    REWRITE로 강등한다 (§0.2: LLM 평가만으로 저장 조건을 판정하지 않는다).
    """
    if output.decision != "PASS":
        return output

    scores = output.scores
    has_blocking = any(i.severity in ("BLOCKING", "CRITICAL") for i in output.issues)
    thresholds_met = (
        scores.groundedness >= cfg.qa_groundedness_threshold
        and scores.citation_correctness >= cfg.qa_citation_threshold
        and scores.patient_context_fidelity >= cfg.qa_context_fidelity_threshold
        and scores.longitudinal_consistency >= cfg.qa_longitudinal_threshold
        and scores.soap_compliance >= cfg.qa_soap_threshold
        and scores.safety == 1.0
        and scores.overall >= cfg.qa_overall_threshold
    )

    if has_blocking or not thresholds_met:
        return output.model_copy(
            update={
                "decision": "REWRITE",
                "route_reason": (
                    f"{output.route_reason} (deterministic gate: threshold 미달 또는 "
                    "BLOCKING/CRITICAL issue 존재로 PASS를 REWRITE로 강등)"
                ),
            }
        )
    return output


def assess_quality(
    clinical_context: ClinicalContextOutput,
    current_session: CurrentSession,
    patient_history: PatientHistory,
    critic_result: EvidenceCriticOutput,
    report: ClinicalReportOutput,
) -> QualityAssuranceOutput:
    message = (
        f"[Clinical Context]\n{clinical_context.model_dump_json(indent=2)}\n\n"
        f"[현재 세션]\n{current_session.model_dump_json(indent=2)}\n\n"
        f"[환자 히스토리]\n{patient_history.model_dump_json(indent=2)}\n\n"
        f"[승인된 근거]\n{critic_result.model_dump_json(indent=2)}\n\n"
        f"[리포트 초안]\n{report.model_dump_json(indent=2)}\n\n"
        "위 리포트를 최종 심사하라."
    )

    agent = build_quality_assurance_agent()
    result = agent(message, structured_output_model=QualityAssuranceOutput)
    output = result.structured_output
    if output is None:
        logger.warning("[quality_assurance_agent] structured_output이 비어 있음")
        raise ValueError("quality assurance returned no structured output")
    return _enforce_pass_gate(output)
