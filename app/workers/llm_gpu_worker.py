# LLM GPU Worker
# utterai-dev-report-analysis-queue 폴링
# 로드 모델: KURE-v1 embedding (RAG용)
# 담당 단계: RAG 검색 + Bedrock Claude 리포트 생성 → RDS 저장
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
from app.schemas.job import ReportJobMessage
from app.pipelines.report_pipeline import run_bedrock_report_stage
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.storage.rds import get_be_engine


def _load_embedding() -> KUREEmbeddingWrapper:
    embedding = KUREEmbeddingWrapper(settings.embedding_model_name)
    embedding.load()
    logger.info("KURE embedding 로드 완료")
    return embedding


def start_worker() -> None:
    initialize_observability()
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    embedding = _load_embedding()
    logger.info(f"LLM GPU Worker 시작. 큐: {settings.sqs_report_analysis_queue_url}")

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
            logger.error(f"[llm-gpu-worker] SQS receive_message 실패: {e}")
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
            with tracer.start_as_current_span("worker.report.message", context=message_context):
                record_sqs_receive("llm-gpu-worker")
                msg = ReportJobMessage(**body)

                async def _run():
                    async with AsyncSession(get_be_engine()) as be_session:
                        # retriever 파라미터는 run_bedrock_report_stage 내부에서 사용되지 않는다.
                        # embedding_model 키워드 인자로 직접 전달해야 retrieve_evidence가 올바른 모델을 쓴다.
                        await run_bedrock_report_stage(
                            msg, None, be_session, embedding_model=embedding
                        )

                asyncio.run(_run())
                sqs.delete_message(
                    QueueUrl=settings.sqs_report_analysis_queue_url,
                    ReceiptHandle=receipt_handle,
                )
                logger.info(f"REPORT STAGE 완료: job_id={body.get('job_id')}")
        except Exception as e:
            record_stage_failure("llm-gpu-worker", "message")
            logger.error(f"REPORT STAGE 실패: {e}")


if __name__ == "__main__":
    start_worker()