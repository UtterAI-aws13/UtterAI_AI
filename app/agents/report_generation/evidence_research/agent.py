# Evidence Research Agent. 참고: 01_production_5_agent_agentic_rag_design.md §9
from __future__ import annotations

import json

from loguru import logger
from strands import Agent
from strands.models import BedrockModel

from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
from app.agents.report_generation.config import report_generation_settings as cfg
from app.agents.report_generation.evidence_research.prompt import EVIDENCE_RESEARCH_SYSTEM_PROMPT
from app.agents.report_generation.evidence_research.schemas import EvidenceResearchOutput
from app.agents.report_generation.evidence_research.tools import (
    fetch_document_section,
    hybrid_search,
    rerank_evidence,
    resolve_ontology_synonyms,
    search_clinical_guidelines,
    search_international_evidence,
    search_korean_evidence,
)

_AGENT_TOOLS = [
    search_korean_evidence,
    search_international_evidence,
    search_clinical_guidelines,
    hybrid_search,
    rerank_evidence,
    fetch_document_section,
    resolve_ontology_synonyms,
]


def build_evidence_research_agent() -> Agent:
    model = BedrockModel(
        model_id=cfg.research_agent_model_id,
        region_name="ap-northeast-2",
        temperature=cfg.research_agent_temperature,
        max_tokens=4096,
    )
    return Agent(
        model=model,
        tools=_AGENT_TOOLS,
        system_prompt=EVIDENCE_RESEARCH_SYSTEM_PROMPT,
    )


def research_evidence(
    clinical_context: ClinicalContextOutput,
    search_feedback: dict | None = None,
) -> EvidenceResearchOutput:
    agent = build_evidence_research_agent()

    message = (
        f"[Clinical Context]\n{clinical_context.model_dump_json(indent=2)}\n\n"
    )
    if search_feedback:
        message += f"[이전 Critic 피드백 - 반드시 반영]\n{json.dumps(search_feedback, ensure_ascii=False, indent=2)}\n\n"
    message += "위 clinical_priorities/evidence_needs를 지원할 문헌 근거를 검색하라."

    result = agent(
        message,
        structured_output_model=EvidenceResearchOutput,
        limits={"turns": cfg.research_agent_max_turns},
    )
    output = result.structured_output
    if output is None:
        logger.warning("[evidence_research_agent] structured_output이 비어 있음")
        return EvidenceResearchOutput(requirements=[], queries=[], candidates=[])
    return output
