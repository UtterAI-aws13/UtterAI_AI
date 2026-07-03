# LOAD_CONTEXT deterministic node의 핵심 로직.
# Phase 4에서 Strands Graph 노드로 얇게 감싸질 함수 — 여기서는 Graph에 의존하지 않는다.
# 참고: 01_production_5_agent_agentic_rag_design.md §7.1
#
# 중복 실행 방지(§7.1 항목 8)는 여기서 하지 않는다 — Phase 4의
# run_report_generation()이 report_generation_runs row를 생성하기 *전에* 확인한다.
# 이 함수 안에서 확인하면 그 시점엔 이미 자기 자신의 run이 QUEUED로 존재해
# 항상 자기 자신을 중복으로 오판한다.
from app.agents.report_generation.models.common import CurrentSession, PatientHistory
from app.repositories.patient_history_repository import PatientHistoryRepository
from app.repositories.session_repository import SessionRepository


async def load_context(
    *,
    session_id: str,
    patient_ref_id: str,
    therapist_id: str,
    selected_analysis: list[str],
    history_session_count: int,
    session_repo: SessionRepository,
    patient_history_repo: PatientHistoryRepository,
) -> tuple[CurrentSession, PatientHistory]:
    """§7.1의 9개 책임 중 권한 검증/확정 데이터 조회를 수행한다.

    민감정보 최소화(§7.1 항목 9)는 CurrentSession/PatientHistory 스키마 자체가
    필요한 필드만 노출하도록 설계되어 있어 이 함수가 별도로 마스킹하지 않는다.
    """
    current_session = await session_repo.get_current_session(
        session_id, therapist_id, selected_analysis
    )
    patient_history = await patient_history_repo.get_patient_history(
        patient_ref_id, therapist_id, history_session_count
    )
    return current_session, patient_history
