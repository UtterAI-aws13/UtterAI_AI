# RAG 문서 수집 파이프라인 진입점
# 파일(TXT/PDF) → 텍스트 추출 → 청크 분할 → KURE-v1 임베딩 → pgvector 저장
#
# PDF 추출 우선순위: pymupdf(수식/레이아웃 보존) → pdfplumber(폴백)
import uuid
from pathlib import Path

from app.schemas import ChunkMetadata
from app.rag import chunker
from app.rag.vector_store import VectorStore
from app.models.embedding_kure import KUREEmbeddingWrapper


def _extract_text_pdf(file_path: str) -> str:
    try:
        import fitz  # pymupdf
        doc = fitz.open(file_path)
        pages = [page.get_text("text") for page in doc]
        doc.close()
        return "\n".join(pages)
    except ImportError:
        pass

    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        pass

    raise ImportError("PDF 파싱에 pymupdf 또는 pdfplumber가 필요합니다: uv add pymupdf")


def _extract_text(file_path: str) -> str:
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8")

    if suffix == ".pdf":
        return _extract_text_pdf(file_path)

    raise ValueError(f"지원하지 않는 파일 형식: {suffix} (지원: .txt, .pdf)")


async def ingest_document(
    file_path: str,
    metadata: ChunkMetadata,
    embedding_model: KUREEmbeddingWrapper,
    vector_store: VectorStore,
    chunk_size: int = 300,
    overlap: int = 50,
) -> int:
    """단일 문서를 읽어 청크로 분할하고 pgvector에 저장한다.

    Returns:
        저장된 청크 수
    """
    text = _extract_text(file_path)
    if not text.strip():
        return 0

    document_id = metadata.document_id or str(uuid.uuid4())
    metadata = metadata.model_copy(update={"document_id": document_id})

    chunks = chunker.make_chunks(document_id, text, metadata, chunk_size, overlap)
    if not chunks:
        return 0

    texts = [c.content for c in chunks]
    embeddings = embedding_model.predict(texts)
    await vector_store.upsert(chunks, embeddings)

    return len(chunks)
