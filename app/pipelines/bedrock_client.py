import json
import re
import time

import boto3
from botocore.exceptions import ClientError
from loguru import logger

from app.config import settings

_client = None

_RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "InternalServerException",
}

MAX_RETRIES = 3
_BACKOFF_BASE = 2


def get_bedrock_client():
    global _client
    if _client is None:
        logger.info(f"[bedrock] client 초기화 region={settings.bedrock_region}")
        _client = boto3.client("bedrock-runtime", region_name=settings.bedrock_region)
    return _client


def invoke_claude(prompt: str, max_tokens: int = 2048) -> dict:
    model_id = settings.bedrock_report_model_id
    logger.info(f"[bedrock] invoke_claude 시작 model_id={model_id} prompt_len={len(prompt)}")

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "messages": [{"role": "user", "content": prompt}],
    }
    body_json = json.dumps(body)

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = get_bedrock_client().invoke_model(
                modelId=model_id,
                body=body_json,
                contentType="application/json",
                accept="application/json",
            )
            logger.info(f"[bedrock] invoke_model 응답 수신 attempt={attempt + 1}")
            break
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in _RETRYABLE_ERROR_CODES and attempt < MAX_RETRIES - 1:
                wait = _BACKOFF_BASE ** attempt
                logger.warning(
                    f"[bedrock] 재시도 가능 오류 attempt={attempt + 1}/{MAX_RETRIES} "
                    f"error_code={error_code} wait={wait}s"
                )
                time.sleep(wait)
                last_exc = exc
                continue
            logger.error(f"[bedrock] invoke_model 실패 error_code={error_code} error={exc}")
            raise
        except Exception as exc:
            logger.error(f"[bedrock] invoke_model 실패 attempt={attempt + 1} error={exc}")
            raise
    else:
        logger.error(f"[bedrock] {MAX_RETRIES}회 재시도 모두 실패")
        raise last_exc  # type: ignore[misc]

    try:
        raw_body = response["body"].read()
        parsed = json.loads(raw_body)
        text = parsed["content"][0]["text"]
        logger.info(f"[bedrock] 응답 파싱 완료 text_len={len(text)}")
    except Exception as exc:
        logger.error(f"[bedrock] 응답 파싱 실패 error={exc}")
        raise

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
