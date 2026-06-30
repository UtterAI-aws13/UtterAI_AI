"""Report chat pipeline: intent classification + response generation via Bedrock."""

from __future__ import annotations

import json
import re

from loguru import logger

from app.config import settings
from app.pipelines.bedrock_client import invoke_claude

_SYSTEM_PROMPT = """너는 언어재활사의 SOAP 리포트 수정 보조 AI다.

역할:
- SOAP 리포트 수정, 설명, 검토, 근거 확인 요청만 처리한다.
- 진단을 확정하지 않는다. 진단명 확정 요청은 완화 표현으로 유도한다.
- 수정 제안 시 원문, 수정안, 수정 이유를 항상 제시한다.
- 근거가 부족한 경우 "근거 부족"이라고 명시한다.
- 환자 데이터 근거와 문헌 근거를 구분한다.
- 리포트, 환자 데이터, 언어치료 임상과 무관한 질문(예: 저녁 메뉴 추천)에는 답하지 않는다.

반환 형식은 반드시 아래 JSON이어야 한다:
{
  "intent": {
    "intent": "<intent_type>",
    "target_section": "<S|O|A|P|ALL|null>",
    "requires_patch": <true|false>
  },
  "assistant_message": "<사용자에게 보여줄 응답 텍스트>",
  "patch_proposal": null 또는 {
    "target_section": "<S|O|A|P>",
    "original_text": "<수정 전 원문>",
    "proposed_text": "<수정 후 제안문>",
    "rationale": "<수정 이유>",
    "evidence_refs": []
  }
}

intent_type 목록:
- rewrite_section: 섹션 수정 요청
- simplify_for_caregiver: 보호자용 쉬운 표현 요청
- verify_grounding: 근거 없는 문장 확인 요청
- show_evidence: 근거 조회 요청
- compare_history: 이전 회기 비교 요청
- revise_goals: 치료 목표 수정 요청
- format_check: SOAP 형식 검토 요청
- apply_patch: 직전 수정안 승인 (patch_proposal은 null)
- general_question: 임상 관련 일반 질문
- off_topic: 리포트/언어치료와 무관한 질문

off_topic이면 assistant_message는 반드시 다음 문장이어야 한다:
"이 챗봇은 SOAP 리포트 수정만 지원합니다. 섹션 수정, 근거 확인, 포맷 검토 등을 요청해주세요."
off_topic이면 patch_proposal은 반드시 null이어야 한다.

수정 제안(patch_proposal)이 있을 때:
- requires_patch는 true
- patch_proposal의 original_text는 리포트의 실제 해당 섹션 content에서 인용
- 자동 반영을 단독으로 결정하지 않는다. 사용자가 승인해야 반영된다고 명시한다.
"""


def _build_user_prompt(
    message: str,
    segments: list[dict],
    history: list[dict],
) -> str:
    segment_text = "\n".join(
        f"[{seg['section']}] {seg.get('title', '')}\n{seg.get('content', '(내용 없음)')}"
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


def _parse_response(raw: dict | str) -> dict:
    if isinstance(raw, str):
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                raw = json.loads(m.group())
            except json.JSONDecodeError:
                return _fallback_response(raw)
        else:
            return _fallback_response(str(raw))

    if not isinstance(raw, dict):
        return _fallback_response(str(raw))

    intent = raw.get("intent")
    if not isinstance(intent, dict):
        intent = {"intent": "general_question", "target_section": None, "requires_patch": False}

    patch = raw.get("patch_proposal")
    if patch is not None and not isinstance(patch, dict):
        patch = None

    if intent.get("intent") == "off_topic":
        patch = None

    return {
        "intent": intent,
        "assistant_message": str(raw.get("assistant_message", "")),
        "patch_proposal": patch,
    }


def _fallback_response(raw_text: str) -> dict:
    return {
        "intent": {"intent": "general_question", "target_section": None, "requires_patch": False},
        "assistant_message": raw_text or "응답을 처리하는 중 오류가 발생했습니다. 다시 시도해주세요.",
        "patch_proposal": None,
    }


def run_report_chat(
    report_id: str,
    report_version: int,
    message: str,
    segments: list[dict],
    history: list[dict],
) -> dict:
    logger.info(f"[report_chat] report_id={report_id} version={report_version} msg_len={len(message)}")

    user_prompt = _build_user_prompt(message, segments, history)

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "temperature": 0.3,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    import json as _json
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("bedrock-runtime", region_name=settings.bedrock_region)
    model_id = settings.bedrock_report_model_id

    try:
        resp = client.invoke_model(
            modelId=model_id,
            body=_json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        raw_body = _json.loads(resp["body"].read())
        text = raw_body["content"][0]["text"]
        logger.info(f"[report_chat] bedrock 응답 text_len={len(text)}")
    except ClientError as exc:
        logger.error(f"[report_chat] bedrock 호출 실패: {exc}")
        raise

    # bedrock_client._parse_json이 text를 dict로 파싱 시도하지만
    # report_chat은 system prompt가 있는 별도 포맷이므로 직접 파싱한다.
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = text

    result = _parse_response(parsed)
    logger.info(f"[report_chat] intent={result['intent'].get('intent')} has_patch={result['patch_proposal'] is not None}")
    return result