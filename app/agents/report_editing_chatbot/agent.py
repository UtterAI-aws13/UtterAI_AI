"""Strands-based report editing chatbot agent."""

from __future__ import annotations

import json
import re

from loguru import logger
from strands import Agent
from strands.models import BedrockModel

from app.config import settings
from app.agents.report_editing_chatbot.prompts import REPORT_EDITING_SYSTEM_PROMPT
from app.agents.report_editing_chatbot.tools import (
    _chat_ctx,
    read_report_section,
    retrieve_research_evidence,
    validate_clinical_safety,
    save_revision_proposal,
    create_ontology_map_link,
)

_AGENT_TOOLS = [
    read_report_section,
    retrieve_research_evidence,
    validate_clinical_safety,
    save_revision_proposal,
    create_ontology_map_link,
]

_OFF_TOPIC_INTENT = {"intent": "off_topic", "target_section": None, "requires_patch": False}
_OFF_TOPIC_MESSAGE = "이 챗봇은 SOAP 리포트 수정만 지원합니다. 섹션 수정, 근거 확인, 포맷 검토 등을 요청해주세요."


def _build_initial_message(
    message: str,
    segments: list[dict],
    history: list[dict],
) -> str:
    segment_text = "\n".join(
        f"[{seg['section']}] {seg.get('title', '')}\n{seg.get('content') or '(내용 없음)'}"
        for seg in segments
    )

    history_text = ""
    if history:
        history_text = "\n".join(
            f"{'치료사' if m['role'] == 'user' else 'AI'}: {m['content']}"
            for m in history[-6:]
        )
        history_text = f"\n\n[이전 대화]\n{history_text}"

    return (
        f"[현재 리포트]\n{segment_text}"
        f"{history_text}"
        f"\n\n[치료사 요청]\n{message}"
    )


def _parse_agent_output(text: str, stored_proposal: dict | None) -> dict:
    """Extract structured response from agent text output."""
    parsed: dict | str = text

    # Try extracting JSON from markdown code block first
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        try:
            parsed = json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: bare JSON object in text
    if isinstance(parsed, str):
        m2 = re.search(r"\{[\s\S]*\}", text)
        if m2:
            try:
                parsed = json.loads(m2.group())
            except json.JSONDecodeError:
                pass

    if isinstance(parsed, str):
        # Plain text response — no structured JSON found
        intent = {"intent": "general_question", "target_section": None, "requires_patch": False}
        assistant_message = parsed or "응답을 처리하는 중 오류가 발생했습니다. 다시 시도해주세요."
        patch = stored_proposal
    else:
        intent_raw = parsed.get("intent")
        intent = (
            intent_raw
            if isinstance(intent_raw, dict)
            else {"intent": "general_question", "target_section": None, "requires_patch": False}
        )
        assistant_message = str(parsed.get("assistant_message", ""))
        # Tool-stored proposal takes precedence; fall back to JSON patch_proposal field
        json_patch = parsed.get("patch_proposal")
        patch = stored_proposal or (json_patch if isinstance(json_patch, dict) else None)

    # Hard safety: off_topic never carries a patch
    if intent.get("intent") == "off_topic":
        patch = None

    return {
        "intent": intent,
        "assistant_message": assistant_message,
        "patch_proposal": patch,
    }


def run_agent(
    report_id: str,
    report_version: int,
    message: str,
    segments: list[dict],
    history: list[dict],
) -> dict:
    logger.info(f"[report_chat_agent] report_id={report_id} version={report_version} msg_len={len(message)}")

    ctx_value: dict = {
        "report_id": report_id,
        "report_version": report_version,
        "segments": segments,
        "history": history,
        "proposal": None,
    }
    token = _chat_ctx.set(ctx_value)

    try:
        model = BedrockModel(
            model_id=settings.bedrock_report_model_id,
            region_name=settings.bedrock_region,
            temperature=0.3,
            max_tokens=2048,
        )

        agent = Agent(
            model=model,
            tools=_AGENT_TOOLS,
            system_prompt=REPORT_EDITING_SYSTEM_PROMPT,
        )

        initial_message = _build_initial_message(message, segments, history)
        result = agent(initial_message)
        response_text = str(result)

        stored_proposal = ctx_value.get("proposal")
        parsed = _parse_agent_output(response_text, stored_proposal)

        logger.info(
            f"[report_chat_agent] intent={parsed['intent'].get('intent')} "
            f"has_patch={parsed['patch_proposal'] is not None}"
        )
        return parsed

    finally:
        _chat_ctx.reset(token)
