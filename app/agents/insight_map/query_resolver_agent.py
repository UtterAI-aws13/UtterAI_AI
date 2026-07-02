"""Strands agent: natural-language search query -> ontology concept candidates.

Kept on Strands SDK per ADR-003 (exception to ADR-002's Managed Harness
default) — this agent is stateless, tool-scoped, and must run locally.
"""

from __future__ import annotations

from loguru import logger
from strands import Agent
from strands.models import BedrockModel

from app.config import settings
from app.agents.insight_map.prompts import QUERY_RESOLVER_SYSTEM_PROMPT
from app.agents.insight_map.schemas import QueryResolveResult
from app.agents.insight_map.tools import search_ontology_concepts, search_synonyms

_AGENT_TOOLS = [search_ontology_concepts, search_synonyms]


def run_query_resolver(query: str) -> dict:
    logger.info(f"[insight_map_query_resolver] query={query!r}")

    model = BedrockModel(
        model_id=settings.bedrock_report_model_id,
        region_name=settings.bedrock_region,
        temperature=0.1,
        max_tokens=1024,
    )

    agent = Agent(
        model=model,
        tools=_AGENT_TOOLS,
        system_prompt=QUERY_RESOLVER_SYSTEM_PROMPT,
    )

    result = agent(
        f"검색어: {query}",
        structured_output_model=QueryResolveResult,
    )

    output: QueryResolveResult = result.structured_output or QueryResolveResult()
    logger.info(f"[insight_map_query_resolver] resolved={len(output.resolved_concepts)}개")
    return output.model_dump()


if __name__ == "__main__":
    import json

    print(json.dumps(run_query_resolver("낮은 MLU"), ensure_ascii=False, indent=2))
