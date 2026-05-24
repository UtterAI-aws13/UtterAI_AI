# 문서 텍스트를 청크로 분할하는 모듈
# 한국어 문장 단위로 분리 후 슬라이딩 윈도우 overlap을 적용해
# 청크 간 문맥이 끊기지 않도록 한다
import re
from app.schemas import RagChunk, ChunkMetadata

# 한국어/영어 문장 끝 문자 기준 분리
_SENTENCE_END_RE = re.compile(r'(?<=[.!?。？！])\s+')


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_END_RE.split(text.strip())
    # 개행 기준 추가 분리
    sentences = []
    for part in parts:
        sentences.extend(line.strip() for line in part.splitlines() if line.strip())
    return sentences


def make_chunks(
    document_id: str,
    text: str,
    metadata: ChunkMetadata,
    chunk_size: int = 300,
    overlap: int = 50,
) -> list[RagChunk]:
    """텍스트를 청크로 분할한다.

    chunk_size: 청크 최대 글자 수
    overlap: 앞 청크에서 다음 청크로 이어지는 글자 수 (문맥 보존)
    """
    sentences = _split_sentences(text)
    chunks: list[RagChunk] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence)

        if current_len + sentence_len > chunk_size and current:
            chunk_text = " ".join(current)
            chunks.append(_make_chunk(document_id, chunk_text, metadata, len(chunks)))

            # overlap: 뒤에서부터 overlap 글자 이내의 문장만 다음 청크로 넘긴다
            overlap_buf: list[str] = []
            overlap_chars = 0
            for s in reversed(current):
                if overlap_chars + len(s) > overlap:
                    break
                overlap_buf.insert(0, s)
                overlap_chars += len(s)

            current = overlap_buf
            current_len = overlap_chars

        current.append(sentence)
        current_len += sentence_len

    if current:
        chunks.append(_make_chunk(document_id, " ".join(current), metadata, len(chunks)))

    return chunks


def _make_chunk(document_id: str, text: str, metadata: ChunkMetadata, idx: int) -> RagChunk:
    chunk_id = f"{document_id}_chunk_{idx:04d}"
    meta = metadata.model_copy(update={"chunk_id": chunk_id})
    return RagChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        content=text,
        metadata=meta,
    )
