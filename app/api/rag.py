# RAG API
# POST /ai/rag/query  - 언어발달/치료 문서에서 관련 근거를 검색 (개발/테스트 용도)
# POST /ai/rag/ingest - 새 문서를 RAG 파이프라인에 등록 (청크 + 임베딩 + pgvector 저장)
import json

import boto3
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas import RagQuery, RagResult, ChunkMetadata
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.rag.vector_store import VectorStore
from app.rag.retriever import Retriever
from app.storage.db import get_session

router = APIRouter()

_embedding: KUREEmbeddingWrapper | None = None
_sqs = None


def _get_embedding() -> KUREEmbeddingWrapper:
    global _embedding
    if _embedding is None:
        _embedding = KUREEmbeddingWrapper(settings.embedding_model_name)
        _embedding.load()
    return _embedding


def _get_sqs():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=settings.aws_region)
    return _sqs


class IngestRequest(BaseModel):
    """RAG 문서 ingest 요청. S3 위치와 청크에 부착할 메타데이터를 전달한다."""
    bucket: str | None = None  # None이면 settings.s3_bucket_rag 사용
    key: str                   # S3 오브젝트 키 (문서 경로)
    metadata: ChunkMetadata


@router.post("/query", response_model=RagResult)
async def query_rag(
    request: RagQuery,
    session: AsyncSession = Depends(get_session),
):
    """질문을 받아 ontology 확장 → KURE-v1 임베딩 → pgvector 검색 순으로 근거를 반환한다."""
    embedding = _get_embedding()
    vector_store = VectorStore(session)
    retriever = Retriever(
        vector_store, embedding,
        settings.rag_top_k, settings.rag_score_threshold,
    )
    return await retriever.retrieve(request)


@router.post("/ingest")
async def ingest_documents(request: IngestRequest):
    """문서 ingest 작업을 SQS에 발행한다. 실제 처리는 rag_ingest_worker가 담당한다."""
    message = {
        "bucket": request.bucket or settings.s3_bucket_rag,
        "key": request.key,
        "metadata": request.metadata.model_dump(),
    }
    _get_sqs().send_message(
        QueueUrl=settings.sqs_rag_ingest_queue_url,
        MessageBody=json.dumps(message),
    )
    return {"status": "accepted", "key": request.key}
