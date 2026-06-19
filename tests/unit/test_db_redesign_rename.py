"""DB 재디자인 용어 변경 검증 테스트.

CHILD/THERAPIST → PATIENT/SLP 리네임과
average_response_latency_sec → avg_response_latency_sec 필드명 변경이
스키마, 지표 계산, mock 데이터에 일관되게 반영됐는지 확인한다.
"""
import pytest


class TestSpeakerRoleConstants:
    def test_patient_constant_exists(self):
        from app.schemas.segment import SpeakerRole
        assert SpeakerRole.PATIENT == "PATIENT"

    def test_slp_constant_exists(self):
        from app.schemas.segment import SpeakerRole
        assert SpeakerRole.SLP == "SLP"

    def test_guardian_constant_exists(self):
        from app.schemas.segment import SpeakerRole
        assert SpeakerRole.GUARDIAN == "GUARDIAN"

    def test_unknown_constant_exists(self):
        from app.schemas.segment import SpeakerRole
        assert SpeakerRole.UNKNOWN == "UNKNOWN"

    def test_old_child_constant_removed(self):
        from app.schemas.segment import SpeakerRole
        assert not hasattr(SpeakerRole, "CHILD")

    def test_old_therapist_constant_removed(self):
        from app.schemas.segment import SpeakerRole
        assert not hasattr(SpeakerRole, "THERAPIST")

    def test_old_caregiver_constant_removed(self):
        from app.schemas.segment import SpeakerRole
        assert not hasattr(SpeakerRole, "CAREGIVER")


class TestLanguageMetricsSchema:
    def test_avg_response_latency_field_exists(self):
        from app.schemas.metrics import LanguageMetrics
        m = LanguageMetrics(
            session_id="s1", target_speaker="PATIENT",
            total_utterances=5, ntw=10, ndw=8, ttr=0.8, mlu_morpheme=2.5,
            avg_response_latency_sec=1.5,
        )
        assert m.avg_response_latency_sec == 1.5

    def test_avg_response_latency_defaults_to_none(self):
        from app.schemas.metrics import LanguageMetrics
        m = LanguageMetrics(
            session_id="s1", target_speaker="PATIENT",
            total_utterances=5, ntw=10, ndw=8, ttr=0.8, mlu_morpheme=2.5,
        )
        assert m.avg_response_latency_sec is None

    def test_old_field_name_ignored(self):
        from app.schemas.metrics import LanguageMetrics
        # 구 필드명은 Pydantic에 의해 무시되고 avg_response_latency_sec는 None이 된다
        m = LanguageMetrics(
            session_id="s1", target_speaker="PATIENT",
            total_utterances=5, ntw=10, ndw=8, ttr=0.8, mlu_morpheme=2.5,
            average_response_latency_sec=1.5,  # 구 필드명 — 무시됨
        )
        assert m.avg_response_latency_sec is None


class TestResponseLatencyCalculation:
    def _make_utterance(self, speaker_role, start_time, end_time):
        from app.schemas.transcript import Utterance
        return Utterance(
            utterance_id=f"u_{speaker_role}_{start_time}",
            speaker_id=speaker_role,
            speaker_role=speaker_role,
            start_time=start_time,
            end_time=end_time,
            duration_sec=end_time - start_time,
            text="테스트",
            asr_confidence=0.9,
        )

    def test_calculates_slp_to_patient_latency(self):
        from app.metrics.response_latency import calculate_average_response_latency
        utterances = [
            self._make_utterance("SLP", 0.0, 2.0),
            self._make_utterance("PATIENT", 4.0, 6.0),  # gap = 2.0s
            self._make_utterance("SLP", 7.0, 9.0),
            self._make_utterance("PATIENT", 11.0, 13.0),  # gap = 2.0s
        ]
        result = calculate_average_response_latency(utterances)
        assert result == pytest.approx(2.0)

    def test_ignores_patient_to_slp_direction(self):
        from app.metrics.response_latency import calculate_average_response_latency
        utterances = [
            self._make_utterance("PATIENT", 0.0, 2.0),
            self._make_utterance("SLP", 4.0, 6.0),  # PATIENT→SLP는 계산 제외
        ]
        result = calculate_average_response_latency(utterances)
        assert result is None

    def test_old_therapist_role_not_counted(self):
        from app.metrics.response_latency import calculate_average_response_latency
        utterances = [
            self._make_utterance("THERAPIST", 0.0, 2.0),
            self._make_utterance("CHILD", 4.0, 6.0),
        ]
        result = calculate_average_response_latency(utterances)
        assert result is None


class TestMockData:
    def test_mock_utterances_use_new_roles(self):
        from app.mocks.mock_utterances import MOCK_UTTERANCES
        roles = {u["speaker_role"] for u in MOCK_UTTERANCES}
        assert "PATIENT" in roles
        assert "SLP" in roles
        assert "CHILD" not in roles
        assert "THERAPIST" not in roles

    def test_mock_patient_utterances_exported(self):
        from app.mocks.mock_utterances import MOCK_PATIENT_UTTERANCES
        assert all(u["speaker_role"] == "PATIENT" for u in MOCK_PATIENT_UTTERANCES)
        assert len(MOCK_PATIENT_UTTERANCES) > 0

    def test_mock_metrics_uses_patient(self):
        from app.mocks.mock_metrics import MOCK_METRICS
        assert MOCK_METRICS["target_speaker"] == "PATIENT"
        assert "avg_response_latency_sec" in MOCK_METRICS
        assert "average_response_latency_sec" not in MOCK_METRICS

    def test_mock_session_uses_slp_id(self):
        from app.mocks.mock_session import MOCK_SESSION
        assert "slp_id" in MOCK_SESSION
        assert "therapist_id" not in MOCK_SESSION
