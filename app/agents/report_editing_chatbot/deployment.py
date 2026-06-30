"""AgentCore Runtime deployment helpers.

Usage (prod):
    from app.agents.report_editing_chatbot.deployment import create_agentcore_runtime

    runtime = create_agentcore_runtime()
    runtime.serve()

The agent entrypoint for AgentCore Runtime is `agentcore_entrypoint()`.
It wraps `run_agent()` with the BedrockAgentCoreApp interface.

References:
    https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/
"""

from __future__ import annotations

from loguru import logger


def agentcore_entrypoint(event: dict, context: object) -> dict:
    """AgentCore Runtime entrypoint. Maps AgentCore event to run_agent() call.

    AgentCore Runtime invokes this function with:
        event = {
            "inputText": "<user message>",
            "sessionState": {
                "sessionAttributes": {
                    "report_id": "...",
                    "report_version": "...",
                    "segments_json": "<JSON string>",
                    "history_json": "<JSON string>",
                }
            }
        }
    """
    import json
    from app.agents.report_editing_chatbot.agent import run_agent

    attrs = event.get("sessionState", {}).get("sessionAttributes", {})
    report_id = attrs.get("report_id", "")
    report_version = int(attrs.get("report_version", "1"))
    segments: list[dict] = json.loads(attrs.get("segments_json", "[]"))
    history: list[dict] = json.loads(attrs.get("history_json", "[]"))
    message: str = event.get("inputText", "")

    logger.info(f"[agentcore_entrypoint] report_id={report_id}")
    return run_agent(
        report_id=report_id,
        report_version=report_version,
        message=message,
        segments=segments,
        history=history,
    )


def create_agentcore_runtime():
    """Create a BedrockAgentCoreApp for AgentCore Runtime deployment.

    Requires `bedrock-agentcore` package (optional dependency).
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
