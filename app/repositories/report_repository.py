# SAVE_DRAFT가 report_drafts를 저장할 때 쓰는 인터페이스와 구현.
# deterministic/QA validation을 모두 통과한 결과만 이 인터페이스를 거쳐
# DRAFT 상태로 저장된다 (호출 시점 검증은 Phase 4 Graph의 책임).
# 참고: 01_production_5_agent_agentic_rag_design.md §18.2
import json
import uuid
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.rds import get_be_engine


class ReportRepository(Protocol):
    async def save_draft(
        self,
        *,
        generation_run_id: str,
        session_id: str,
        patient_ref_id: str,
        therapist_id: str,
        soap: dict[str, Any],
        reasoning_summary: dict[str, Any],
        claims: list[dict[str, Any]],
        evidence_trace: dict[str, Any],
        validation: dict[str, Any],
        quality_scores: dict[str, Any],
    ) -> str:
        """report_drafts row를 status='DRAFT'로 저장하고 report_draft_id를 반환한다."""
        ...


class SqlReportRepository:
    """report_drafts(BE RDS)에 대한 저장 구현."""

    async def save_draft(
        self,
        *,
        generation_run_id: str,
        session_id: str,
        patient_ref_id: str,
        therapist_id: str,
        soap: dict[str, Any],
        reasoning_summary: dict[str, Any],
        claims: list[dict[str, Any]],
        evidence_trace: dict[str, Any],
        validation: dict[str, Any],
        quality_scores: dict[str, Any],
    ) -> str:
        report_draft_id = str(uuid.uuid4())
        async with AsyncSession(get_be_engine()) as db:
            await db.execute(
                text("""
                    INSERT INTO report_drafts
                        (id, generation_run_id, session_id, patient_ref_id, therapist_id,
                         status, soap_json, reasoning_summary_json, claims_json,
                         evidence_trace_json, validation_json, quality_scores_json,
                         created_at, updated_at)
                    VALUES
                        (CAST(:id AS uuid), CAST(:generation_run_id AS uuid),
                         CAST(:session_id AS uuid), CAST(:patient_ref_id AS uuid),
                         CAST(:therapist_id AS uuid), 'DRAFT', CAST(:soap_json AS jsonb),
                         CAST(:reasoning_summary_json AS jsonb), CAST(:claims_json AS jsonb),
                         CAST(:evidence_trace_json AS jsonb), CAST(:validation_json AS jsonb),
                         CAST(:quality_scores_json AS jsonb), now(), now())
                """),
                {
                    "id": report_draft_id,
                    "generation_run_id": generation_run_id,
                    "session_id": session_id,
                    "patient_ref_id": patient_ref_id,
                    "therapist_id": therapist_id,
                    "soap_json": json.dumps(soap),
                    "reasoning_summary_json": json.dumps(reasoning_summary),
                    "claims_json": json.dumps(claims),
                    "evidence_trace_json": json.dumps(evidence_trace),
                    "validation_json": json.dumps(validation),
                    "quality_scores_json": json.dumps(quality_scores),
                },
            )
            await db.commit()
        return report_draft_id
