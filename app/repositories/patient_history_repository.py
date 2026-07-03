# LOAD_CONTEXT가 환자 longitudinal context를 조회할 때 쓰는 인터페이스와 구현.
# 정량 지표는 RDS deterministic query로만 조회한다. AgentCore Memory를
# source of truth로 쓰지 않는다.
# 참고: 01_production_5_agent_agentic_rag_design.md §7.2
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.report_generation.models.common import PatientHistory
from app.services.authorization_service import AuthorizationService
from app.storage.rds import get_be_engine


class PatientHistoryRepository(Protocol):
    async def get_patient_history(
        self, patient_ref_id: str, therapist_id: str, recent_session_count: int
    ) -> PatientHistory:
        """최근 N회기 요약과 지표 추이를 조회한다.

        therapist_id가 patient_ref_id에 접근 권한이 없으면 예외를 발생시킨다.
        """
        ...


class SqlPatientHistoryRepository:
    """patient_metric_trends / soap_case_indexes / sessions에서 환자 히스토리를 조회한다.

    주의: patient_metric_trends는 이 구현 시점 기준 실제 writer가 없어 빈 결과를
    반환할 수 있다 (수치가 쌓이면 자동으로 채워진다 — 코드 변경 불필요).
    soap_case_indexes는 리포트 확정 시 채워지므로 실사용 가능하다.
    """

    def __init__(self, authorization_service: AuthorizationService | None = None):
        self._authz = authorization_service or AuthorizationService()

    async def get_patient_history(
        self, patient_ref_id: str, therapist_id: str, recent_session_count: int
    ) -> PatientHistory:
        async with AsyncSession(get_be_engine()) as db:
            await self._authz.ensure_patient_ref_access(db, patient_ref_id, therapist_id)

            trend_rows = await db.execute(
                text("""
                    SELECT metric, trend_json FROM patient_metric_trends
                    WHERE patient_ref_id = CAST(:patient_ref_id AS uuid)
                      AND therapist_id = CAST(:therapist_id AS uuid)
                """),
                {"patient_ref_id": patient_ref_id, "therapist_id": therapist_id},
            )
            # trend_json은 metric당 세션별 시계열 값의 list라고 가정한다
            # (§7.3 예시 "metric_trends": {"MLU": [2.1, 2.3, ...]}와 동일한 형태).
            # 이 컬럼을 실제로 채우는 writer가 아직 없어 형태가 운영 데이터로
            # 검증되지 않았다 — 첫 writer 구현 시 이 가정을 재확인해야 한다.
            metric_trends: dict[str, list[float]] = {}
            for metric, trend_json in trend_rows:
                if isinstance(trend_json, list):
                    metric_trends[metric] = [float(v) for v in trend_json][-recent_session_count:]

            goal_row = await db.execute(
                text("""
                    SELECT session_goal FROM sessions
                    WHERE patient_ref_id = CAST(:patient_ref_id AS uuid)
                      AND session_goal IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"patient_ref_id": patient_ref_id},
            )
            goal_record = goal_row.first()
            current_goal = goal_record[0] if goal_record else None

            summary_rows = await db.execute(
                text("""
                    SELECT summary FROM soap_case_indexes
                    WHERE patient_ref_id = CAST(:patient_ref_id AS uuid)
                      AND therapist_id = CAST(:therapist_id AS uuid)
                    ORDER BY created_at DESC
                    LIMIT :recent_session_count
                """),
                {
                    "patient_ref_id": patient_ref_id,
                    "therapist_id": therapist_id,
                    "recent_session_count": recent_session_count,
                },
            )
            summaries = [row[0] for row in summary_rows]
            goal_progress_summary = "; ".join(reversed(summaries)) if summaries else None

            return PatientHistory(
                recent_session_count=recent_session_count,
                metric_trends=metric_trends,
                current_goal=current_goal,
                goal_progress_summary=goal_progress_summary,
                # clinician_cautions에 대응하는 소스 테이블이 아직 없어 비워둔다.
                clinician_cautions=[],
            )
