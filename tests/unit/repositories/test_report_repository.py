"""report_drafts 저장. json.dumps + CAST(...AS jsonb) 강제 (Phase 2 실제 버그 회귀 방지)."""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.report_repository import SqlReportRepository


@pytest.fixture
def mock_session():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


def _patch_engine(mock_session):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return patch("app.repositories.report_repository.AsyncSession", return_value=cm)


@pytest.mark.asyncio
async def test_save_draft_serializes_all_json_fields_and_returns_uuid(mock_session):
    with _patch_engine(mock_session):
        report_draft_id = await SqlReportRepository().save_draft(
            generation_run_id="run1", session_id="s1", patient_ref_id="p1", therapist_id="t1",
            soap={"S": "s", "O": "o", "A": "a", "P": "p"},
            reasoning_summary={"S": []},
            claims=[{"claim_id": "A1"}],
            evidence_trace={"claims": []},
            validation={"passed": True},
            quality_scores={"overall": 0.95},
        )

    uuid.UUID(report_draft_id)
    params = mock_session.execute.call_args.args[1]
    assert params["soap_json"] == json.dumps({"S": "s", "O": "o", "A": "a", "P": "p"})
    assert params["claims_json"] == json.dumps([{"claim_id": "A1"}])
    assert params["quality_scores_json"] == json.dumps({"overall": 0.95})
    mock_session.commit.assert_awaited_once()
