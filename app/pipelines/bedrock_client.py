import json
import re

import boto3

from app.config import settings

_client = None


def get_bedrock_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=settings.bedrock_region)
    return _client


def invoke_claude(prompt: str, max_tokens: int = 2048) -> dict:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "messages": [{"role": "user", "content": prompt}],
    }

    response = get_bedrock_client().invoke_model(
        modelId=settings.bedrock_report_model_id,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )

    text = json.loads(response["body"].read())["content"][0]["text"]
    return _parse_json(text)


def _parse_json(text: str) -> dict:
    # ```json ... ``` 블록 추출 시도
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 첫 번째 { ... } 블록 추출 시도
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
