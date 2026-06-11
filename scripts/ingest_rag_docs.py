"""
RAG 문서를 pgvector에 ingestion하는 스크립트.
로컬에서 한 번 실행하면 pgvector에 문서가 저장된다.
문서가 바뀌면 다시 실행한다.
"""
import asyncio
import re
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.rag.vector_store import VectorStore
from app.schemas.rag import RagChunk, ChunkMetadata
from app.storage.db import get_engine

DOCUMENTS = [
    {
        "path": "docs/rag/mlu_interpretation_guide.txt",
        "document_id": "doc_mlu_guide",
        "title": "MLU 해석 가이드",
        "source_type": "clinical_guide",
        "age_group": "preschool",
        "metric": ["mlu_morpheme"],
    },
    {
        "path": "docs/rag/ttr_ndw_interpretation.txt",
        "document_id": "doc_ttr_ndw",
        "title": "TTR NDW 해석 가이드",
        "source_type": "clinical_guide",
        "age_group": "preschool",
        "metric": ["ttr", "ndw", "ntw"],
    },
    {
        "path": "docs/rag/response_latency_guide.txt",
        "document_id": "doc_latency",
        "title": "반응 지연 시간 해석 가이드",
        "source_type": "clinical_guide",
        "age_group": "preschool",
        "metric": ["average_response_latency_sec"],
    },
    {
        "path": "docs/rag/soap_note_template.txt",
        "document_id": "doc_soap_template",
        "title": "SOAP Note 작성 가이드",
        "source_type": "report_template",
        "age_group": "all",
        "metric": [],
    },
]


def chunk_document(text: str, doc_info: dict, max_chars: int = 600, overlap: int = 80) -> list[RagChunk]:
    sections = re.split(r"\n(?=#{1,3} )", text.strip())
    chunks = []
    idx = 0

    for section in sections:
        section = section.strip()
        if not section:
            continue

        def _make_chunk(content: str) -> RagChunk:
            nonlocal idx
            chunk_id = f"{doc_info['document_id']}_chunk_{idx:04d}"
            idx += 1
            return RagChunk(
                chunk_id=chunk_id,
                document_id=doc_info["document_id"],
                content=content,
                metadata=ChunkMetadata(
                    document_id=doc_info["document_id"],
                    chunk_id=chunk_id,
                    title=doc_info["title"],
                    source_type=doc_info["source_type"],
                    age_group=doc_info.get("age_group"),
                    metric=doc_info.get("metric", []),
                ),
            )

        if len(section) <= max_chars:
            chunks.append(_make_chunk(section))
        else:
            start = 0
            while start < len(section):
                end = min(start + max_chars, len(section))
                chunks.append(_make_chunk(section[start:end]))
                start = end - overlap

    return chunks


async def main():
    embedding_model = KUREEmbeddingWrapper(model_name="nlpai-lab/KURE-v1")
    embedding_model.load()
    print("임베딩 모델 로드 완료")

    async with AsyncSession(get_engine()) as session:
        vector_store = VectorStore(session)

        for doc_info in DOCUMENTS:
            path = Path(doc_info["path"])
            if not path.exists():
                print(f"[SKIP] 파일 없음: {path}")
                continue

            text = path.read_text(encoding="utf-8")
            chunks = chunk_document(text, doc_info)
            print(f"[INGEST] {doc_info['title']}: {len(chunks)}개 청크")

            embeddings = embedding_model.predict([c.content for c in chunks])
            await vector_store.upsert(chunks, embeddings)
            print(f"[DONE] {doc_info['document_id']}")

    print("\n전체 ingestion 완료")


if __name__ == "__main__":
    asyncio.run(main())
