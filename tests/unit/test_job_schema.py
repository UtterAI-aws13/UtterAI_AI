"""JobMessage 스키마 계약 검증 테스트.

이 세션에서 추가된 필드들이 모든 메시지 타입에 일관되게 존재하는지 확인한다.
- JobStatus.CANCELLED
- JobOptions.template_id
- audio_file_id in JobMessage / MLGpuMessage / LLMMessage
"""
from datetime import datetime


class TestJobStatus:
    def test_cancelled_status_exists(self):
        from app.schemas.job import JobStatus
        assert JobStatus.CANCELLED == "CANCELLED"

    def test_all_expected_statuses_present(self):
        from app.schemas.job import JobStatus
        expected = {
            "PENDING", "DOWNLOADING", "PREPROCESSING",
            "RUNNING_VAD", "RUNNING_DIARIZATION", "RUNNING_ASR", "ALIGNING",
            "CALCULATING_METRICS", "RUNNING_RAG", "GENERATING_REPORT", "SAVING_RESULT",
            "COMPLETED", "FAILED", "RETRYING", "CANCELLED",
        }
        actual = {s.value for s in JobStatus}
        assert expected == actual


class TestJobOptions:
    def test_template_id_defaults_to_none(self):
        from app.schemas.job import JobOptions
        opts = JobOptions()
        assert opts.template_id is None

    def test_template_id_accepted_as_string(self):
        from app.schemas.job import JobOptions
        opts = JobOptions(template_id="tmpl-abc")
        assert opts.template_id == "tmpl-abc"

    def test_default_language_is_korean(self):
        from app.schemas.job import JobOptions
        assert JobOptions().language == "ko"

    def test_diarization_enabled_by_default(self):
        from app.schemas.job import JobOptions
        assert JobOptions().enable_diarization is True


class TestJobMessage:
    def _make_message(self, **kwargs):
        from app.schemas.job import JobMessage, AudioInput, JobOptions
        defaults = dict(
            job_id="j1",
            session_id="s1",
            audio_file_id="af1",
            user_id="u1",
            audio=AudioInput(bucket="b", key="k"),
            options=JobOptions(),
            requested_at=datetime.now(),
        )
        defaults.update(kwargs)
        return JobMessage(**defaults)

    def test_audio_file_id_field_exists(self):
        msg = self._make_message(audio_file_id="af-xyz")
        assert msg.audio_file_id == "af-xyz"

    def test_options_template_id_preserved(self):
        from app.schemas.job import JobOptions
        msg = self._make_message(options=JobOptions(template_id="t-123"))
        assert msg.options.template_id == "t-123"

    def test_serialises_and_deserialises(self):
        from app.schemas.job import JobMessage
        msg = self._make_message()
        restored = JobMessage.model_validate_json(msg.model_dump_json())
        assert restored.audio_file_id == msg.audio_file_id


class TestMLGpuMessage:
    def test_audio_file_id_field_exists(self):
        from app.schemas.job import MLGpuMessage, JobOptions
        msg = MLGpuMessage(
            job_id="j1",
            session_id="s1",
            audio_file_id="af1",
            wav_s3_key="intermediate/s1/j1/processed.wav",
            vad_s3_key="intermediate/s1/j1/vad.json",
            options=JobOptions(),
        )
        assert msg.audio_file_id == "af1"

    def test_template_id_survives_round_trip(self):
        from app.schemas.job import MLGpuMessage, JobOptions
        msg = MLGpuMessage(
            job_id="j1", session_id="s1", audio_file_id="af1",
            wav_s3_key="w", vad_s3_key="v",
            options=JobOptions(template_id="tmpl-99"),
        )
        restored = MLGpuMessage.model_validate_json(msg.model_dump_json())
        assert restored.options.template_id == "tmpl-99"


class TestLLMMessage:
    def test_audio_file_id_field_exists(self):
        from app.schemas.job import LLMMessage, JobOptions
        msg = LLMMessage(
            job_id="j1",
            session_id="s1",
            audio_file_id="af1",
            vad_s3_key="v",
            speaker_s3_key="sp",
            asr_s3_key="asr",
            options=JobOptions(),
        )
        assert msg.audio_file_id == "af1"
