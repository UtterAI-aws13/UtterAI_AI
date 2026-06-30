# CPU Worker
# utterai-dev-audio-preprocess-queue, utterai-dev-report-analysis-queue 폴링
# 로드 모델: Silero VAD, KURE-v1 embedding
# 담당 단계: 전처리 + VAD → S3 저장 → gpu-inference-queue 발행
#           RAG 검색 + Bedrock Claude 리포트 생성 → RDS 저장
import asyncio
import json
import threading

import boto3
from loguru import logger
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.observability.otel import initialize_observability
from app.observability.metrics import record_sqs_receive
from app.observability.metrics import record_stage_failure
from app.observability.sqs import extract_context_from_message_attributes
from app.schemas import JobMessage
from app.schemas.job import ReportJobMessage
from app.pipelines.analysis_pipeline import run_cpu_stage, CPUModels
from app.pipelines.report_pipeline import run_bedrock_report_stage
from app.models.vad_silero import SileroVADWrapper
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.storage.rds import get_be_engine


def _extend_report_visibility(sqs, queue_url: str, receipt_handle: str, stop_event: threading.Event, interval: int = 240) -> None:
    while True:
        try:
            sqs.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=1800,
            )
        except Exception as e:
            logger.warning(f"[report-heartbeat] VisibilityTimeout 연장 실패: {e}")
        if stop_event.wait(interval):
            break


def _load_models() -> CPUModels:
    vad = SileroVADWrapper(settings.vad_model_name)
    vad.load()
    logger.info("Silero VAD 로드 완료")

    embedding = KUREEmbeddingWrapper(settings.embedding_model_name)
    embedding.load()
    logger.info("KURE embedding 로드 완료")

    return CPUModels(vad=vad, embedding=embedding)


def _run_preprocess_loop(sqs, models: CPUModels) -> None:
    logger.info(f"CPU Worker 시작. 큐: {settings.sqs_audio_preprocess_queue_url}")
    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=settings.sqs_audio_preprocess_queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=300,
                MessageAttributeNames=["All"],
            )
        except Exception as e:
            logger.error(f"[cpu-worker] SQS receive_message 실패: {e}")
            continue

        messages = response.get("Messages", [])
        if not messages:
            continue

        raw = messages[0]
        receipt_handle = raw["ReceiptHandle"]
        body = json.loads(raw["Body"])
        message_context = extract_context_from_message_attributes(raw.get("MessageAttributes"))

        try:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(
                "worker.cpu.message",
                context=message_context,
                kind=trace.SpanKind.CONSUMER,
            ) as span:
                record_sqs_receive("cpu-worker")
                job = JobMessage(**body)
                span.set_attribute("session_id", job.session_id)
                span.set_attribute("user_id", job.user_id)
                asyncio.run(run_cpu_stage(job, models))
                sqs.delete_message(
                    QueueUrl=settings.sqs_audio_preprocess_queue_url,
                    ReceiptHandle=receipt_handle,
                )
                logger.info(f"CPU STAGE 완료: job_id={body.get('job_id')}")
        except Exception as e:
            record_stage_failure("cpu-worker", "message")
            logger.error(f"CPU STAGE 실패: {e}")


def _run_report_loop(sqs, embedding: KUREEmbeddingWrapper) -> None:
    logger.info(f"Report Worker 시작. 큐: {settings.sqs_report_analysis_queue_url}")
    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=settings.sqs_report_analysis_queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=600,
                MessageAttributeNames=["All"],
            )
        except Exception as e:
            logger.error(f"[report-loop] SQS receive_message 실패: {e}")
            continue

        messages = response.get("Messages", [])
        if not messages:
            continue

        raw = messages[0]
        receipt_handle = raw["ReceiptHandle"]

        try:
            body = json.loads(raw["Body"])
            job_id = body.get("job_id", "unknown")
            logger.info(f"[report-loop] 메시지 수신 job_id={job_id} transcript_id={body.get('transcript_id')}")
            message_context = extract_context_from_message_attributes(raw.get("MessageAttributes"))
        except Exception as e:
            logger.exception(f"[report-loop] 메시지 파싱 실패: {e}")
            continue

        stop_event = threading.Event()
        heartbeat = threading.Thread(
            target=_extend_report_visibility,
            args=(sqs, settings.sqs_report_analysis_queue_url, receipt_handle, stop_event),
            daemon=True,
        )
        heartbeat.start()

        try:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(
                "worker.report.message",
                context=message_context,
                kind=trace.SpanKind.CONSUMER,
            ) as span:
                record_sqs_receive("cpu-worker-report")
                msg = ReportJobMessage(**body)
                span.set_attribute("session_id", msg.session_id)
                span.set_attribute("job_id", msg.job_id)

                logger.info(f"[report-loop] BE DB 세션 열기 job_id={job_id}")

                async def _run():
                    async with AsyncSession(get_be_engine()) as be_session:
                        await run_bedrock_report_stage(
                            msg, None, be_session, embedding_model=embedding
                        )

                asyncio.run(_run())
                sqs.delete_message(
                    QueueUrl=settings.sqs_report_analysis_queue_url,
                    ReceiptHandle=receipt_handle,
                )
                logger.info(f"[report-loop] REPORT STAGE 완료 job_id={job_id}")
        except Exception as e:
            record_stage_failure("cpu-worker", "report")
            logger.exception(f"[report-loop] REPORT STAGE 실패 job_id={job_id}: {e}")
            try:
                sqs.change_message_visibility(
                    QueueUrl=settings.sqs_report_analysis_queue_url,
                    ReceiptHandle=receipt_handle,
                    VisibilityTimeout=0,
                )
            except Exception as vis_e:
                logger.warning(f"[report-loop] VisibilityTimeout 즉시 해제 실패: {vis_e}")
        finally:
            stop_event.set()


def start_worker() -> None:
    initialize_observability()
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    models = _load_models()

    report_thread = threading.Thread(
        target=_run_report_loop,
        args=(sqs, models.embedding),
        daemon=True,
    )
    report_thread.start()

    _run_preprocess_loop(sqs, models)


if __name__ == "__main__":
    start_worker()
