# Evidence Research Agent tool. 전부 read-only, 논문/가이드 corpus만 검색한다
# (환자 데이터는 검색하지 않는다 — §9.6).
#
# 기존 KURE-v1 + pgvector 검색 인프라(app.rag.retriever/vector_store/semantic_layer)를
# 그대로 재사용한다. hybrid_search/rerank_evidence는 이 프로젝트에 아직 별도의
# BM25/reranker 모델이 없어(app.config.settings.rag_rerank_enabled=False) 키워드
# 중첩도 기반 휴리스틱으로 구현했다 — 실제 reranker 모델 도입 시 교체 대상이다.
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

from loguru import logger
from strands.tools import tool


def _run_async_in_thread(coro) -> Any:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


def _to_evidence_dict(e) -> dict:
    return {
        "evidence_id": f"{e.document_id}:{e.chunk_id}",
        "source_id": e.document_id,
        "chunk_id": e.chunk_id,
        "source_type": e.source_type,
        "title": e.title,
        "publication_year": (e.metadata or {}).get("publication_year"),
        "population": (e.metadata or {}).get("age_group") and [(e.metadata or {}).get("age_group")] or [],
        "metrics": (e.metadata or {}).get("metric", []),
        "language_areas": (e.metadata or {}).get("language_area", []),
        "text": e.text,
        "retrieval_score": e.score,
        "rerank_score": None,
    }


async def _search(query: str, top_k: int) -> list[dict]:
    from app.rag.retriever import retrieve_evidence

    results = await retrieve_evidence(metrics={}, session={}, top_k=top_k, direct_query=query)
    # retrieve_evidence()는 Bedrock 파이프라인용 dict를 반환한다 (retriever.py 참고).
    # EvidenceChunk 스키마 필드명에 맞춰 변환한다.
    return [
        {
            "evidence_id": f"{r['document_id']}:{r['chunk_id']}",
            "source_id": r["document_id"],
            "chunk_id": r["chunk_id"],
            "source_type": "",
            "title": r["title"],
            "publication_year": None,
            "population": [],
            "metrics": [],
            "language_areas": [],
            "text": r["content"],
            "retrieval_score": r["score"],
            "rerank_score": None,
        }
        for r in results
    ]


@tool
def search_korean_evidence(query_ko: str, top_k: int = 10) -> list[dict]:
    """국내 언어재활 논문/자료를 한국어 쿼리로 검색한다.

    query_ko: 한국어 자연어 쿼리.
    """
    try:
        return _run_async_in_thread(_search(query_ko, top_k))
    except Exception as exc:
        logger.warning(f"[evidence_research_tool] search_korean_evidence 실패: {exc}")
        return []


@tool
def search_international_evidence(query_en: str, top_k: int = 10) -> list[dict]:
    """해외 언어재활 논문을 검색한다.

    주의: 현재 임베딩 모델(KURE-v1)은 한국어 특화 모델이라 별도의 해외 문헌
    전용 인덱스가 없다 — search_korean_evidence와 동일한 corpus를 검색한다.
    다국어/영어 임베딩 파이프라인이 추가되면 이 tool을 교체해야 한다.

    query_en: 영어 자연어 쿼리.
    """
    try:
        return _run_async_in_thread(_search(query_en, top_k))
    except Exception as exc:
        logger.warning(f"[evidence_research_tool] search_international_evidence 실패: {exc}")
        return []


@tool
def search_clinical_guidelines(query: str, top_k: int = 10) -> list[dict]:
    """임상 가이드(source_type=clinical_guide) 문서만 검색한다.

    query: 한국어 자연어 쿼리.
    """
    try:
        candidates = _run_async_in_thread(_search(query, top_k * 3))
    except Exception as exc:
        logger.warning(f"[evidence_research_tool] search_clinical_guidelines 실패: {exc}")
        return []

    async def _filter_by_source_type():
        from sqlalchemy import select

        from app.rag.vector_store import RagChunkORM
        from app.storage.db import get_engine
        from sqlalchemy.ext.asyncio import AsyncSession

        chunk_ids = [c["chunk_id"] for c in candidates]
        if not chunk_ids:
            return set()
        async with AsyncSession(get_engine()) as db:
            rows = await db.execute(
                select(RagChunkORM.chunk_id, RagChunkORM.metadata_json).where(
                    RagChunkORM.chunk_id.in_(chunk_ids)
                )
            )
            return {
                chunk_id
                for chunk_id, meta in rows
                if (meta or {}).get("source_type") == "clinical_guide"
            }

    try:
        guide_chunk_ids = _run_async_in_thread(_filter_by_source_type())
    except Exception as exc:
        logger.warning(f"[evidence_research_tool] source_type 필터링 실패: {exc}")
        return candidates[:top_k]

    filtered = [c for c in candidates if c["chunk_id"] in guide_chunk_ids]
    return filtered[:top_k]


@tool
def hybrid_search(query: str, top_k: int = 10) -> list[dict]:
    """벡터 검색 + ontology 기반 키워드 확장을 결합한 검색.

    query: 한국어 자연어 쿼리.
    """
    from app.rag.semantic_layer import expand_query, get_metadata_filters

    async def _hybrid():
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.embedding_kure import KUREEmbeddingWrapper
        from app.rag.retriever import _get_embedding_model
        from app.rag.vector_store import VectorStore
        from app.storage.db import get_engine

        keywords = query.split()
        expanded = expand_query(keywords)
        filters = get_metadata_filters(keywords)
        query_text = query + " " + " ".join(expanded)

        model: KUREEmbeddingWrapper = _get_embedding_model()
        embedding = model.predict([query_text])[0]

        async with AsyncSession(get_engine()) as db:
            store = VectorStore(db)
            evidence = await store.search(embedding, filters, top_k, score_threshold=0.0)
        return [_to_evidence_dict(e) for e in evidence]

    try:
        return _run_async_in_thread(_hybrid())
    except Exception as exc:
        logger.warning(f"[evidence_research_tool] hybrid_search 실패: {exc}")
        return []


@tool
def rerank_evidence(candidates: list[dict], query: str) -> list[dict]:
    """검색 후보를 query와의 키워드 중첩도로 재정렬한다.

    실제 cross-encoder reranker 모델이 아직 없어(rag_rerank_enabled=False),
    retrieval_score와 키워드 중첩 비율을 가중합한 임시 rerank_score를 사용한다.

    candidates: search_* tool이 반환한 근거 목록.
    query: 원 쿼리 텍스트.
    """
    query_tokens = set(query.split())
    reranked = []
    for c in candidates:
        text_tokens = set(str(c.get("text", "")).split())
        overlap = len(query_tokens & text_tokens) / len(query_tokens) if query_tokens else 0.0
        retrieval_score = float(c.get("retrieval_score") or 0.0)
        rerank_score = round(0.7 * retrieval_score + 0.3 * overlap, 4)
        reranked.append({**c, "rerank_score": rerank_score})
    reranked.sort(key=lambda c: c["rerank_score"], reverse=True)
    return reranked


@tool
def fetch_document_section(chunk_id: str) -> dict:
    """chunk_id로 원문 청크 전체를 조회한다 (인용 범위 확인용).

    chunk_id: search_* tool이 반환한 chunk_id.
    """

    async def _fetch():
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.rag.vector_store import RagChunkORM
        from app.storage.db import get_engine

        async with AsyncSession(get_engine()) as db:
            row = await db.execute(
                select(RagChunkORM).where(RagChunkORM.chunk_id == chunk_id)
            )
            chunk = row.scalar_one_or_none()
            if chunk is None:
                return None
            return {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "text": chunk.content,
                "metadata": chunk.metadata_json or {},
            }

    try:
        result = _run_async_in_thread(_fetch())
    except Exception as exc:
        logger.warning(f"[evidence_research_tool] fetch_document_section 실패: {exc}")
        return {"error": str(exc)}

    if result is None:
        return {"error": f"chunk_id {chunk_id}를 찾을 수 없습니다."}
    return result


@tool
def resolve_ontology_synonyms(term: str) -> list[str]:
    """ontology.yaml 기반으로 term과 연관된 동의어/관련어를 확장한다.

    term: 확장할 임상 개념 또는 지표명. 예: 'MLU', '음운 인식'.
    """
    from app.rag.semantic_layer import expand_query

    try:
        return expand_query([term])
    except Exception as exc:
        logger.warning(f"[evidence_research_tool] resolve_ontology_synonyms 실패: {exc}")
        return [term]
