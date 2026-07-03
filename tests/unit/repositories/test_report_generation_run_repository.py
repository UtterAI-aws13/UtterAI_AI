"""report_generation_runs/events repository. AsyncSession은 mock, 실제 DB에 연결하지 않는다.

json.dumps() + CAST(... AS jsonb) 패턴을 강제한다 - 이 테스트가 없으면
dict를 그대로 바인딩해 psycopg의 "cannot adapt type 'dict'" 런타임 에러로만
발견되는 회귀가 재발할 수 있다 (Phase 2에서 실제로 겪은 버그).
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.report_generation.models.common import FailureCode, RunStatus
from app.repositories.report_generation_run_repository import (
    SqlReportGenerationRunRepository,
    record_event,
)


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
    return patch(
        "app.repositories.report_generation_run_repository.AsyncSession",
        return_value=cm,
    )


@pytest.mark.asyncio
async def test_create_run_serializes_json_fields(mock_session):
    with _patch_engine(mock_session):
        await SqlReportGenerationRunRepository().create_run(
            run_id="r1", session_id="s1", patient_ref_id="p1", therapist_id="t1",
            graph_version="v1", model_config={"context_agent_model_id": "x"},
        )

    params = mock_session.execute.call_args.args[1]
    assert params["model_config_json"] == json.dumps({"context_agent_model_id": "x"})
    assert params["retry_budget_json"] == json.dumps({})
    assert params["status"] == RunStatus.QUEUED.value
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_progress_serializes_retry_budget(mock_session):
    with _patch_engine(mock_session):
        await SqlReportGenerationRunRepository().update_progress(
            run_id="r1", status=RunStatus.RESEARCHING, current_node="evidence_research",
            retry_budget={"research_round": 2},
        )

    params = mock_session.execute.call_args.args[1]
    assert params["retry_budget_json"] == json.dumps({"research_round": 2})
    assert params["status"] == RunStatus.RESEARCHING.value


@pytest.mark.asyncio
async def test_mark_failed_serializes_failure_code(mock_session):
    with _patch_engine(mock_session):
        await SqlReportGenerationRunRepository().mark_failed(
            run_id="r1", failure_code=FailureCode.UNAUTHORIZED, failure_detail="denied"
        )

    params = mock_session.execute.call_args.args[1]
    assert params["failure_code"] == "UNAUTHORIZED"
    assert params["status"] == RunStatus.FAILED.value


@pytest.mark.asyncio
async def test_record_event_serializes_optional_json_fields(mock_session):
    with _patch_engine(mock_session):
        await record_event(
            run_id="r1", node_name="evidence_research", event_type="NODE_COMPLETED",
            decision="ACCEPT", retry_count=1, duration_ms=500,
            token_usage={"input": 10}, metadata={"note": "x"},
        )

    params = mock_session.execute.call_args.args[1]
    assert params["token_usage_json"] == json.dumps({"input": 10})
    assert params["metadata_json"] == json.dumps({"note": "x"})


@pytest.mark.asyncio
async def test_record_event_handles_none_optional_fields(mock_session):
    with _patch_engine(mock_session):
        await record_event(run_id="r1", node_name="load_context", event_type="NODE_COMPLETED")

    params = mock_session.execute.call_args.args[1]
    assert params["token_usage_json"] is None
    assert params["metadata_json"] is None
