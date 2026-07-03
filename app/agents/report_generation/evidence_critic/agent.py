# Evidence Critic Agent. Research Agent와 반드시 다른 Agent 객체다 (§10.1).
# 참고: 01_production_5_agent_agentic_rag_design.md §10
from __future__ import annotations

from loguru import logger
from strands import Agent
from strands.models import BedrockModel

from app.agents.report_generation.config import report_generation_settings as cfg
from app.agents.report_generation.evidence_critic.prompt import EVIDENCE_CRITIC_SYSTEM_PROMPT
from app.agents.report_generation.evidence_critic.schemas import EvidenceCriticOutput
from app.agents.report_generation.evidence_critic.tools import (
    deduplicate_sources,
    fetch_document_section,
    verify_source_metadata,
)
from app.agents.report_generation.evidence_research.schemas import EvidenceResearchOutput

_AGENT_TOOLS = [fetch_document_section, verify_source_metadata, deduplicate_sources]


def build_evidence_critic_agent() -> Agent:
    model = BedrockModel(
        model_id=cfg.critic_agent_model_id,
        region_name="ap-northeast-2",
        temperature=cfg.critic_agent_temperature,
        max_tokens=4096,
    )
    return Agent(
        model=model,
        tools=_AGENT_TOOLS,
        system_prompt=EVIDENCE_CRITIC_SYSTEM_PROMPT,
    )


def critique_evidence(research_result: EvidenceResearchOutput) -> EvidenceCriticOutput:
    agent = build_evidence_critic_agent()
    message = (
        "[Evidence Research 결과]\n"
        f"{research_result.model_dump_json(indent=2)}\n\n"
        "위 requirements coverage와 candidates 품질을 심사하라."
    )
    result = agent(
        message,
        structured_output_model=EvidenceCriticOutput,
        limits={"turns": cfg.critic_agent_max_turns},
    )
    output = result.structured_output
    if output is None:
        logger.warning("[evidence_critic_agent] structured_output이 비어 있음")
        return EvidenceCriticOutput(decision="HUMAN_REVIEW", search_feedback="critic 출력 파싱 실패")
    return output
