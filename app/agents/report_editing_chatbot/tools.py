"""Strands @tool definitions for the report editing chatbot agent."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
from typing import Any

from loguru import logger
from strands.tools import tool

# Per-request context: set by run_agent() before invoking the agent loop.
# Holds: report_id, report_version, segments, history, proposal (mutable).
_chat_ctx: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("report_chat_context")


def _get_ctx() -> dict[str, Any]:
    try:
        return _chat_ctx.get()
    except LookupError:
        raise RuntimeError("report_chat_context が設定されていません。run_agent() 경유로 호출해야 합니다.")


def _run_async_in_thread(coro) -> Any:
    """Run an async coroutine safely regardless of whether an event loop is already running."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


# ── Tool definitions ────────────────────────────────────────────────────────


@tool
def read_report_section(section: str) -> str:
    """현재 리포트의 특정 섹션(S/O/A/P) 내용을 반환한다.

    section: 조회할 섹션 코드. S(Subjective), O(Objective), A(Assessment), P(Plan) 중 하나.
    """
    ctx = _get_ctx()
    for seg in ctx.get("segments", []):
        if seg.get("section") == section:
            content = seg.get("content") or "(내용 없음)"
            title = seg.get("title", "")
            return f"[{section}] {title}\n{content}"
    return f"섹션 {section}을 찾을 수 없습니다. 현재 리포트에 해당 섹션이 존재하지 않습니다."


@tool
def retrieve_research_evidence(query: str) -> str:
    """언어치료 문헌/가이드에서 임상 근거를 검색한다.

    query: 한국어 임상 질문. 예: 'MLU 해석 기준', '음운 인식 치료 목표 기준'.
    """
    try:
        from app.rag.retriever import retrieve_evidence

        results = _run_async_in_thread(
            retrieve_evidence(metrics={}, session={}, top_k=3, direct_query=query)
        )
    except Exception as exc:
        logger.warning(f"[report_chat_tool] retrieve_research_evidence 실패: {exc}")
        return f"근거 검색에 실패했습니다: {exc}"

    if not results:
        return "관련 문헌 근거를 찾지 못했습니다."

    lines = []
    for r in results:
        snippet = r.get("content", "")[:400]
        lines.append(f"[{r.get('title', '출처 미상')}]\n{snippet}")
    return "\n\n---\n\n".join(lines)


@tool
def validate_clinical_safety(proposed_text: str) -> str:
    """수정 제안 텍스트의 임상 안전성을 검사한다.

    proposed_text: 안전성을 검사할 수정안 텍스트.
    진단 단정 표현이나 근거 없는 단정 표현 여부를 확인한다.
    """
    from app.agents.report_editing_chatbot.validators import check_clinical_safety

    is_safe, message = check_clinical_safety(proposed_text)
    if is_safe:
        return "임상 안전성 검사를 통과했습니다."
    return f"안전성 검사 실패: {message}. 진단을 완화 표현으로 수정하세요."


@tool
def save_revision_proposal(
    target_section: str,
    original_text: str,
    proposed_text: str,
    rationale: str,
) -> str:
    """수정 제안을 확정하고 저장한다. 치료사가 승인해야만 리포트에 반영된다.

    target_section: 수정 대상 섹션 코드 (S/O/A/P).
    original_text: 수정 전 원문 (리포트에서 인용).
    proposed_text: 수정 후 제안문.
    rationale: 수정 이유 및 근거.
    """
    from app.agents.report_editing_chatbot.validators import check_clinical_safety
    from app.agents.report_editing_chatbot.diff import produce_diff_ops

    is_safe, violation = check_clinical_safety(proposed_text)
    if not is_safe:
        return f"수정안을 저장할 수 없습니다. 안전성 검사 실패: {violation}"

    valid_sections = {"S", "O", "A", "P"}
    if target_section not in valid_sections:
        return f"유효하지 않은 섹션 코드입니다: {target_section}. S/O/A/P 중 하나를 사용하세요."

    ctx = _get_ctx()
    ctx["proposal"] = {
        "target_section": target_section,
        "original_text": original_text,
        "proposed_text": proposed_text,
        "rationale": rationale,
        "evidence_refs": [],
        "diff_ops": produce_diff_ops(original_text, proposed_text),
    }
    logger.info(f"[report_chat_tool] 수정안 저장: section={target_section}")
    return "수정안이 저장되었습니다. 치료사가 검토·승인해야 리포트에 반영됩니다."


@tool
def create_ontology_map_link(focus: str) -> str:
    """현재 리포트와 연계된 인사이트맵(온톨로지맵) 링크를 생성한다.

    focus: 강조할 개념이나 키워드. 예: 'MLU', '음운 인식', '언어 발달'.
    """
    ctx = _get_ctx()
    report_id = ctx.get("report_id", "")
    import urllib.parse
    encoded_focus = urllib.parse.quote(focus)
    url = f"/insight-map?report_id={report_id}&focus={encoded_focus}"
    return f"인사이트맵 링크: {url}\n새 창에서 열어 확인하세요."
