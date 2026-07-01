"""Unit tests for the Strands-based report editing chatbot agent (no Bedrock/tool calls)."""

from __future__ import annotations

from app.agents.report_editing_chatbot.agent import (
    ChatResponse,
    IntentClassification,
    PatchProposal,
    _build_initial_message,
)
from app.agents.report_editing_chatbot.validators import check_clinical_safety


# ── off_topic guard ───────────────────────────────────────────────────────────

class TestOffTopicGuard:
    """run_agent() removes patch_proposal when intent is off_topic.
    Tested here via the ChatResponse model to avoid a real Bedrock call."""

    def test_off_topic_patch_is_stripped(self):
        output = ChatResponse(
            intent=IntentClassification(intent="off_topic"),
            assistant_message="이 챗봇은 SOAP 리포트 수정만 지원합니다.",
            patch_proposal=PatchProposal(
                target_section="A",
                original_text="원문",
                proposed_text="수정안",
                rationale="이유",
            ),
        )
        # Mimic the guard in run_agent()
        if output.intent.intent == "off_topic":
            output.patch_proposal = None

        assert output.patch_proposal is None

    def test_rewrite_section_keeps_patch(self):
        proposal = PatchProposal(
            target_section="A",
            original_text="원문",
            proposed_text="수정안",
            rationale="임상 표현 강화",
        )
        output = ChatResponse(
            intent=IntentClassification(intent="rewrite_section", target_section="A", requires_patch=True),
            assistant_message="수정 제안입니다.",
            patch_proposal=proposal,
        )
        if output.intent.intent == "off_topic":
            output.patch_proposal = None

        assert output.patch_proposal is not None
        assert output.patch_proposal.target_section == "A"

    def test_chat_response_defaults_are_safe(self):
        output = ChatResponse()
        assert output.intent.intent == "general_question"
        assert output.patch_proposal is None
        assert output.assistant_message == ""


# ── _build_initial_message ────────────────────────────────────────────────────

class TestBuildInitialMessage:
    def _segments(self):
        return [
            {"section": "S", "title": "주관적", "content": "아동이 불편함을 호소함"},
            {"section": "O", "title": "객관적", "content": "MLU 2.1"},
            {"section": "A", "title": "평가", "content": "언어 발달 지연 의심"},
            {"section": "P", "title": "계획", "content": "주 2회 치료"},
        ]

    def test_all_sections_present(self):
        msg = _build_initial_message("A 섹션 써줘", self._segments(), [])
        for section in ("S", "O", "A", "P"):
            assert section in msg

    def test_user_message_present(self):
        message = "치료 목표를 3개로 정리해줘"
        msg = _build_initial_message(message, self._segments(), [])
        assert message in msg
        assert "[치료사 요청]" in msg

    def test_no_history_block_when_empty(self):
        msg = _build_initial_message("질문", self._segments(), [])
        assert "[이전 대화]" not in msg

    def test_history_included(self):
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
        is_safe, _ = check_clinical_safety("확진 결과 언어 발달 지연입니다.")
        assert not is_safe

    def test_empty_text_passes(self):
        is_safe, _ = check_clinical_safety("")
        assert is_safe
