# RAG 문서 ingest Worker
# SQS에서 ingest 요청 메시지를 수신해 문서를 chunk → embedding → pgvector 저장한다
# 분석 Worker와 별도로 운영해 RAG 문서 업데이트가 분석 파이프라인에 영향을 주지 않게 한다
import asyncio
import json
import tempfile
from pathlib import Path

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
from app.schemas import ChunkMetadata
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.rag.vector_store import VectorStore
from app.rag.ingest import ingest_document
from app.storage import s3_client
from app.storage.db import get_engine

_runtime = Lifecycle()
_visibility_client = None


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

    embedding = KUREEmbeddingWrapper(settings.embedding_model_name)
    embedding.load()
    _runtime.mark_ready()
    logger.info("KURE embedding 로드 완료")

    logger.info(f"Ingest Worker 시작. 큐: {settings.sqs_rag_ingest_queue_url}")

    while not _runtime.stop.is_set():
        response = sqs.receive_message(
            QueueUrl=settings.sqs_rag_ingest_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=VISIBILITY_SECONDS,
            MessageAttributeNames=["All"],
        )

        messages = response.get("Messages", [])
        if not messages:
            continue

        raw = messages[0]
        receipt_handle = raw["ReceiptHandle"]
        if not _runtime.accept(sqs, settings.sqs_rag_ingest_queue_url, receipt_handle):
            continue
        handle = start_heartbeat(
            _visibility_client, settings.sqs_rag_ingest_queue_url, receipt_handle
        )
        try:
            body = json.loads(raw["Body"])
            message_context = extract_context_from_message_attributes(raw.get("MessageAttributes"))
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("worker.rag.message", context=message_context):
                record_sqs_receive("rag-ingest-worker")
                asyncio.run(_handle_ingest_async(body, embedding))
                stop_heartbeat(handle)
                sqs.delete_message(
                    QueueUrl=settings.sqs_rag_ingest_queue_url,
                    ReceiptHandle=receipt_handle,
                )
        except Exception as e:
            record_stage_failure("rag-ingest-worker", "message")
            logger.error(f"[ingest] 처리 실패: {e}")
        finally:
            stop_heartbeat(handle)
            _runtime.finish()


if __name__ == "__main__":
    start_worker()
