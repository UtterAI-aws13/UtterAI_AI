# RAG 문서 ingest Worker
# SQS에서 ingest 요청 메시지를 수신해 문서를 chunk → embedding → pgvector 저장한다
# 분석 Worker와 별도로 운영해 RAG 문서 업데이트가 분석 파이프라인에 영향을 주지 않게 한다
import asyncio
import json
import tempfile
from pathlib import Path

import boto3
from loguru import logger
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.observability.otel import initialize_observability
from app.observability.metrics import record_sqs_receive
from app.observability.metrics import record_stage_failure
from app.observability.sqs import extract_context_from_message_attributes
from app.schemas import ChunkMetadata
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.rag.vector_store import VectorStore
from app.rag.ingest import ingest_document
from app.storage import s3_client
from app.storage.db import get_engine


async def _handle_ingest_async(message: dict, embedding: KUREEmbeddingWrapper) -> None:
    """ingest 메시지를 받아 문서 처리 파이프라인을 실행한다.

    메시지 필수 필드:
      bucket, key: S3 문서 위치
      metadata: ChunkMetadata 직렬화 dict
    """
    bucket: str = message["bucket"]
    key: str = message["key"]
    metadata = ChunkMetadata(**message["metadata"])

    with tempfile.TemporaryDirectory() as tmp_dir:
        suffix = Path(key).suffix
        local_path = str(Path(tmp_dir) / f"{metadata.document_id}{suffix}")
        logger.info(f"[ingest] 다운로드: s3://{bucket}/{key}")
        s3_client.download(bucket, key, local_path)

        async with AsyncSession(get_engine()) as session:
            vector_store = VectorStore(session)
            count = await ingest_document(local_path, metadata, embedding, vector_store)

    logger.info(f"[ingest] 완료: {count}개 청크 저장 ({key})")


def start_worker() -> None:
    """SQS 큐를 폴링하며 ingest 메시지를 처리하는 루프."""
    initialize_observability()
    sqs = boto3.client("sqs", region_name=settings.aws_region)

    embedding = KUREEmbeddingWrapper(settings.embedding_model_name)
    embedding.load()
    logger.info("KURE embedding 로드 완료")

    logger.info(f"Ingest Worker 시작. 큐: {settings.sqs_rag_ingest_queue_url}")

    while True:
        response = sqs.receive_message(
            QueueUrl=settings.sqs_rag_ingest_queue_url,
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
            with tracer.start_as_current_span("worker.rag.message", context=message_context):
                record_sqs_receive("rag-ingest-worker")
                asyncio.run(_handle_ingest_async(body, embedding))
                sqs.delete_message(
                    QueueUrl=settings.sqs_rag_ingest_queue_url,
                    ReceiptHandle=receipt_handle,
                )
        except Exception as e:
            record_stage_failure("rag-ingest-worker", "message")
            logger.error(f"[ingest] 처리 실패: {e}")


if __name__ == "__main__":
    start_worker()
