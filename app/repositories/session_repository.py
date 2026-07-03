# LOAD_CONTEXT가 확정 세션 데이터를 조회할 때 쓰는 인터페이스와 구현.
# 참고: 01_production_5_agent_agentic_rag_design.md §7
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.report_generation.errors import MissingConfirmedTranscriptError
from app.agents.report_generation.models.common import CurrentSession, CurrentSessionMetrics
from app.pipelines.report_pipeline import _compute_metrics_from_segments
from app.services.authorization_service import AuthorizationService
from app.storage.rds import get_be_engine, get_transcript_segments

# report_generation_runs에서 "진행 중"으로 간주해 중복 실행을 막는 상태.
# 완료/실패한 run은 재시도를 막지 않는다.
_IN_FLIGHT_RUN_STATUSES = ("QUEUED", "RUNNING", "RESEARCHING", "WRITING", "VALIDATING")


class SessionRepository(Protocol):
    async def get_current_session(
        self, session_id: str, therapist_id: str, selected_analysis: list[str]
    ) -> CurrentSession:
        """확정 transcript, 선택 분석표, 현재 세션 지표를 조회한다.

        therapist_id가 session_id에 접근 권한이 없으면 예외를 발생시킨다
        (권한 검증은 prompt가 아니라 이 계층에서 강제한다).
        """
        ...

    async def has_existing_report_generation_run(self, session_id: str) -> bool:
        """동일 세션에 대한 리포트 생성 중복 실행 여부를 확인한다."""
        ...


class SqlSessionRepository:
    """BE RDS(cross-repo)에서 세션 컨텍스트를 조회하는 SessionRepository 구현.

    app.storage.rds의 기존 헬퍼(get_transcript_segments)와
    app.pipelines.report_pipeline._compute_metrics_from_segments를 그대로 재사용해
    지표 계산 로직을 이중으로 유지하지 않는다.
    """

    def __init__(self, authorization_service: AuthorizationService | None = None):
        self._authz = authorization_service or AuthorizationService()

    async def get_current_session(
        self, session_id: str, therapist_id: str, selected_analysis: list[str]
    ) -> CurrentSession:
        async with AsyncSession(get_be_engine()) as db:
            await self._authz.ensure_session_access(db, session_id, therapist_id)

            transcript_row = await db.execute(
                text("""
                    SELECT id FROM transcripts
                    WHERE session_id = CAST(:session_id AS uuid) AND status = 'FINALIZED'
                    ORDER BY finalized_at DESC
                    LIMIT 1
                """),
                {"session_id": session_id},
            )
            transcript = transcript_row.first()
            if transcript is None:
                raise MissingConfirmedTranscriptError(
                    f"session {session_id} has no finalized transcript"
                )

            segments = await get_transcript_segments(db, str(transcript[0]))
            transcript_text = "\n".join(
                f"{s['speaker_role']}: {s['text']}" for s in segments if s.get("text")
            )
            computed = _compute_metrics_from_segments(segments)

            return CurrentSession(
                session_id=session_id,
                selected_analysis=selected_analysis,
                transcript=transcript_text,
                metrics=CurrentSessionMetrics(
                    MLU=computed["mlu_word"],
                    TTR=computed["ttr"],
                    NDW=computed["ndw"],
                    NTW=computed["ntw"],
                    response_latency_avg_ms=round(computed["avg_response_latency_sec"] * 1000),
                ),
                # sessions.memo/session_goal 중 어느 필드가 "조건" 태그에 해당하는지
                # 확정된 스키마가 없어 비워둔다. 필요해지면 별도 확인 후 채운다.
                session_conditions=[],
            )

    async def has_existing_report_generation_run(self, session_id: str) -> bool:
        async with AsyncSession(get_be_engine()) as db:
            row = await db.execute(
                text("""
                    SELECT 1 FROM report_generation_runs
                    WHERE session_id = CAST(:session_id AS uuid)
                      AND status = ANY(:in_flight_statuses)
                    LIMIT 1
                """),
                {"session_id": session_id, "in_flight_statuses": list(_IN_FLIGHT_RUN_STATUSES)},
            )
            return row.first() is not None
