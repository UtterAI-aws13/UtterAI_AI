import json
import re

import boto3
from loguru import logger

from app.config import settings

_client = None


def get_agentcore_client():
    global _client
    if _client is None:
        logger.info(f"[agentcore] client 초기화 region={settings.bedrock_region}")
        _client = boto3.client("bedrock-agentcore", region_name=settings.bedrock_region)
    return _client


def invoke_agent(
    prompt: str,
    session_id: str,
    max_tokens: int = 2048,
) -> dict:
    """AgentCore Runtime을 호출한다.

    Claude가 search_evidence tool을 필요한 만큼 호출한 뒤 SOAP Note를 생성한다.
    AgentCore Memory가 session_id 기반으로 이전 세션 컨텍스트를 자동 주입한다.
    """
    client = get_agentcore_client()
    agent_id = settings.agentcore_agent_id
    alias_id = settings.agentcore_agent_alias_id

    logger.info(f"[agentcore] invoke_agent 시작 session_id={session_id} agent_id={agent_id}")

    invoke_kwargs: dict = {
        "agentRuntimeArn": agent_id,
        "runtimeSessionId": session_id,
        "payload": json.dumps({"inputText": prompt}).encode("utf-8"),
        "contentType": "application/json",
        "accept": "application/json",
    }
    if alias_id:
        invoke_kwargs["qualifier"] = alias_id

    response = client.invoke_agent_runtime(**invoke_kwargs)

    raw = response["response"].read()
    full_text = raw.decode("utf-8") if raw else ""

    logger.info(f"[agentcore] 응답 수신 완료 text_len={len(full_text)}")
    return _parse_json(full_text)


def _parse_json(text: str) -> dict:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {
        "soap_note": {"subjective": "", "objective": text, "assessment": "", "plan": ""},
        "parse_error": True,
        "disclaimer": "치료사 검토가 필요한 AI 생성 초안입니다.",
    }