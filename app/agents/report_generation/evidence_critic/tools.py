# Evidence Critic Agent tool. 검색 tool은 기본적으로 허용하지 않는다 (§10.2) —
# fetch_document_section만 evidence_research와 공유하고, 나머지는 순수 로직이다.
from strands.tools import tool

from app.agents.report_generation.evidence_research.tools import fetch_document_section

__all__ = ["fetch_document_section", "verify_source_metadata", "deduplicate_sources"]


@tool
def verify_source_metadata(evidence: dict) -> dict:
    """근거 chunk의 metadata가 인용 가능한 최소 요건을 갖췄는지 확인한다.

    evidence: EvidenceChunk 형태의 dict (evidence_id, source_id, chunk_id, title, text 등).
    """
    missing = [
        field
        for field in ("source_id", "chunk_id", "title", "text")
        if not evidence.get(field)
    ]
    return {
        "evidence_id": evidence.get("evidence_id"),
        "has_required_fields": len(missing) == 0,
        "missing_fields": missing,
    }


@tool
def deduplicate_sources(candidates: list[dict]) -> list[dict]:
    """같은 source_id의 유사 chunk가 과도하게 중복되지 않도록, source_id당 상위
    2개 chunk만 남긴다 (retrieval_score/rerank_score 기준 정렬).

    candidates: search_* / rerank_evidence tool이 반환한 근거 목록.
    """
    by_source: dict[str, list[dict]] = {}
    for c in candidates:
        by_source.setdefault(c.get("source_id", ""), []).append(c)

    deduped: list[dict] = []
    for _source_id, chunks in by_source.items():
        chunks.sort(
            key=lambda c: c.get("rerank_score") or c.get("retrieval_score") or 0.0,
            reverse=True,
        )
        deduped.extend(chunks[:2])
    return deduped
