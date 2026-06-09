# 분석 Job API (서비스 간 내부 전용)
# POST /internal/ai/analysis-jobs          - Backend가 음성 분석을 요청할 때 Job을 생성하고 job_id를 즉시 반환
# GET  /internal/ai/analysis-jobs/{job_id} - 처리 단계와 진행 상태를 폴링할 때 사용
import json
from datetime import datetime, timezone

import boto3
from fastapi import APIRouter, HTTPException
from opentelemetry import trace

from app.config import settings
from app.observability.metrics import record_job_created, record_sqs_publish
from app.observability.sqs import build_message_attributes_from_current_context
from app.schemas import (
    JobCreateRequest, JobCreateResponse, JobStatusResponse,
    JobStatus, JobMessage, AudioInput, JobOptions,
)
from app.utils.ids import generate_job_id

router = APIRouter()

_sqs = None


def _get_sqs():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=settings.aws_region)
    return _sqs


@router.post("", response_model=JobCreateResponse)
async def create_job(request: JobCreateRequest):
    """분석 Job을 생성하고 SQS에 메시지를 발행한다.

    Worker가 SQS 메시지를 수신해 비동기로 분석을 처리하므로
    API는 job_id와 PENDING 상태만 즉시 반환한다.
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("ai_api.create_job") as span:
        job_id = generate_job_id()

        message = JobMessage(
            job_id=job_id,
            session_id=request.session_id,
            user_id="system",  # TODO: 인증 헤더에서 user_id 추출
            audio=AudioInput(bucket=settings.s3_bucket_audio, key=request.audio_s3_key),
            options=request.options,
            requested_at=datetime.now(timezone.utc),
        )

        _get_sqs().send_message(
            QueueUrl=settings.sqs_analysis_queue_url,
            MessageBody=message.model_dump_json(),
            MessageAttributes=build_message_attributes_from_current_context(),
        )

        record_job_created()
        record_sqs_publish("analysis-request")
        span.set_attribute("job.id", job_id)
        span.set_attribute("audio.key", request.audio_s3_key)
        return JobCreateResponse(job_id=job_id, status=JobStatus.PENDING)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    """DB에서 Job 상태를 조회한다. Backend가 완료 여부를 폴링하는 용도로 사용."""
    # TODO: Job 상태 테이블 ORM 추가 후 DB 조회로 교체
    raise HTTPException(status_code=404, detail="job not found")
