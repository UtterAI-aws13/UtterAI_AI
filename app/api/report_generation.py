# 5-Agent 리포트 생성 API (서비스 간 내부 전용, jobs.py와 동일한 신뢰 경계)
# POST /internal/ai/sessions/{session_id}/reports/generate - run_id를 생성하고 SQS 발행
# GET  /internal/ai/report-generation-runs/{run_id}        - 진행 상태 조회
# 참고: 01_production_5_agent_agentic_rag_design.md §19, §20
import uuid
from datetime import UTC, datetime

import boto3
from fastapi import APIRouter, HTTPException
from opentelemetry import trace

from app.agents.report_generation.errors import UnauthorizedError
from app.agents.report_generation.graph import build_default_dependencies
from app.config import settings
from app.schemas.report_generation import (
    ReportGenerationCreateRequest,
    ReportGenerationCreateResponse,
    ReportGenerationQueueMessage,
    ReportGenerationStatusResponse,
    build_status_response,
)

router = APIRouter()

_sqs = None


def _get_sqs():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=settings.aws_region)
    return _sqs


@router.post("/sessions/{session_id}/reports/generate", response_model=ReportGenerationCreateResponse)
async def create_report_generation_run(session_id: str, request: ReportGenerationCreateRequest):
    """report_generation_runs row 생성/실행은 워커가 담당한다 (jobs.py의
    create_job()과 동일하게, API는 SQS 발행만 하고 즉시 응답한다).
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("ai_api.create_report_generation_run") as span:
        run_id = str(uuid.uuid4())

        message = ReportGenerationQueueMessage(
            run_id=run_id,
            session_id=session_id,
            patient_ref_id=request.patient_ref_id,
            therapist_id=request.therapist_id,
            selected_analysis=request.selected_analysis,
            history_session_count=request.history_session_count,
            requested_at=datetime.now(UTC),
        )

        _get_sqs().send_message(
            QueueUrl=settings.sqs_report_generation_queue_url,
            MessageBody=message.model_dump_json(),
        )

        span.set_attribute("report_generation.run_id", run_id)
        return ReportGenerationCreateResponse(run_id=run_id, status="QUEUED")


@router.get("/report-generation-runs/{run_id}", response_model=ReportGenerationStatusResponse)
async def get_report_generation_run(run_id: str, therapist_id: str):
    """therapist_id는 쿼리 파라미터로 받아 소유권을 검증한다 (§19.2).

    TODO: 인증 헤더에서 therapist_id를 추출하도록 교체 (jobs.py의
    user_id="system" TODO와 동일한 임시 신뢰 경계).
    """
    deps = build_default_dependencies()
    try:
        run_row = await deps.run_repo.get_run(run_id, therapist_id)
    except UnauthorizedError:
        raise HTTPException(status_code=404, detail="run not found") from None
    return build_status_response(run_row)
