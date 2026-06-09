# LLM GPU Worker
# utterai-dev-report-analysis-queue 폴링
# 로드 모델: KURE-v1 embedding (RAG용), EXAONE LLM
# 담당 단계: 정렬 + 지표 + RAG + EXAONE → 최종 S3/RDS 저장
import asyncio
import json

import boto3
from loguru import logger
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.observability.otel import initialize_observability
from app.observability.metrics import record_sqs_receive
from app.observability.metrics import record_stage_failure
from app.observability.sqs import extract_context_from_message_attributes
from app.schemas import LLMMessage
from app.pipelines.analysis_pipeline import run_llm_gpu_stage, LLMModels
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.models.llm_exaone import EXAONEWrapper
from app.rag.vector_store import VectorStore
from app.rag.retriever import Retriever
from app.storage.db import get_engine


def _load_base_models() -> tuple[KUREEmbeddingWrapper, EXAONEWrapper]:
    embedding = KUREEmbeddingWrapper(settings.embedding_model_name)
    embedding.load()
    logger.info("KURE embedding 로드 완료")

    llm = EXAONEWrapper(settings.llm_model_name, device=settings.llm_device)
    llm.load()
    logger.info("EXAONE LLM 로드 완료")

    return embedding, llm


def start_worker() -> None:
    initialize_observability()
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    embedding, llm = _load_base_models()
    logger.info(f"LLM GPU Worker 시작. 큐: {settings.sqs_report_analysis_queue_url}")

    while True:
        response = sqs.receive_message(
            QueueUrl=settings.sqs_report_analysis_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=1800,
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
            with tracer.start_as_current_span("worker.llm.message", context=message_context):
                record_sqs_receive("llm-gpu-worker")
                msg = LLMMessage(**body)

                async def _run():
                    async with AsyncSession(get_engine()) as session:
                        vector_store = VectorStore(session)
                        retriever = Retriever(
                            vector_store, embedding,
                            settings.rag_top_k, settings.rag_score_threshold,
                        )
                        models = LLMModels(embedding=embedding, llm=llm, retriever=retriever)
                        await run_llm_gpu_stage(msg, models)

                asyncio.run(_run())
                sqs.delete_message(
                    QueueUrl=settings.sqs_report_analysis_queue_url,
                    ReceiptHandle=receipt_handle,
                )
                logger.info(f"LLM STAGE 완료: job_id={body.get('job_id')}")
        except Exception as e:
            record_stage_failure("llm-gpu-worker", "message")
            logger.error(f"LLM STAGE 실패: {e}")
