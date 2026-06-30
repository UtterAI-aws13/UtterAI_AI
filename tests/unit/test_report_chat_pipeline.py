"""Unit tests for report_chat_pipeline logic (no Bedrock call)."""

import json

import pytest

from app.pipelines.report_chat_pipeline import (
    _build_user_prompt,
    _fallback_response,
    _parse_response,
)


# ── _parse_response ───────────────────────────────────────────────────────────

class TestParseResponse:
    def test_off_topic_forces_null_patch(self):
        raw = {
            "intent": {"intent": "off_topic", "target_section": None, "requires_patch": False},
            "assistant_message": "이 챗봇은 SOAP 리포트 수정만 지원합니다.",
            # LLM이 실수로 patch를 채워 반환해도 강제 null
            "patch_proposal": {
                "target_section": "A",
                "original_text": "원문",
                "proposed_text": "수정안",
                "rationale": "",
                "evidence_refs": [],
            },
        }
        result = _parse_response(raw)
        assert result["intent"]["intent"] == "off_topic"
        assert result["patch_proposal"] is None

    def test_rewrite_section_preserves_patch(self):
        raw = {
            "intent": {"intent": "rewrite_section", "target_section": "A", "requires_patch": True},
            "assistant_message": "수정 제안입니다.",
            "patch_proposal": {
                "target_section": "A",
                "original_text": "원문",
                "proposed_text": "수정안",
                "rationale": "임상 표현 강화",
                "evidence_refs": [],
            },
        }
        result = _parse_response(raw)
        assert result["intent"]["intent"] == "rewrite_section"
        assert result["patch_proposal"] is not None
        assert result["patch_proposal"]["target_section"] == "A"

    def test_general_question_no_patch(self):
        raw = {
            "intent": {"intent": "general_question", "target_section": None, "requires_patch": False},
            "assistant_message": "MLU는 Mean Length of Utterance입니다.",
            "patch_proposal": None,
        }
        result = _parse_response(raw)
        assert result["patch_proposal"] is None
        assert result["assistant_message"] == "MLU는 Mean Length of Utterance입니다."

    def test_invalid_intent_field_defaults_to_general_question(self):
        raw = {
            "intent": "잘못된_형식",  # dict이 아닌 str
            "assistant_message": "응답",
            "patch_proposal": None,
        }
        result = _parse_response(raw)
        assert result["intent"]["intent"] == "general_question"

    def test_json_string_is_parsed(self):
        payload = {
            "intent": {"intent": "format_check", "target_section": "ALL", "requires_patch": False},
            "assistant_message": "형식 이상 없습니다.",
            "patch_proposal": None,
        }
        raw_str = json.dumps(payload)
        result = _parse_response(raw_str)
        assert result["intent"]["intent"] == "format_check"

    def test_plain_string_falls_back(self):
        result = _parse_response("저는 AI 어시스턴트입니다.")
        assert result["intent"]["intent"] == "general_question"
        assert "저는 AI 어시스턴트입니다." in result["assistant_message"]

    def test_json_string_wrapped_in_markdown_is_parsed(self):
        payload = {
            "intent": {"intent": "show_evidence", "target_section": "O", "requires_patch": False},
            "assistant_message": "MLU 근거입니다.",
            "patch_proposal": None,
        }
        raw_str = f"```json\n{json.dumps(payload)}\n```"
        result = _parse_response(raw_str)
        assert result["intent"]["intent"] == "show_evidence"


# ── _build_user_prompt ────────────────────────────────────────────────────────

class TestBuildUserPrompt:
    def _segments(self):
        return [
            {"section": "SUBJECTIVE", "title": "주관적", "content": "아동이 불편함을 호소함"},
            {"section": "OBJECTIVE", "title": "객관적", "content": "MLU 2.1"},
            {"section": "ASSESSMENT", "title": "평가", "content": "언어 발달 지연 의심"},
            {"section": "PLAN", "title": "계획", "content": "주 2회 치료"},
        ]

    def test_all_sections_in_prompt(self):
        prompt = _build_user_prompt("A 섹션 써줘", self._segments(), [])
        for section in ("SUBJECTIVE", "OBJECTIVE", "ASSESSMENT", "PLAN"):
            assert section in prompt

    def test_user_message_in_prompt(self):
        message = "치료 목표를 3개로 정리해줘"
        prompt = _build_user_prompt(message, self._segments(), [])
        assert message in prompt
        assert "[치료사 요청]" in prompt

    def test_no_history_block_when_history_empty(self):
        prompt = _build_user_prompt("질문", self._segments(), [])
        assert "[이전 대화]" not in prompt

    def test_history_included_when_present(self):
        history = [
            {"role": "user", "content": "근거 보여줘"},
            {"role": "assistant", "content": "MLU 근거입니다."},
        ]
        prompt = _build_user_prompt("이어서 설명해줘", self._segments(), history)
        assert "[이전 대화]" in prompt
        assert "근거 보여줘" in prompt

    def test_history_limited_to_last_6(self):
        history = [{"role": "user", "content": f"메시지 {i}"} for i in range(20)]
        prompt = _build_user_prompt("질문", self._segments(), history)
        assert "메시지 0" not in prompt
        assert "메시지 14" in prompt or "메시지 19" in prompt

    def test_empty_content_shows_placeholder(self):
        segments = [{"section": "ASSESSMENT", "title": "평가", "content": None}]
        prompt = _build_user_prompt("질문", segments, [])
        assert "(내용 없음)" in prompt