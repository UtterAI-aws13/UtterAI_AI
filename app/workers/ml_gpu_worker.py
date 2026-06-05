# ML GPU Worker
# utterai-dev-audio-ml-queue 폴링
# 로드 모델: pyannote speaker-diarization, Whisper ASR
# 담당 단계: 화자 분리 + STT → S3 저장 → llm-queue 발행
import asyncio
import json

import boto3
from loguru import logger

from app.config import settings
from app.schemas import MLGpuMessage
from app.pipelines.analysis_pipeline import run_ml_gpu_stage, MLGpuModels
from app.models.diarization_pyannote import PyannoteWrapper
from app.models.asr_whisper import WhisperASRWrapper


def _load_models() -> MLGpuModels:
    diarize = PyannoteWrapper(
        settings.diarization_model_name,
        device=settings.diarization_device,
        hf_token=settings.hf_token,
    )
    diarize.load()
    logger.info("pyannote diarization 로드 완료")

    asr = WhisperASRWrapper(settings.asr_model_name, device=settings.asr_device)
    asr.load()
    logger.info("Whisper ASR 로드 완료")

    return MLGpuModels(diarize=diarize, asr=asr)


def start_worker() -> None:
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    models = _load_models()
    logger.info(f"ML GPU Worker 시작. 큐: {settings.sqs_ml_gpu_queue_url}")

    while True:
        response = sqs.receive_message(
            QueueUrl=settings.sqs_ml_gpu_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=600,
        )
        messages = response.get("Messages", [])
        if not messages:
            continue

        raw = messages[0]
        receipt_handle = raw["ReceiptHandle"]
        body = json.loads(raw["Body"])

        try:
            msg = MLGpuMessage(**body)
            asyncio.run(run_ml_gpu_stage(msg, models))
            sqs.delete_message(
                QueueUrl=settings.sqs_ml_gpu_queue_url,
                ReceiptHandle=receipt_handle,
            )
            logger.info(f"ML GPU STAGE 완료: job_id={body.get('job_id')}")
        except Exception as e:
            logger.error(f"ML GPU STAGE 실패: {e}")
