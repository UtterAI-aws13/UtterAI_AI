# AgentCore Runtime과 로컬 실행이 공유하는 단일 진입점.
# 참고: 01_production_5_agent_agentic_rag_design.md §21.2, §21.3
#
# 로컬 실행 (AWS 없이, Bedrock 호출만 필요):
#   python -m app.agents.report_generation.runtime_entrypoint --fixture <path/to/fixture.json>
#
# fixture JSON 형식:
#   {
#     "session_id": "...", "patient_ref_id": "...", "therapist_id": "...",
#     "selected_analysis": ["MLU", "TTR"], "history_session_count": 5
#   }
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from loguru import logger

from app.agents.report_generation.errors import ReportGenerationError
from app.agents.report_generation.graph import build_default_dependencies, run_report_generation
from app.agents.report_generation.graph_state import ReportGenerationState


def _serialize_result(state: ReportGenerationState) -> dict[str, Any]:
    """환자 원문/전체 prompt는 반환하지 않는다 (§19.2, §22.3) — 상태 요약만 반환."""
    return {
        "run_id": state.run_id,
        "status": state.status.value,
        "failure_code": state.failure_code,
        "retry_budget": state.retry_budget.model_dump(),
        "quality_scores": (state.qa_result or {}).get("scores"),
    }


async def invoke(payload: dict[str, Any]) -> dict[str, Any]:
    """AgentCore Runtime과 로컬 실행이 공유하는 단일 진입점.

    payload: {session_id, patient_ref_id, therapist_id, selected_analysis,
              history_session_count, run_id(optional)}

    Graph 내부 실패(FAILED_CONTEXT_ANALYSIS 등)는 이미 GraphState.status=FAILED로
    정리되어 정상 반환된다. run_report_generation() 자체가 그래프 시작 전에
    던지는 예외(중복 실행, 잘못된 session/therapist_id 등)만 여기서 잡아
    AgentCore/로컬 호출자에게 항상 JSON 결과를 반환하고 raw 예외를 흘리지 않는다.
    """
    deps = build_default_dependencies()
    try:
        state = await run_report_generation(
            session_id=payload["session_id"],
            patient_ref_id=payload["patient_ref_id"],
            therapist_id=payload["therapist_id"],
            selected_analysis=payload["selected_analysis"],
            history_session_count=payload.get("history_session_count", 5),
            deps=deps,
            run_id=payload.get("run_id"),
        )
    except ReportGenerationError as exc:
        return {
            "run_id": payload.get("run_id"),
            "status": "FAILED",
            "failure_code": exc.failure_code.value,
            "retry_budget": None,
            "quality_scores": None,
        }
    return _serialize_result(state)


def _run_fixture(fixture_path: str) -> None:
    with open(fixture_path, encoding="utf-8") as f:
        payload = json.load(f)

    logger.info(f"[report_generation_runtime] fixture={fixture_path} 실행 시작")
    result = asyncio.run(invoke(payload))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="리포트 생성 Graph 로컬 실행기")
    parser.add_argument("--fixture", required=True, help="입력 payload JSON 파일 경로")
    args = parser.parse_args()
    _run_fixture(args.fixture)
