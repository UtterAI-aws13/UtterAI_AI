# report_generation_runs 상태를 기록/조회할 때 쓰는 인터페이스와 구현.
# 참고: 01_production_5_agent_agentic_rag_design.md §18.1, §19.2
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.report_generation.errors import UnauthorizedError
from app.agents.report_generation.models.common import FailureCode, RunStatus
from app.storage.rds import get_be_engine

# 완료/실패한 run은 재시도를 막지 않는다 (SessionRepository와 동일한 기준).
_IN_FLIGHT_RUN_STATUSES = ("QUEUED", "RUNNING", "RESEARCHING", "WRITING", "VALIDATING")


class ReportGenerationRunRepository(Protocol):
    async def create_run(
        self,
        *,
        run_id: str,
        session_id: str,
        patient_ref_id: str,
        therapist_id: str,
        graph_version: str,
        model_config: dict[str, Any],
    ) -> None:
        """status=QUEUED로 run row를 생성한다. idempotency key는 run_id다."""
        ...

    async def update_progress(
        self,
        *,
        run_id: str,
        status: RunStatus,
        current_node: str,
        retry_budget: dict[str, Any],
    ) -> None:
        """Graph 노드 진입/이탈마다 현재 진행 상태를 갱신한다."""
        ...

    async def mark_succeeded(
        self, *, run_id: str, quality_scores: dict[str, Any]
    ) -> None:
        ...

    async def mark_failed(
        self, *, run_id: str, failure_code: FailureCode, failure_detail: str
    ) -> None:
        ...

    async def get_run(self, run_id: str, therapist_id: str) -> dict[str, Any]:
        """상태 조회 API가 사용한다. therapist_id 권한 검증을 포함한다."""
        ...


class SqlReportGenerationRunRepository:
    """report_generation_runs(BE RDS)에 대한 CRUD 구현."""

    async def create_run(
        self,
        *,
        run_id: str,
        session_id: str,
        patient_ref_id: str,
        therapist_id: str,
        graph_version: str,
        model_config: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC)
        async with AsyncSession(get_be_engine()) as db:
            await db.execute(
                text("""
                    INSERT INTO report_generation_runs
                        (id, session_id, patient_ref_id, therapist_id, status,
                         graph_version, model_config_json, retry_budget_json, created_at)
                    VALUES
                        (CAST(:run_id AS uuid), CAST(:session_id AS uuid),
                         CAST(:patient_ref_id AS uuid), CAST(:therapist_id AS uuid),
                         :status, :graph_version, CAST(:model_config_json AS jsonb),
                         CAST(:retry_budget_json AS jsonb), :now)
                """),
                {
                    "run_id": run_id,
                    "session_id": session_id,
                    "patient_ref_id": patient_ref_id,
                    "therapist_id": therapist_id,
                    "status": RunStatus.QUEUED.value,
                    "graph_version": graph_version,
                    "model_config_json": json.dumps(model_config),
                    "retry_budget_json": json.dumps({}),
                    "now": now,
                },
            )
            await db.commit()

    async def update_progress(
        self,
        *,
        run_id: str,
        status: RunStatus,
        current_node: str,
        retry_budget: dict[str, Any],
    ) -> None:
        async with AsyncSession(get_be_engine()) as db:
            await db.execute(
                text("""
                    UPDATE report_generation_runs
                    SET status = :status, current_node = :current_node,
                        retry_budget_json = CAST(:retry_budget_json AS jsonb),
                        started_at = COALESCE(started_at, now())
                    WHERE id = CAST(:run_id AS uuid)
                """),
                {
                    "run_id": run_id,
                    "status": status.value,
                    "current_node": current_node,
                    "retry_budget_json": json.dumps(retry_budget),
                },
            )
            await db.commit()

    async def mark_succeeded(self, *, run_id: str, quality_scores: dict[str, Any]) -> None:
        async with AsyncSession(get_be_engine()) as db:
            await db.execute(
                text("""
                    UPDATE report_generation_runs
                    SET status = :status, quality_scores_json = CAST(:quality_scores_json AS jsonb),
                        completed_at = now()
                    WHERE id = CAST(:run_id AS uuid)
                """),
                {
                    "run_id": run_id,
                    "status": RunStatus.SUCCEEDED.value,
                    "quality_scores_json": json.dumps(quality_scores),
                },
            )
            await db.commit()

    async def mark_failed(
        self, *, run_id: str, failure_code: FailureCode, failure_detail: str
    ) -> None:
        async with AsyncSession(get_be_engine()) as db:
            await db.execute(
                text("""
                    UPDATE report_generation_runs
                    SET status = :status, failure_code = :failure_code,
                        failure_detail = :failure_detail, completed_at = now()
                    WHERE id = CAST(:run_id AS uuid)
                """),
                {
                    "run_id": run_id,
                    "status": RunStatus.FAILED.value,
                    "failure_code": failure_code.value,
                    "failure_detail": failure_detail,
                },
            )
            await db.commit()

    async def get_run(self, run_id: str, therapist_id: str) -> dict[str, Any]:
        async with AsyncSession(get_be_engine()) as db:
            row = await db.execute(
                text("""
                    SELECT r.id, r.therapist_id, r.status, r.current_node, r.retry_budget_json,
                           r.quality_scores_json, r.failure_code, r.failure_detail, d.id AS report_draft_id
                    FROM report_generation_runs r
                    LEFT JOIN report_drafts d ON d.generation_run_id = r.id
                    WHERE r.id = CAST(:run_id AS uuid)
                """),
                {"run_id": run_id},
            )
            record = row.mappings().first()
            if record is None or str(record["therapist_id"]) != therapist_id:
                raise UnauthorizedError(f"run {run_id} not found or not owned by {therapist_id}")
            return dict(record)


async def record_event(
    *,
    run_id: str,
    node_name: str,
    event_type: str,
    decision: str | None = None,
    retry_count: int | None = None,
    duration_ms: int | None = None,
    token_usage: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """report_generation_events에 노드 진행 이벤트를 기록한다.

    민감 원문(transcript/SOAP 등)을 metadata에 담지 않는다 (§22.3).
    """
    async with AsyncSession(get_be_engine()) as db:
        await db.execute(
            text("""
                INSERT INTO report_generation_events
                    (id, run_id, node_name, event_type, decision, retry_count,
                     duration_ms, token_usage_json, metadata_json, created_at)
                VALUES
                    (CAST(:id AS uuid), CAST(:run_id AS uuid), :node_name, :event_type,
                     :decision, :retry_count, :duration_ms, CAST(:token_usage_json AS jsonb),
                     CAST(:metadata_json AS jsonb), now())
            """),
            {
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "node_name": node_name,
                "event_type": event_type,
                "decision": decision,
                "retry_count": retry_count,
                "duration_ms": duration_ms,
                "token_usage_json": json.dumps(token_usage) if token_usage is not None else None,
                "metadata_json": json.dumps(metadata) if metadata is not None else None,
            },
        )
        await db.commit()
