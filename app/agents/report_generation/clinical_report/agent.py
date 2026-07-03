# Clinical Report Agent. 원칙적으로 tool 없음 — 검색/DB조회/저장 tool을 주지 않는다 (§11.2).
# 참고: 01_production_5_agent_agentic_rag_design.md §11
from __future__ import annotations

from loguru import logger
from strands import Agent
from strands.models import BedrockModel

from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
from app.agents.report_generation.clinical_report.prompt import CLINICAL_REPORT_SYSTEM_PROMPT
from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput
from app.agents.report_generation.config import report_generation_settings as cfg
from app.agents.report_generation.evidence_critic.schemas import EvidenceCriticOutput
from app.agents.report_generation.models.common import CurrentSession, PatientHistory


def build_clinical_report_agent() -> Agent:
    model = BedrockModel(
        model_id=cfg.report_agent_model_id,
        region_name="ap-northeast-2",
        temperature=cfg.report_agent_temperature,
        max_tokens=8192,
    )
    return Agent(model=model, system_prompt=CLINICAL_REPORT_SYSTEM_PROMPT)


def write_report(
    clinical_context: ClinicalContextOutput,
    current_session: CurrentSession,
    patient_history: PatientHistory,
    critic_result: EvidenceCriticOutput,
    rewrite_feedback: str | None = None,
) -> ClinicalReportOutput:
    accepted_ids = {e.evidence_id for e in critic_result.accepted_evidence}

    message = (
        f"[Clinical Context]\n{clinical_context.model_dump_json(indent=2)}\n\n"
        f"[현재 세션]\n{current_session.model_dump_json(indent=2)}\n\n"
        f"[환자 히스토리]\n{patient_history.model_dump_json(indent=2)}\n\n"
        f"[승인된 문헌 근거 evidence_id 목록 - 이것만 인용 가능]\n{sorted(accepted_ids)}\n\n"
        f"[승인된 근거 상세]\n"
        + "\n".join(
            f"- {e.evidence_id}: {e.supported_claim_scope} (directness={e.directness})"
            for e in critic_result.accepted_evidence
        )
    )
    if rewrite_feedback:
        message += f"\n\n[이전 검증/QA 피드백 - 반드시 반영해 재작성]\n{rewrite_feedback}"
    message += "\n\n위 정보로 SOAP 리포트 초안을 작성하라."

    agent = build_clinical_report_agent()
    result = agent(message, structured_output_model=ClinicalReportOutput)
    output = result.structured_output
    if output is None:
        logger.warning("[clinical_report_agent] structured_output이 비어 있음")
        raise ValueError("clinical report generation returned no structured output")
    return output
