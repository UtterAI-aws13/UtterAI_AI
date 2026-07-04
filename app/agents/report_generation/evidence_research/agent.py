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

# evidence_research_gateway_url이 비어있을 때(기본값) 쓰는 in-process tool.
# Gateway 모드에서는 이 대신 kure_retriever Lambda가 노출하는 동일 이름의
# MCP tool을 원격 호출한다(_mcp_gateway_client) - 둘 다 결국 같은 @tool
# 함수(같은 파이프라인)를 실행하므로 검색 결과는 동일해야 한다.
_AGENT_TOOLS = [
    search_korean_evidence,
    search_international_evidence,
    search_clinical_guidelines,
    hybrid_search,
    rerank_evidence,
    fetch_document_section,
    resolve_ontology_synonyms,
]


def _build_model() -> BedrockModel:
    return BedrockModel(
        model_id=cfg.research_agent_model_id,
        region_name="ap-northeast-2",
        temperature=cfg.research_agent_temperature,
        max_tokens=4096,
    )


def build_evidence_research_agent() -> Agent:
    """in-process tool로 동작하는 Agent (Gateway 미설정 시 기본 경로)."""
    return Agent(
        model=_build_model(),
        tools=_AGENT_TOOLS,
        system_prompt=EVIDENCE_RESEARCH_SYSTEM_PROMPT,
    )


def _mcp_gateway_client():
    """kure_retriever Lambda를 노출하는 AgentCore Gateway(MCP, AWS_IAM 인증)에 연결한다.

    참고: https://github.com/aws/mcp-proxy-for-aws - aws_iam_streamablehttp_client가
    호출자의 AWS 자격증명으로 각 요청에 SigV4 서명을 자동으로 붙여준다.
    """
    from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
    from strands.tools.mcp import MCPClient

    return MCPClient(
        lambda: aws_iam_streamablehttp_client(
            endpoint=cfg.evidence_research_gateway_url,
            aws_region=cfg.evidence_research_gateway_region,
            aws_service="bedrock-agentcore",
        )
    )


def research_evidence(
    clinical_context: ClinicalContextOutput,
    search_feedback: dict | None = None,
) -> EvidenceResearchOutput:
    message = (
        f"[Clinical Context]\n{clinical_context.model_dump_json(indent=2)}\n\n"
    )
    if search_feedback:
        message += f"[이전 Critic 피드백 - 반드시 반영]\n{json.dumps(search_feedback, ensure_ascii=False, indent=2)}\n\n"
    message += "위 clinical_priorities/evidence_needs를 지원할 문헌 근거를 검색하라."

    call_kwargs = {
        "structured_output_model": EvidenceResearchOutput,
        "limits": {"turns": cfg.research_agent_max_turns},
    }

    if cfg.evidence_research_gateway_url:
        with _mcp_gateway_client() as mcp_client:
            agent = Agent(
                model=_build_model(),
                tools=mcp_client.list_tools_sync(),
                system_prompt=EVIDENCE_RESEARCH_SYSTEM_PROMPT,
            )
            result = agent(message, **call_kwargs)
    else:
        agent = build_evidence_research_agent()
        result = agent(message, **call_kwargs)

    output = result.structured_output
    if output is None:
        logger.warning("[evidence_research_agent] structured_output이 비어 있음")
        return EvidenceResearchOutput(requirements=[], queries=[], candidates=[])
    return output
