"""RDS read/write helpers for transcript draft, report, and job/session status.

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
        _be_engine = create_async_engine(
            settings.be_database_url,
            connect_args={"sslmode": "require"},
        )
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


async def get_transcript_segments(
    db: AsyncSession,
    transcript_id: str,
) -> list[dict]:
    """transcript_segments rows를 발화 순서대로 반환한다."""
    result = await db.execute(
        text("""
            SELECT speaker_role, text, start_ms, end_ms
            FROM transcript_segments
            WHERE transcript_id = CAST(:transcript_id AS uuid)
            ORDER BY segment_index
        """),
        {"transcript_id": transcript_id},
    )
    return [dict(row._mapping) for row in result]


async def get_session_context(
    db: AsyncSession,
    session_id: str,
) -> dict:
    """sessions + patients 조인으로 리포트 생성에 필요한 세션 컨텍스트를 반환한다.

    반환 키:
        session_date       : date 객체 (없으면 None)
        session_number     : 해당 환자의 누적 세션 순번 (1-based)
        patient_age_months : 세션일 기준 나이(개월 수, birth_date 없으면 0)
    """
    row = await db.execute(
        text("""
            SELECT
                s.session_date,
                p.birth_date,
                (
                    SELECT COUNT(*)
                    FROM sessions s2
                    WHERE s2.patient_ref_id = s.patient_ref_id
                      AND s2.created_at <= s.created_at
                ) AS session_number
            FROM sessions s
            JOIN patient_refs pr ON s.patient_ref_id = pr.id
            LEFT JOIN patients p ON p.patient_ref_id = pr.id
            WHERE s.id = CAST(:session_id AS uuid)
        """),
        {"session_id": session_id},
    )
    record = row.mappings().first()
    if record is None:
        return {"session_date": None, "session_number": 1, "patient_age_months": 0}

    session_date = record["session_date"]
    birth_date = record["birth_date"]
    session_number = int(record["session_number"] or 1)

    patient_age_months = 0
    if birth_date and session_date:
        months = (session_date.year - birth_date.year) * 12 + (session_date.month - birth_date.month)
        patient_age_months = max(0, months)

    return {
        "session_date": str(session_date) if session_date else None,
        "session_number": session_number,
        "patient_age_months": patient_age_months,
    }


async def save_report(
    db: AsyncSession,
    job_id: str,
    session_id: str,
    soap_note: dict,
    clinical_flags: list,
    evidence_chunk_ids: list,
    model_used: str,
) -> str:
    """reports + report_segments rows를 삽입하고 report_id를 반환한다."""
    report_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    await db.execute(
        text("""
            INSERT INTO reports
                (id, session_id, job_id, status, model_used, clinical_flags,
                 evidence_chunk_ids, requires_human_review, generated_at, updated_at)
            VALUES
                (CAST(:id AS uuid), CAST(:session_id AS uuid), CAST(:job_id AS uuid),
                 'DRAFT', :model_used, CAST(:clinical_flags AS jsonb),
                 CAST(:evidence_chunk_ids AS jsonb), true, :now, :now)
        """),
        {
            "id": report_id,
            "session_id": session_id,
            "job_id": job_id,
            "model_used": model_used,
            "clinical_flags": __import__("json").dumps(clinical_flags),
            "evidence_chunk_ids": __import__("json").dumps(evidence_chunk_ids),
            "now": now,
        },
    )

    soap_map = [
        ("SUBJECTIVE", soap_note.get("subjective", "")),
        ("OBJECTIVE",  soap_note.get("objective",  "")),
        ("ASSESSMENT", soap_note.get("assessment", "")),
        ("PLAN",       soap_note.get("plan",       "")),
    ]
    for idx, (seg_type, content) in enumerate(soap_map):
        await db.execute(
            text("""
                INSERT INTO report_segments
                    (id, report_id, segment_type, segment_index, ai_content, content, is_edited, created_at)
                VALUES
                    (CAST(:id AS uuid), CAST(:report_id AS uuid),
                     CAST(:segment_type AS report_segment_type),
                     :segment_index, :content, :content, false, :now)
            """),
            {
                "id": str(uuid.uuid4()),
                "report_id": report_id,
                "segment_type": seg_type,
                "segment_index": idx,
                "content": content,
                "now": now,
            },
        )

    await db.commit()
    return report_id


async def update_session_status(
    db: AsyncSession,
    session_id: str,
    status: str,
) -> None:
    """sessions.status를 갱신한다."""
    await db.execute(
        text("""
            UPDATE sessions
            SET status     = CAST(:status AS session_status),
                updated_at = :now
            WHERE id = CAST(:session_id AS uuid)
        """),
        {
            "status": status,
            "session_id": session_id,
            "now": datetime.now(UTC),
        },
    )
    await db.commit()


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