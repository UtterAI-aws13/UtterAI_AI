# report_generation_runs 상태를 기록/조회할 때 쓰는 인터페이스.
# 구현은 Phase 2에서 붙인다.
# 참고: 01_production_5_agent_agentic_rag_design.md §18.1, §19.2
from typing import Any, Protocol

from app.agents.report_generation.models.common import FailureCode, RunStatus


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
