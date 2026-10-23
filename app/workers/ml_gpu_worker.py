# ML GPU Worker
# utterai-dev-gpu-inference-queue 폴링
# 로드 모델: pyannote speaker-diarization, Whisper ASR
# 담당 단계: 화자 분리 + STT → transcript draft 저장 → 완료 (리포트 큐는 BE finalize가 발행)
import asyncio
import json

from botocore.config import Config
from app.workers.lifecycle import Lifecycle, VISIBILITY_SECONDS, start_heartbeat, stop_heartbeat

import boto3
from loguru import logger
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.observability.otel import initialize_observability
from app.observability.metrics import record_sqs_receive
from app.observability.metrics import record_stage_failure
from app.observability.sqs import extract_context_from_message_attributes
from app.schemas import MLGpuMessage
from app.pipelines.analysis_pipeline import run_ml_gpu_stage, MLGpuModels
from app.models.diarization_pyannote import PyannoteWrapper
from app.models.asr_whisper import WhisperASRWrapper
from app.storage.rds import get_be_engine

_runtime = Lifecycle()
_visibility_client = None


def _load_models() -> MLGpuModels:
    diarize = PyannoteWrapper(
        settings.diarization_model_name,
        device=settings.diarization_device,
        hf_token=settings.hf_token,
    )
    diarize.load()
    logger.info("pyannote diarization 로드 완료")

    asr = WhisperASRWrapper(
        settings.asr_model_name,
        device=settings.asr_device,
    )
    asr.load()
    logger.info("Whisper ASR 로드 완료")

    return MLGpuModels(diarize=diarize, asr=asr)


def start_worker() -> None:
    global _visibility_client
    _visibility_client = boto3.client(
        "sqs",
        region_name=settings.aws_region,
        config=Config(connect_timeout=1, read_timeout=2, retries={"max_attempts": 0}),
    )
    _runtime.start()
    initialize_observability()
    sqs = boto3.client(
        "sqs",
        region_name=settings.aws_region,
        config=Config(connect_timeout=2, read_timeout=25, retries={"max_attempts": 1}),
    )
    models = _load_models()
    _runtime.mark_ready()
    logger.info(f"ML GPU Worker 시작. 큐: {settings.sqs_gpu_inference_queue_url}")

    while not _runtime.stop.is_set():
        try:
            response = sqs.receive_message(
                QueueUrl=settings.sqs_gpu_inference_queue_url,
                MaxNumberOfMessages=1,
                VisibilityTimeout=VISIBILITY_SECONDS,
                WaitTimeSeconds=20,
                MessageAttributeNames=["All"],
            )
        except Exception as e:
            logger.error(f"[ml-gpu-worker] SQS receive_message 실패: {e}")
            continue

        messages = response.get("Messages", [])
        if not messages:
            continue

        raw = messages[0]
        receipt_handle = raw["ReceiptHandle"]
        if not _runtime.accept(sqs, settings.sqs_gpu_inference_queue_url, receipt_handle):
            continue
        handle = start_heartbeat(
            _visibility_client, settings.sqs_gpu_inference_queue_url, receipt_handle
        )
        body = {}
        try:
            body = json.loads(raw["Body"])
            message_context = extract_context_from_message_attributes(raw.get("MessageAttributes"))
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(
                "worker.ml_gpu.message",
                context=message_context,
                kind=trace.SpanKind.CONSUMER,
            ) as span:
                record_sqs_receive("ml-gpu-worker")
                msg = MLGpuMessage(**body)
                span.set_attribute("session_id", msg.session_id)
                span.set_attribute("job_id", msg.job_id)
                if msg.user_id:
                    span.set_attribute("user.id", msg.user_id)

                async def _run():
                    async with AsyncSession(get_be_engine()) as session:
                        await run_ml_gpu_stage(msg, models, session)

                asyncio.run(_run())
                logger.info(f"ML GPU STAGE 완료: job_id={body.get('job_id')}")
            stop_heartbeat(handle)
            sqs.delete_message(
                QueueUrl=settings.sqs_gpu_inference_queue_url,
                ReceiptHandle=receipt_handle,
            )
        except Exception as e:
            record_stage_failure("ml-gpu-worker", "message")
            logger.error(f"ML GPU STAGE 실패: {e}")
            stop_heartbeat(handle)
            try:
                sqs.change_message_visibility(
                    QueueUrl=settings.sqs_gpu_inference_queue_url,
                    ReceiptHandle=receipt_handle,
                    VisibilityTimeout=0,
                )
            except Exception as vis_e:
                logger.warning(f"[ml-gpu-worker] VisibilityTimeout 즉시 해제 실패: {vis_e}")
        finally:
            stop_heartbeat(handle)
            _runtime.finish()


if __name__ == "__main__":
    start_worker()
