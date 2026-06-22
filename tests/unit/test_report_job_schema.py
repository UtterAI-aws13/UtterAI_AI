"""ReportJobMessage 스키마 계약 검증 — final_s3_key 필드 추가."""


class TestReportJobMessage:
    def _make(self, **kwargs):
        from app.schemas.job import ReportJobMessage
        defaults = dict(job_id="j1", session_id="s1", transcript_id="t1")
        defaults.update(kwargs)
        return ReportJobMessage(**defaults)

    def test_final_s3_key_defaults_to_none(self):
        msg = self._make()
        assert msg.final_s3_key is None

    def test_final_s3_key_accepted(self):
        key = "finals/session-1/transcript-1.json"
        msg = self._make(final_s3_key=key)
        assert msg.final_s3_key == key

    def test_round_trip_with_final_s3_key(self):
        from app.schemas.job import ReportJobMessage
        key = "finals/s/t.json"
        msg = self._make(final_s3_key=key, template_id="tmpl-1")
        restored = ReportJobMessage.model_validate_json(msg.model_dump_json())
        assert restored.final_s3_key == key
        assert restored.template_id == "tmpl-1"

    def test_round_trip_without_final_s3_key(self):
        from app.schemas.job import ReportJobMessage
        msg = self._make()
        restored = ReportJobMessage.model_validate_json(msg.model_dump_json())
        assert restored.final_s3_key is None

    def test_sqs_payload_omits_none_fields_when_excluded(self):
        """final_s3_key=None 일 때 직렬화해도 역직렬화에 문제없다."""
        from app.schemas.job import ReportJobMessage
        msg = self._make()
        data = msg.model_dump(exclude_none=True)
        assert "final_s3_key" not in data
        restored = ReportJobMessage(**data)
        assert restored.final_s3_key is None