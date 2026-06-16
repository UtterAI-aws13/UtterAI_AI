"""
RAG 문서 인제스트 스크립트.

APP_ENV=local  : docs/ 파일을 직접 pgvector에 인제스트
APP_ENV=dev|prod: docs/ 파일을 S3 업로드 후 SQS 메시지 발행 → rag_ingest_worker가 처리

스캔 대상:
  docs/rag/    - 임상 가이드 txt (source_type=clinical_guide)
  docs/papers/ - 학술 논문 pdf  (source_type=research_paper)

파일명 규칙: <document_id>__<title>.<ext>
  예) doc_mlu_guide__MLU_해석_가이드.txt
  규칙을 따르지 않으면 파일명 기반으로 자동 생성
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.config import settings

ROOT = Path(__file__).parent.parent

SCAN_TARGETS = [
    (ROOT / "docs" / "rag",    "clinical_guide",  ("*.txt",)),
    (ROOT / "docs" / "papers", "research_paper",  ("*.pdf",)),
]

S3_PREFIX = "documents"


def _parse_filename(stem: str) -> tuple[str, str]:
    if "__" in stem:
        doc_id, title = stem.split("__", 1)
        return doc_id, title.replace("_", " ")
    return stem.replace(" ", "_").lower(), stem


def scan_docs():
    from app.schemas.rag import ChunkMetadata
    docs = []
    for directory, source_type, patterns in SCAN_TARGETS:
        if not directory.exists():
            continue
        for pattern in patterns:
            for path in sorted(directory.glob(pattern)):
                doc_id, title = _parse_filename(path.stem)
                docs.append((path, source_type, ChunkMetadata(
                    document_id=doc_id,
                    chunk_id="",
                    title=title,
                    source_type=source_type,
                    age_group="all",
                    metric=[],
                )))
    return docs


async def _already_ingested_local(document_id: str) -> bool:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.storage.db import get_engine

    async with AsyncSession(get_engine()) as session:
        result = await session.execute(
            text("SELECT 1 FROM rag_chunks WHERE document_id = :doc_id LIMIT 1"),
            {"doc_id": document_id},
        )
        return result.fetchone() is not None


def _already_uploaded_s3(s3_client, bucket: str, key: str) -> bool:
    from botocore.exceptions import ClientError
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


async def ingest_local(docs):
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.embedding_kure import KUREEmbeddingWrapper
    from app.rag.vector_store import VectorStore
    from app.rag.ingest import ingest_document
    from app.storage.db import get_engine

    new_docs = []
    for item in docs:
        path, _, metadata = item
        if await _already_ingested_local(metadata.document_id):
            print(f"[SKIP] 이미 인제스트됨: {metadata.document_id}")
        else:
            new_docs.append(item)

    if not new_docs:
        print("새로 인제스트할 문서가 없습니다.")
        return

    embedding_model = KUREEmbeddingWrapper(model_name=settings.embedding_model_name)
    embedding_model.load()
    print(f"임베딩 모델 로드 완료 ({len(new_docs)}개 문서 대상)")

    async with AsyncSession(get_engine()) as session:
        vector_store = VectorStore(session)
        for path, _, metadata in new_docs:
            count = await ingest_document(str(path), metadata, embedding_model, vector_store)
            print(f"[DONE] {metadata.document_id} ({path.name}): {count}개 청크")

    print("\n전체 ingestion 완료")


def ingest_remote(docs, force: bool = False):
    import boto3

    s3 = boto3.client("s3", region_name=settings.aws_region)
    sqs = boto3.client("sqs", region_name=settings.aws_region)

    bucket = settings.s3_bucket_rag
    queue_url = settings.sqs_rag_ingest_queue_url

    if not queue_url:
        print("[ERROR] SQS_RAG_INGEST_QUEUE_URL이 설정되지 않았습니다.")
        sys.exit(1)

    new_count = 0
    for path, _, metadata in docs:
        s3_key = f"{S3_PREFIX}/{path.name}"
        already_exists = _already_uploaded_s3(s3, bucket, s3_key)

        if already_exists and not force:
            print(f"[SKIP] 이미 S3에 존재함: {s3_key}")
            continue

        if not already_exists:
            print(f"[UPLOAD] {path.name} → s3://{bucket}/{s3_key}")
            s3.upload_file(str(path), bucket, s3_key)

        message = {
            "bucket": bucket,
            "key": s3_key,
            "metadata": {
                "document_id": metadata.document_id,
                "chunk_id": "",
                "title": metadata.title,
                "source_type": metadata.source_type,
                "age_group": metadata.age_group or "all",
                "metric": metadata.metric or [],
            },
        }
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message, ensure_ascii=False))
        print(f"[SQS] 메시지 발행 완료: {metadata.document_id}")
        new_count += 1

    if new_count == 0:
        print("새로 처리할 문서가 없습니다. --force 옵션으로 SQS 재발행할 수 있습니다.")
    else:
        print(f"\n총 {new_count}개 문서 처리 완료")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="S3에 이미 있어도 SQS 재발행")
    args = parser.parse_args()

    docs = scan_docs()
    if not docs:
        print("인제스트할 문서가 없습니다. docs/rag/ 또는 docs/papers/ 에 파일을 추가하세요.")
        return

    if settings.app_env == "local":
        await ingest_local(docs)
    else:
        ingest_remote(docs, force=args.force)


if __name__ == "__main__":
    asyncio.run(main())