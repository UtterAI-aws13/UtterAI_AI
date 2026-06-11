"""Unit tests for storage/rds.py helper functions.

AsyncSession은 MagicMock으로 대체하며 실제 DB에 연결하지 않는다.
SQL 텍스트와 파라미터 바인딩이 올바른지, 그리고 terminal status일 때
completed_at이 설정되는지 검증한다.
"""
import uuid
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


def _make_utterance(idx: int, speaker_role: str = "UNKNOWN"):
    from app.schemas.transcript import Utterance
    return Utterance(
        utterance_id=f"u{idx}",
        speaker_id=f"SPEAKER_0{idx % 2}",
        speaker_role=speaker_role,
        start_time=float(idx),
        end_time=float(idx + 1),
        duration_sec=1.0,
        text=f"발화 {idx}",
        asr_confidence=0.9,
    )


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


class TestSaveTranscriptDraft:
    @pytest.mark.asyncio
    async def test_inserts_transcript_and_segments(self, mock_db):
        from app.storage.rds import save_transcript_draft
        utterances = [_make_utterance(i) for i in range(3)]

        transcript_id = await save_transcript_draft(
            mock_db,
            job_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            audio_file_id=str(uuid.uuid4()),
            draft_s3_key="transcript-drafts/s/j/draft.json",
            utterances=utterances,
        )

        assert isinstance(transcript_id, str)
        uuid.UUID(transcript_id)  # 유효한 UUID 형식인지 확인
        # INSERT 횟수: 1 (transcripts) + 3 (segments)
        assert mock_db.execute.await_count == 4
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_segment_indices_are_sequential(self, mock_db):
        from app.storage.rds import save_transcript_draft
        utterances = [_make_utterance(i) for i in range(2)]

        await save_transcript_draft(
            mock_db,
            job_id="j", session_id="s", audio_file_id="af",
            draft_s3_key="k", utterances=utterances,
        )

        # 두 번째, 세 번째 execute 호출이 segment insert (idx=0, idx=1)
        segment_calls = mock_db.execute.await_args_list[1:]
        indices = [c.args[1]["segment_index"] for c in segment_calls]
        assert indices == [0, 1]

    @pytest.mark.asyncio
    async def test_time_converted_to_ms(self, mock_db):
        from app.storage.rds import save_transcript_draft
        utterances = [_make_utterance(0)]
        utterances[0] = utterances[0].model_copy(
            update={"start_time": 1.5, "end_time": 3.25}
        )

        await save_transcript_draft(
            mock_db, job_id="j", session_id="s", audio_file_id="af",
            draft_s3_key="k", utterances=utterances,
        )

        segment_params = mock_db.execute.await_args_list[1].args[1]
        assert segment_params["start_ms"] == 1500
        assert segment_params["end_ms"] == 3250

    @pytest.mark.asyncio
    async def test_empty_utterances_inserts_only_transcript_row(self, mock_db):
        from app.storage.rds import save_transcript_draft

        await save_transcript_draft(
            mock_db, job_id="j", session_id="s", audio_file_id="af",
            draft_s3_key="k", utterances=[],
        )

        assert mock_db.execute.await_count == 1


class TestUpdateAnalysisJobStatus:
    @pytest.mark.asyncio
    async def test_sets_completed_at_for_completed_status(self, mock_db):
        from app.storage.rds import update_analysis_job_status

        await update_analysis_job_status(mock_db, "job-1", "COMPLETED", pipeline_stage="COMPLETED")

        params = mock_db.execute.await_args.args[1]
        assert params["status"] == "COMPLETED"
        assert params["completed_at"] is not None
        assert isinstance(params["completed_at"], datetime)
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sets_completed_at_for_failed_status(self, mock_db):
        from app.storage.rds import update_analysis_job_status

        await update_analysis_job_status(
            mock_db, "job-1", "FAILED",
            error_code="ML_GPU_STAGE_FAILED",
            error_message="OOM",
        )

        params = mock_db.execute.await_args.args[1]
        assert params["completed_at"] is not None
        assert params["error_code"] == "ML_GPU_STAGE_FAILED"
        assert params["error_message"] == "OOM"

    @pytest.mark.asyncio
    async def test_no_completed_at_for_in_progress_status(self, mock_db):
        from app.storage.rds import update_analysis_job_status

        await update_analysis_job_status(mock_db, "job-1", "RUNNING_ASR", pipeline_stage="RUNNING_ASR")

        params = mock_db.execute.await_args.args[1]
        assert params["completed_at"] is None

    @pytest.mark.asyncio
    async def test_passes_job_id_and_pipeline_stage(self, mock_db):
        from app.storage.rds import update_analysis_job_status

        await update_analysis_job_status(mock_db, "job-abc", "ALIGNING", pipeline_stage="ML_GPU")

        params = mock_db.execute.await_args.args[1]
        assert params["job_id"] == "job-abc"
        assert params["pipeline_stage"] == "ML_GPU"
