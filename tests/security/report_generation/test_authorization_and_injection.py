"""IDOR/cross-therapist/injection/oversized-payload/trace 노출 방지. 참고: §25.4."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput
from app.agents.report_generation.errors import UnauthorizedError
from app.agents.report_generation.models.report import ReportClaim, SoapDraft, SoapReasoningPlan
from app.agents.report_generation.validators.state_transition_validator import (
    sanitize_text,
    validate_no_foreign_ids,
    validate_payload_size,
)
from app.repositories.report_generation_run_repository import SqlReportGenerationRunRepository
from app.services.authorization_service import AuthorizationService

_PLAN = SoapReasoningPlan(S=[], O=[], A=[], P=[])
_SOAP = SoapDraft(S="s", O="o", A="a", P="p")


def _mock_db(rows: list) -> AsyncMock:
    db = AsyncMock()
    results = []
    for row in rows:
        result = MagicMock()
        result.first.return_value = row
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    return db


class TestIDOR:
    @pytest.mark.asyncio
    async def test_cross_therapist_session_access_denied(self):
        """IDOR: session_id를 알고 있다는 이유만으로 다른 치료사가 접근할 수 없다."""
        db = _mock_db([("owner-therapist", "ACTIVE"), ("SLP",)])
        with pytest.raises(UnauthorizedError):
            await AuthorizationService().ensure_session_access(db, "victim-session", "attacker-therapist")

    @pytest.mark.asyncio
    async def test_cross_therapist_patient_ref_access_denied(self):
        db = _mock_db([("owner-therapist",), ("SLP",)])
        with pytest.raises(UnauthorizedError):
            await AuthorizationService().ensure_patient_ref_access(db, "victim-patient", "attacker-therapist")

    @pytest.mark.asyncio
    async def test_get_run_denies_non_owner_without_leaking_row(self):
        """get_run은 소유자가 아니면 존재 여부/내용을 노출하지 않고 동일하게 거부한다."""
        import unittest.mock as mock

        with mock.patch("app.repositories.report_generation_run_repository.AsyncSession") as MockSession:
            cm = MagicMock()
            row_result = MagicMock()
            row_result.mappings.return_value.first.return_value = {
                "id": "run1", "therapist_id": "owner-therapist", "status": "SUCCEEDED",
            }
            db = AsyncMock()
            db.execute = AsyncMock(return_value=row_result)
            cm.__aenter__ = AsyncMock(return_value=db)
            cm.__aexit__ = AsyncMock(return_value=False)
            MockSession.return_value = cm

            with pytest.raises(UnauthorizedError):
                await SqlReportGenerationRunRepository().get_run("run1", "attacker-therapist")


class TestPromptInjectionDefenses:
    def test_malicious_html_script_stripped_from_claim_text(self):
        text = 'MLU 개선<script>alert(1)</script> <img src=x onerror=alert(2)> 시사'
        cleaned = sanitize_text(text)
        assert "<script>" not in cleaned
        assert "onerror" not in cleaned

    def test_foreign_patient_id_injected_via_evidence_is_caught(self):
        """근거 chunk에 다른 환자 ID가 섞여 claim에 그대로 반영되면 차단한다."""
        leaked_id = "99999999-9999-9999-9999-999999999999"
        report = ClinicalReportOutput(
            reasoning_plan=_PLAN, soap=_SOAP,
            claims=[
                ReportClaim(
                    claim_id="A1", section="A",
                    text=f"환자 {leaked_id}의 이전 리포트에 따르면...",
                    claim_strength="OBSERVATION",
                )
            ],
        )
        issues = validate_no_foreign_ids(
            report, session_id="11111111-1111-1111-1111-111111111111",
            patient_ref_id="22222222-2222-2222-2222-222222222222",
        )
        assert len(issues) == 1


class TestOversizedPayload:
    def test_oversized_claim_text_rejected(self):
        report = ClinicalReportOutput(
            reasoning_plan=_PLAN, soap=_SOAP,
            claims=[
                ReportClaim(claim_id="A1", section="A", text="x" * 5000, claim_strength="OBSERVATION")
            ],
        )
        issues = validate_payload_size(report, max_length=2000)
        assert len(issues) == 1


class TestTraceRedaction:
    @pytest.mark.asyncio
    async def test_save_draft_event_metadata_does_not_contain_transcript_or_soap_text(self):
        """§22.3: report_generation_events에는 SOAP/transcript 원문이 남지 않아야 한다."""
        from unittest.mock import patch

        from app.agents.report_generation.graph_state import (
            REPORT_REPO_KEY,
            RUN_REPO_KEY,
            STATE_KEY,
            GraphStatus,
            ReportGenerationState,
        )
        from app.agents.report_generation.evidence_critic.schemas import EvidenceCriticOutput
        from app.agents.report_generation.nodes import SaveDraftNode

        secret_transcript_marker = "이것은-절대-로그에-남으면-안되는-원문-마커"
        report = ClinicalReportOutput(
            reasoning_plan=_PLAN,
            soap=SoapDraft(S=secret_transcript_marker, O="o", A="a", P="p"),
            claims=[
                ReportClaim(claim_id="A1", section="A", text="x", claim_strength="OBSERVATION")
            ],
        )
        critic = EvidenceCriticOutput(decision="ACCEPT")
        state = ReportGenerationState(
            run_id="r1", session_id="s1", patient_ref_id="p1", therapist_id="t1",
            status=GraphStatus.QA_PASSED, report_result=report.model_dump(), critic_result=critic.model_dump(),
        )
        run_repo = AsyncMock()
        report_repo = AsyncMock()
        report_repo.save_draft = AsyncMock(return_value="draft-1")
        invocation_state = {STATE_KEY: state, RUN_REPO_KEY: run_repo, REPORT_REPO_KEY: report_repo}

        with patch(
            "app.repositories.report_generation_run_repository.record_event", new=AsyncMock()
        ) as mock_record:
            await SaveDraftNode().invoke_async("x", invocation_state)

        recorded_metadata = mock_record.call_args.kwargs.get("metadata") or {}
        assert secret_transcript_marker not in str(recorded_metadata)
