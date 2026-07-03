# SAVE_DRAFT가 report_drafts를 저장할 때 쓰는 인터페이스.
# 구현은 Phase 2에서 붙인다. deterministic/QA validation을 모두 통과한
# 결과만 이 인터페이스를 거쳐 DRAFT 상태로 저장된다.
# 참고: 01_production_5_agent_agentic_rag_design.md §18.2
from typing import Any, Protocol


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
