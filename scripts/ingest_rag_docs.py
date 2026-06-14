"""
로컬 RAG 문서 인제스트 스크립트.
dev/prod 환경에서는 rag_ingest_worker(SQS → S3)를 사용한다.

스캔 대상:
  docs/rag/    - 임상 가이드 txt (source_type=clinical_guide)
  docs/papers/ - 학술 논문 pdf  (source_type=research_paper)

파일명 규칙: <document_id>__<title>.<ext>
  예) doc_mlu_guide__MLU_해석_가이드.txt
  규칙을 따르지 않으면 파일명 기반으로 자동 생성
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.rag.vector_store import VectorStore
from app.schemas.rag import ChunkMetadata
from app.rag.ingest import ingest_document
from app.storage.db import get_engine

ROOT = Path(__file__).parent.parent

SCAN_TARGETS = [
    (ROOT / "docs" / "rag",    "clinical_guide",  ("*.txt",)),
    (ROOT / "docs" / "papers", "research_paper",  ("*.pdf",)),
]


def _parse_filename(stem: str) -> tuple[str, str]:
    if "__" in stem:
        doc_id, title = stem.split("__", 1)
        return doc_id, title.replace("_", " ")
    return stem.replace(" ", "_").lower(), stem


def scan_docs() -> list[tuple[Path, ChunkMetadata]]:
    docs = []
    for directory, source_type, patterns in SCAN_TARGETS:
        if not directory.exists():
            continue
        for pattern in patterns:
            for path in sorted(directory.glob(pattern)):
                doc_id, title = _parse_filename(path.stem)
                docs.append((path, ChunkMetadata(
                    document_id=doc_id,
                    chunk_id="",
                    title=title,
                    source_type=source_type,
                    age_group="all",
                    metric=[],
                )))
    return docs


async def main():
    docs = scan_docs()
    if not docs:
        print("인제스트할 문서가 없습니다. docs/rag/ 또는 docs/papers/ 에 파일을 추가하세요.")
        return

    embedding_model = KUREEmbeddingWrapper(model_name="nlpai-lab/KURE-v1")
    embedding_model.load()
    print(f"임베딩 모델 로드 완료 ({len(docs)}개 문서 대상)")

    async with AsyncSession(get_engine()) as session:
        vector_store = VectorStore(session)
        for path, metadata in docs:
            count = await ingest_document(str(path), metadata, embedding_model, vector_store)
            print(f"[DONE] {metadata.document_id} ({path.name}): {count}개 청크")

    print("\n전체 ingestion 완료")


if __name__ == "__main__":
    asyncio.run(main())
