"""Strands-based report editing chatbot agent."""

from __future__ import annotations

from typing import Literal, Optional

from loguru import logger
from pydantic import BaseModel, Field
from strands import Agent
from strands.models import BedrockModel

from app.config import settings
from app.agents.report_editing_chatbot.prompts import REPORT_EDITING_SYSTEM_PROMPT
from app.agents.report_editing_chatbot.tools import (
    _chat_ctx,
    read_report_section,
    retrieve_research_evidence,
    save_revision_proposal,
    create_ontology_map_link,
)

# ── Response schema ──────────────────────────────────────────────────────────

SectionCode = Literal["S", "O", "A", "P"]


class IntentClassification(BaseModel):
    intent: str = "general_question"
    target_section: Optional[SectionCode] = None
    requires_patch: bool = False


class PatchProposal(BaseModel):
    # report_patch_proposals.target_section은 VARCHAR(20) 단일 섹션 코드용 컬럼이다.
    # 자유 텍스트를 허용하면 모델이 "S, A, P (Multiple sections)" 같은 값을 반환해
    # DB insert가 StringDataRightTruncation으로 실패하고 채팅 응답 전체가 죽는다.
    target_section: SectionCode
    original_text: str
    proposed_text: str
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    intent: IntentClassification = Field(default_factory=IntentClassification)
    assistant_message: str = ""
    patch_proposal: Optional[PatchProposal] = None


# ── Agent ────────────────────────────────────────────────────────────────────

_AGENT_TOOLS = [
    read_report_section,
    retrieve_research_evidence,
    save_revision_proposal,
    create_ontology_map_link,
]


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


def run_agent(
    report_id: str,
    report_version: int,
    message: str,
    segments: list[dict],
    history: list[dict],
) -> dict:
    logger.info(f"[report_chat_agent] report_id={report_id} version={report_version} msg_len={len(message)}")

    token = _chat_ctx.set({"report_id": report_id, "segments": segments})
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

        result = agent(
            _build_initial_message(message, segments, history),
            structured_output_model=ChatResponse,
        )

        output: ChatResponse = result.structured_output or ChatResponse(
            assistant_message=str(result)
        )

        # off_topic은 서버 레벨에서 patch를 강제 제거
        if output.intent.intent == "off_topic":
            output.patch_proposal = None

        response = output.model_dump()
        logger.info(
            f"[report_chat_agent] intent={output.intent.intent} "
            f"has_patch={output.patch_proposal is not None}"
        )
        return response

    finally:
        _chat_ctx.reset(token)
