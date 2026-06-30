"""Strands @tool definitions for the report editing chatbot agent."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import urllib.parse
from typing import Any

from loguru import logger
from strands.tools import tool

# Per-request context injected by run_agent() before the agent loop starts.
# Holds: report_id, segments.
_chat_ctx: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("report_chat_context")


def _get_ctx() -> dict[str, Any]:
    try:
        return _chat_ctx.get()
    except LookupError:
        raise RuntimeError("run_agent() 경유로 호출해야 합니다.")


def _run_async_in_thread(coro) -> Any:
    """Run an async coroutine in a new thread, safe even when an event loop is already running."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


# ── Tools ───────────────────────────────────────────────────────────────────


@tool
def read_report_section(section: str) -> str:
    """현재 리포트의 특정 섹션(S/O/A/P) 내용을 반환한다.

    section: S(Subjective), O(Objective), A(Assessment), P(Plan) 중 하나.
    """
    ctx = _get_ctx()
    for seg in ctx.get("segments", []):
        if seg.get("section") == section:
            content = seg.get("content") or "(내용 없음)"
            title = seg.get("title", "")
            return f"[{section}] {title}\n{content}"
    return f"섹션 {section}을 찾을 수 없습니다."


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

    lines = [
        f"[{r.get('title', '출처 미상')}]\n{r.get('content', '')[:400]}"
        for r in results
    ]
    return "\n\n---\n\n".join(lines)


@tool
def save_revision_proposal(
    target_section: str,
    original_text: str,
    proposed_text: str,
    rationale: str,
) -> str:
    """수정 제안의 임상 안전성을 검증한다. 통과하면 치료사 승인 대기 상태로 전환된다.

    target_section: 수정 대상 섹션 코드 (S/O/A/P).
    original_text: 수정 전 원문 (리포트에서 인용).
    proposed_text: 수정 후 제안문.
    rationale: 수정 이유 및 근거.
    """
    from app.agents.report_editing_chatbot.validators import check_clinical_safety

    if target_section not in {"S", "O", "A", "P"}:
        return f"유효하지 않은 섹션 코드: {target_section}. S/O/A/P 중 하나를 사용하세요."

    is_safe, violation = check_clinical_safety(proposed_text)
    if not is_safe:
        return f"안전성 검사 실패: {violation}. 진단 단정 표현을 완화해 다시 시도하세요."

    logger.info(f"[report_chat_tool] 수정안 검증 통과: section={target_section}")
    return "수정안 검증 완료. 치료사가 최종 승인해야 리포트에 반영됩니다."


@tool
def create_ontology_map_link(focus: str) -> str:
    """현재 리포트와 연계된 인사이트맵 링크를 생성한다.

    focus: 강조할 개념이나 키워드. 예: 'MLU', '음운 인식', '언어 발달'.
    """
    ctx = _get_ctx()
    report_id = ctx.get("report_id", "")
    url = f"/insight-map?report_id={report_id}&focus={urllib.parse.quote(focus)}"
    return f"인사이트맵 링크: {url}\n새 창에서 열어 확인하세요."
