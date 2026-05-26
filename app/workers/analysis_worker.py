# 분석 Worker
# SQS에서 분석 요청 메시지를 수신해 전체 AI 분석 파이프라인을 실행한다
# CPU Worker(VAD, Kiwi, RAG)와 GPU Worker(Whisper, pyannote, EXAONE)로 분리 배포 가능하다
import asyncio
import json

import boto3
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas import JobMessage
from app.pipelines.analysis_pipeline import run_analysis, PipelineModels
from app.models.vad_silero import SileroVADWrapper
from app.models.diarization_pyannote import PyannoteWrapper
from app.models.asr_whisper import WhisperASRWrapper
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.models.llm_exaone import EXAONEWrapper
from app.rag.vector_store import VectorStore
from app.rag.retriever import Retriever
from app.storage.db import engine


def _load_models() -> PipelineModels:
    """Worker 시작 시 한 번만 호출해 모든 모델을 메모리에 로드한다."""
    logger.info("모델 로딩 시작...")

    vad = SileroVADWrapper(settings.vad_model_name)
    vad.load()
    logger.info("Silero VAD 로드 완료")

    diarize = PyannoteWrapper(settings.diarization_model_name,
                              device=settings.diarization_device,
                              hf_token=settings.hf_token)
    diarize.load()
    logger.info("pyannote diarization 로드 완료")

    asr = WhisperASRWrapper(settings.asr_model_name, device=settings.asr_device)
    asr.load()
    logger.info("Whisper ASR 로드 완료")

    embedding = KUREEmbeddingWrapper(settings.embedding_model_name)
    embedding.load()
    logger.info("KURE embedding 로드 완료")

    llm = EXAONEWrapper(settings.llm_model_name, device=settings.llm_device)
    llm.load()
    logger.info("EXAONE LLM 로드 완료")

    # Retriever는 DB 세션을 매 Job마다 새로 만들어야 하므로 여기서는 embedding만 보관
    # handle_message에서 세션과 함께 조립한다
    return PipelineModels(
        vad=vad,
        diarize=diarize,
        asr=asr,
        retriever=None,  # 매 Job마다 DB 세션으로 생성
        llm=llm,
    ), embedding


async def _handle_message_async(
    message: dict,
    base_models: PipelineModels,
    embedding: KUREEmbeddingWrapper,
) -> None:
    job = JobMessage(**message)
    async with AsyncSession(engine) as session:
        vector_store = VectorStore(session)
        retriever = Retriever(vector_store, embedding,
                              settings.rag_top_k, settings.rag_score_threshold)
        models = PipelineModels(
            vad=base_models.vad,
            diarize=base_models.diarize,
            asr=base_models.asr,
            retriever=retriever,
            llm=base_models.llm,
        )
        await run_analysis(job, models)


def start_worker() -> None:
    """SQS 큐를 폴링하며 메시지를 수신하고 분석 파이프라인을 실행하는 루프."""
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    base_models, embedding = _load_models()

    logger.info(f"Worker 시작. 큐: {settings.sqs_analysis_queue_url}")

    while True:
        response = sqs.receive_message(
            QueueUrl=settings.sqs_analysis_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,  # long polling
            VisibilityTimeout=600,  # 10분: 파이프라인 최대 처리 시간
        )

        messages = response.get("Messages", [])
        if not messages:
            continue

        raw = messages[0]
        receipt_handle = raw["ReceiptHandle"]
        body = json.loads(raw["Body"])

        try:
            asyncio.run(_handle_message_async(body, base_models, embedding))
            sqs.delete_message(
                QueueUrl=settings.sqs_analysis_queue_url,
                ReceiptHandle=receipt_handle,
            )
            logger.info(f"메시지 처리 완료: job_id={body.get('job_id')}")
        except Exception as e:
            logger.error(f"메시지 처리 실패: {e}")
            # 메시지를 삭제하지 않으면 VisibilityTimeout 후 재처리됨
