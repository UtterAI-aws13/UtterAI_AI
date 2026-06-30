"""Unit tests for the Strands-based report editing chatbot agent (no Bedrock/tool calls)."""

from __future__ import annotations

import json

import pytest

from app.agents.report_editing_chatbot.agent import _build_initial_message, _parse_agent_output
from app.agents.report_editing_chatbot.validators import check_clinical_safety
from app.agents.report_editing_chatbot.diff import produce_diff_ops, render_diff_text


# ── _parse_agent_output ──────────────────────────────────────────────────────

class TestParseAgentOutput:
    def test_off_topic_forces_null_patch(self):
        raw = json.dumps({
            "intent": {"intent": "off_topic", "target_section": None, "requires_patch": False},
            "assistant_message": "이 챗봇은 SOAP 리포트 수정만 지원합니다.",
            "patch_proposal": {
                "target_section": "A",
                "original_text": "원문",
                "proposed_text": "수정안",
                "rationale": "",
                "evidence_refs": [],
            },
        })
        result = _parse_agent_output(raw, stored_proposal=None)
        assert result["intent"]["intent"] == "off_topic"
        assert result["patch_proposal"] is None

    def test_rewrite_section_preserves_json_patch(self):
        patch = {
            "target_section": "A",
            "original_text": "원문",
            "proposed_text": "수정안",
            "rationale": "임상 표현 강화",
            "evidence_refs": [],
        }
        raw = json.dumps({
            "intent": {"intent": "rewrite_section", "target_section": "A", "requires_patch": True},
            "assistant_message": "수정 제안입니다.",
            "patch_proposal": patch,
        })
        result = _parse_agent_output(raw, stored_proposal=None)
        assert result["intent"]["intent"] == "rewrite_section"
        assert result["patch_proposal"] is not None
        assert result["patch_proposal"]["target_section"] == "A"

    def test_stored_proposal_takes_precedence_over_json_patch(self):
        stored = {
            "target_section": "P",
            "original_text": "원문P",
            "proposed_text": "수정P",
            "rationale": "이유",
            "evidence_refs": [],
        }
        raw = json.dumps({
            "intent": {"intent": "rewrite_section", "target_section": "A", "requires_patch": True},
            "assistant_message": "수정 제안입니다.",
            "patch_proposal": {"target_section": "A", "original_text": "x", "proposed_text": "y", "rationale": ""},
        })
        result = _parse_agent_output(raw, stored_proposal=stored)
        assert result["patch_proposal"]["target_section"] == "P"

    def test_general_question_no_patch(self):
        raw = json.dumps({
            "intent": {"intent": "general_question", "target_section": None, "requires_patch": False},
            "assistant_message": "MLU는 Mean Length of Utterance입니다.",
            "patch_proposal": None,
        })
        result = _parse_agent_output(raw, stored_proposal=None)
        assert result["patch_proposal"] is None
        assert result["assistant_message"] == "MLU는 Mean Length of Utterance입니다."

    def test_invalid_intent_field_defaults_to_general_question(self):
        raw = json.dumps({
            "intent": "잘못된_형식",
            "assistant_message": "응답",
            "patch_proposal": None,
        })
        result = _parse_agent_output(raw, stored_proposal=None)
        assert result["intent"]["intent"] == "general_question"

    def test_plain_string_falls_back(self):
        result = _parse_agent_output("저는 AI 어시스턴트입니다.", stored_proposal=None)
        assert result["intent"]["intent"] == "general_question"
        assert "저는 AI 어시스턴트입니다." in result["assistant_message"]

    def test_markdown_json_block_is_parsed(self):
        payload = {
            "intent": {"intent": "show_evidence", "target_section": "O", "requires_patch": False},
            "assistant_message": "MLU 근거입니다.",
            "patch_proposal": None,
        }
        raw = f"```json\n{json.dumps(payload)}\n```"
        result = _parse_agent_output(raw, stored_proposal=None)
        assert result["intent"]["intent"] == "show_evidence"

    def test_stored_proposal_used_when_no_json_patch(self):
        stored = {
            "target_section": "S",
            "original_text": "원문",
            "proposed_text": "수정",
            "rationale": "이유",
            "evidence_refs": [],
        }
        raw = json.dumps({
            "intent": {"intent": "rewrite_section", "target_section": "S", "requires_patch": True},
            "assistant_message": "수정 제안입니다.",
            "patch_proposal": None,
        })
        result = _parse_agent_output(raw, stored_proposal=stored)
        assert result["patch_proposal"] == stored


# ── _build_initial_message ────────────────────────────────────────────────────

class TestBuildInitialMessage:
    def _segments(self):
        return [
            {"section": "S", "title": "주관적", "content": "아동이 불편함을 호소함"},
            {"section": "O", "title": "객관적", "content": "MLU 2.1"},
            {"section": "A", "title": "평가", "content": "언어 발달 지연 의심"},
            {"section": "P", "title": "계획", "content": "주 2회 치료"},
        ]

    def test_all_sections_in_message(self):
        msg = _build_initial_message("A 섹션 써줘", self._segments(), [])
        for section in ("S", "O", "A", "P"):
            assert section in msg

    def test_user_message_in_prompt(self):
        message = "치료 목표를 3개로 정리해줘"
        msg = _build_initial_message(message, self._segments(), [])
        assert message in msg
        assert "[치료사 요청]" in msg

    def test_no_history_block_when_empty(self):
        msg = _build_initial_message("질문", self._segments(), [])
        assert "[이전 대화]" not in msg

    def test_history_included_when_present(self):
        history = [
            {"role": "user", "content": "근거 보여줘"},
            {"role": "assistant", "content": "MLU 근거입니다."},
        ]
        msg = _build_initial_message("이어서 설명해줘", self._segments(), history)
        assert "[이전 대화]" in msg
        assert "근거 보여줘" in msg

    def test_history_limited_to_last_6(self):
        history = [{"role": "user", "content": f"메시지 {i}"} for i in range(20)]
        msg = _build_initial_message("질문", self._segments(), history)
        assert "메시지 0" not in msg
        assert "메시지 19" in msg

    def test_none_content_shows_placeholder(self):
        segments = [{"section": "A", "title": "평가", "content": None}]
        msg = _build_initial_message("질문", segments, [])
        assert "(내용 없음)" in msg


# ── validators ────────────────────────────────────────────────────────────────

class TestClinicalSafety:
    def test_safe_text_passes(self):
        is_safe, _ = check_clinical_safety("언어 발달 지연이 의심됩니다.")
        assert is_safe

    def test_diagnostic_assertion_fails(self):
        is_safe, msg = check_clinical_safety("검사 결과 언어장애가 있다.")
        assert not is_safe
        assert msg

    def test_confirmed_diagnosis_fails(self):
        is_safe, msg = check_clinical_safety("확진 결과 언어 발달 지연입니다.")
        assert not is_safe

    def test_empty_text_passes(self):
        is_safe, _ = check_clinical_safety("")
        assert is_safe


# ── diff ──────────────────────────────────────────────────────────────────────

class TestDiff:
    def test_identical_text_produces_no_ops(self):
        ops = produce_diff_ops("같은 문장", "같은 문장")
        assert ops == []

    def test_changed_text_produces_replace_op(self):
        ops = produce_diff_ops("원문 텍스트", "수정 텍스트")
        assert any(op["op"] == "replace" for op in ops)

    def test_render_diff_text_returns_string(self):
        result = render_diff_text("원문", "수정")
        assert isinstance(result, str)
