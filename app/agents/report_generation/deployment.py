"""AgentCore Runtime deployment wrapper for the 5-agent report generation Graph.

Usage (prod):
    from app.agents.report_generation.deployment import create_agentcore_runtime

    runtime = create_agentcore_runtime()
    runtime.serve()

동일한 runtime_entrypoint.invoke()가 로컬 실행과 AgentCore Runtime 배포에서
그대로 재사용된다 (§21.3) — 이 파일은 AgentCore가 요구하는 이벤트 형식을
invoke() 호출로 변환하는 얇은 어댑터일 뿐이다.

References:
    https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/
"""

from __future__ import annotations

from loguru import logger


def agentcore_entrypoint(event: dict, context: object) -> dict:
    """AgentCore Runtime entrypoint. event를 runtime_entrypoint.invoke() payload로 매핑한다.

    AgentCore Runtime invokes this function with:
        event = {
            "session_id": "...",
            "patient_ref_id": "...",
            "therapist_id": "...",
            "selected_analysis": ["MLU", "TTR"],
            "history_session_count": 5,
            "run_id": "..."  # SQS worker가 미리 생성한 idempotency key
        }
    """
    import asyncio

    from app.agents.report_generation.runtime_entrypoint import invoke

    logger.info(f"[report_generation_agentcore] run_id={event.get('run_id')}")
    return asyncio.run(invoke(event))


def create_agentcore_runtime():
    """AgentCore Runtime 배포용 BedrockAgentCoreApp을 생성한다.

    `bedrock-agentcore` 패키지가 필요하다 (optional dependency).
    Install with: uv add bedrock-agentcore
    """
    try:
        from bedrock_agentcore.runtime import BedrockAgentCoreApp  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "bedrock-agentcore is required for AgentCore Runtime deployment. "
            "Install with: uv add bedrock-agentcore"
        ) from exc

    app = BedrockAgentCoreApp()
    app.entrypoint(agentcore_entrypoint)
    return app
