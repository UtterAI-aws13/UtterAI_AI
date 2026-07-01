"""Strands agent: summarize a selected node/path into plain-language Korean.

Kept on Strands SDK per ADR-003. No tools — the caller (Graph API) already
resolved the path's labels/relations; this agent only phrases them.
"""

from __future__ import annotations

from loguru import logger
from strands import Agent
from strands.models import BedrockModel

from app.config import settings
from app.agents.insight_map.prompts import EXPLAINER_SYSTEM_PROMPT
from app.agents.insight_map.schemas import ExplainResult


def _format_path(path: list[dict]) -> str:
    """path: [{"label": "...", "type": "...", "relation_from_prev": "..."}]"""
    lines = []
    for i, node in enumerate(path):
        relation = node.get("relation_from_prev")
        prefix = f"--[{relation}]--> " if relation and i > 0 else ""
        lines.append(f"{prefix}{node['label']} ({node.get('type', '')})")
    return "\n".join(lines)


def run_explainer(path: list[dict]) -> dict:
    logger.info(f"[insight_map_explainer] path_len={len(path)}")

    if not path:
        return ExplainResult(summary="설명할 경로가 없습니다.").model_dump()

    model = BedrockModel(
        model_id=settings.bedrock_report_model_id,
        region_name=settings.bedrock_region,
        temperature=0.3,
        max_tokens=512,
    )

    agent = Agent(
        model=model,
        tools=[],
        system_prompt=EXPLAINER_SYSTEM_PROMPT,
    )

    result = agent(
        f"다음 경로를 설명해 주세요:\n{_format_path(path)}",
        structured_output_model=ExplainResult,
    )

    output: ExplainResult = result.structured_output or ExplainResult(summary=str(result))
    return output.model_dump()


if __name__ == "__main__":
    import json

    sample_path = [
        {"label": "MLU", "type": "metric"},
        {"label": "짧은 발화", "type": "disorder", "relation_from_prev": "related_to"},
        {"label": "문장 확장 모델링", "type": "intervention", "relation_from_prev": "related_intervention"},
    ]
    print(json.dumps(run_explainer(sample_path), ensure_ascii=False, indent=2))
