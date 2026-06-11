# CPU Worker
# utterai-dev-audio-preprocess-queue 폴링
# 로드 모델: Silero VAD, KURE-v1 embedding
# 담당 단계: 전처리 + VAD → S3 저장 → gpu-inference-queue 발행
import asyncio
import json

import boto3
from loguru import logger
from opentelemetry import trace

from app.config import settings
from app.observability.otel import initialize_observability
from app.observability.metrics import record_sqs_receive
from app.observability.metrics import record_stage_failure
from app.observability.sqs import extract_context_from_message_attributes
from app.schemas import JobMessage
from app.pipelines.analysis_pipeline import run_cpu_stage, CPUModels
from app.models.vad_silero import SileroVADWrapper
from app.models.embedding_kure import KUREEmbeddingWrapper


def _load_models() -> CPUModels:
    vad = SileroVADWrapper(settings.vad_model_name)
    vad.load()
    logger.info("Silero VAD 로드 완료")

    embedding = KUREEmbeddingWrapper(settings.embedding_model_name)
    embedding.load()
    logger.info("KURE embedding 로드 완료")

    return CPUModels(vad=vad, embedding=embedding)


def start_worker() -> None:
    initialize_observability()
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    models = _load_models()
    logger.info(f"CPU Worker 시작. 큐: {settings.sqs_audio_preprocess_queue_url}")

    while True:
        response = sqs.receive_message(
            QueueUrl=settings.sqs_audio_preprocess_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=300,
            MessageAttributeNames=["All"],
        )
        messages = response.get("Messages", [])
        if not messages:
            continue

        raw = messages[0]
        receipt_handle = raw["ReceiptHandle"]
        body = json.loads(raw["Body"])
        message_context = extract_context_from_message_attributes(raw.get("MessageAttributes"))

        try:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("worker.cpu.message", context=message_context):
                record_sqs_receive("cpu-worker")
                job = JobMessage(**body)
                asyncio.run(run_cpu_stage(job, models))
                sqs.delete_message(
                    QueueUrl=settings.sqs_audio_preprocess_queue_url,
                    ReceiptHandle=receipt_handle,
                )
                logger.info(f"CPU STAGE 완료: job_id={body.get('job_id')}")
        except Exception as e:
            record_stage_failure("cpu-worker", "message")
            logger.error(f"CPU STAGE 실패: {e}")
