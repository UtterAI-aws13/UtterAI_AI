# 문서 텍스트를 청크로 분할하는 모듈
# 한국어 문장 단위로 분리 후 슬라이딩 윈도우 overlap을 적용해
# 청크 간 문맥이 끊기지 않도록 한다
import re
from app.schemas import RagChunk, ChunkMetadata

# 한국어/영어 문장 끝 문자 기준 분리
_SENTENCE_END_RE = re.compile(r'(?<=[.!?。？！])\s+')

# source_type별 기본 chunk 파라미터.
# 계산 규칙은 작게(정밀도), 논문은 크게(맥락 보존), safety_rule은 매우 작게(독립 저장).
_CHUNK_PARAMS: dict[str, tuple[int, int]] = {
    "scoring_rule":       (150, 30),
    "linguistic_rule":    (200, 40),
    "safety_rule":        (100, 20),
    "research_paper":     (500, 80),
    "research_abstract":  (300, 50),
    "clinical_guide":     (300, 50),
}
_DEFAULT_CHUNK_PARAMS = (300, 50)


def _chunk_params(source_type: str) -> tuple[int, int]:
    return _CHUNK_PARAMS.get(source_type, _DEFAULT_CHUNK_PARAMS)


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
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[RagChunk]:
    """텍스트를 청크로 분할한다.

    chunk_size/overlap을 명시하지 않으면 metadata.source_type 기준으로 자동 선택한다.
    """
    default_size, default_overlap = _chunk_params(metadata.source_type)
    chunk_size = chunk_size if chunk_size is not None else default_size
    overlap = overlap if overlap is not None else default_overlap

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
