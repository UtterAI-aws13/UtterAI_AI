"""RDS write helpers for transcript draft and analysis job status.

BE RDS에 직접 쓰는 헬퍼. AI pgvector DB(db.py)와 별개의 엔진을 사용한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.schemas.transcript import Utterance

_be_engine = None


def get_be_engine():
    global _be_engine
    if _be_engine is None:
        from app.config import settings
        _be_engine = create_async_engine(settings.be_database_url)
    return _be_engine

_TERMINAL_STATUSES = {"COMPLETED", "FAILED"}


async def save_transcript_draft(
    db: AsyncSession,
    job_id: str,
    session_id: str,
    audio_file_id: str,
    draft_s3_key: str,
    utterances: list[Utterance],
) -> str:
    """transcripts row와 transcript_segments rows를 삽입하고 transcript_id를 반환한다."""
    transcript_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    await db.execute(
        text("""
            INSERT INTO transcripts
                (id, session_id, audio_file_id, job_id, status, raw_draft_s3_key, created_at, updated_at)
            VALUES
                (CAST(:id AS uuid), CAST(:session_id AS uuid), CAST(:audio_file_id AS uuid),
                 CAST(:job_id AS uuid), 'DRAFT', :raw_draft_s3_key, :now, :now)
        """),
        {
            "id": transcript_id,
            "session_id": session_id,
            "audio_file_id": audio_file_id,
            "job_id": job_id,
            "raw_draft_s3_key": draft_s3_key,
            "now": now,
        },
    )

    for idx, utt in enumerate(utterances):
        await db.execute(
            text("""
                INSERT INTO transcript_segments
                    (id, transcript_id, session_id, segment_index, speaker_label, speaker_role,
                     start_ms, end_ms, original_text, text, confidence, is_edited, created_at)
                VALUES
                    (CAST(:id AS uuid), CAST(:transcript_id AS uuid), CAST(:session_id AS uuid),
                     :segment_index, :speaker_label, CAST(:speaker_role AS speaker_role),
                     :start_ms, :end_ms, :original_text, :text, :confidence, false, :now)
            """),
            {
                "id": str(uuid.uuid4()),
                "transcript_id": transcript_id,
                "session_id": session_id,
                "segment_index": idx,
                "speaker_label": utt.speaker_id,
                "speaker_role": utt.speaker_role,
                "start_ms": int(utt.start_time * 1000),
                "end_ms": int(utt.end_time * 1000),
                "original_text": utt.text,
                "text": utt.text,
                "confidence": utt.asr_confidence,
                "now": now,
            },
        )

    await db.commit()
    return transcript_id


async def update_analysis_job_status(
    db: AsyncSession,
    job_id: str,
    status: str,
    pipeline_stage: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """analysis_jobs.status와 관련 필드를 갱신한다."""
    completed_at = datetime.now(UTC) if status in _TERMINAL_STATUSES else None

    await db.execute(
        text("""
            UPDATE analysis_jobs
            SET status          = CAST(:status AS analysis_job_status),
                pipeline_stage  = :pipeline_stage,
                error_code      = :error_code,
                error_message   = :error_message,
                completed_at    = :completed_at
            WHERE id = CAST(:job_id AS uuid)
        """),
        {
            "status": status,
            "pipeline_stage": pipeline_stage,
            "error_code": error_code,
            "error_message": error_message,
            "completed_at": completed_at,
            "job_id": job_id,
        },
    )
    await db.commit()