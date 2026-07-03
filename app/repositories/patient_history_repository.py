# LOAD_CONTEXT가 환자 longitudinal context를 조회할 때 쓰는 인터페이스.
# 정량 지표는 RDS deterministic query로만 조회한다. AgentCore Memory를
# source of truth로 쓰지 않는다.
# 참고: 01_production_5_agent_agentic_rag_design.md §7.2
from typing import Protocol

from app.agents.report_generation.models.common import PatientHistory


class PatientHistoryRepository(Protocol):
    async def get_patient_history(
        self, patient_ref_id: str, therapist_id: str, recent_session_count: int
    ) -> PatientHistory:
        """최근 N회기 요약과 지표 추이를 조회한다.

        therapist_id가 patient_ref_id에 접근 권한이 없으면 예외를 발생시킨다.
        """
        ...
