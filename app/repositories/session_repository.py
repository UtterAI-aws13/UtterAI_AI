# LOAD_CONTEXT가 확정 세션 데이터를 조회할 때 쓰는 인터페이스.
# 구현은 Phase 2에서 붙인다 (SQLAlchemy 기반, object-level authorization 포함).
# 참고: 01_production_5_agent_agentic_rag_design.md §7
from typing import Protocol

from app.agents.report_generation.models.common import CurrentSession


class SessionRepository(Protocol):
    async def get_current_session(
        self, session_id: str, therapist_id: str
    ) -> CurrentSession:
        """확정 transcript, 선택 분석표, 현재 세션 지표를 조회한다.

        therapist_id가 session_id에 접근 권한이 없으면 예외를 발생시킨다
        (권한 검증은 prompt가 아니라 이 계층에서 강제한다).
        """
        ...

    async def has_existing_report_generation_run(self, session_id: str) -> bool:
        """동일 세션에 대한 리포트 생성 중복 실행 여부를 확인한다."""
        ...
