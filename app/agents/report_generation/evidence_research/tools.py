# Evidence Research Agent tool. 전부 read-only, 논문/가이드 corpus만 검색한다
# (환자 데이터는 검색하지 않는다 — §9.6).
#
# 검색은 기존 app.rag.rag_graph의 LangGraph 파이프라인(Kiwi 형태소 분석 →
# ontology.yaml 동의어/관련어 확장 → language_area/metric 메타데이터 필터 →
# pgvector 검색 → 근거 부족 시 필터 없이 fallback 재검색)을 그대로 재사용한다
# (app.rag.retriever.Retriever가 이 파이프라인을 감싼 진입점이다).
#
# 주의: 이전에는 app.rag.retriever.retrieve_evidence()(Lambda/구 Bedrock
# 파이프라인용 단순 버전 - Kiwi/ontology/필터를 거치지 않고 raw 쿼리를 그대로
# 임베딩)를 잘못 재사용했었다. 이 파일은 그 문제를 고쳐 Retriever 파이프라인으로
# 통일한 버전이다.
#
# rerank_evidence는 이 프로젝트에 아직 별도의 cross-encoder reranker 모델이
# 없어(app.config.settings.rag_rerank_enabled=False) 키워드 중첩도 기반
# 휴리스틱으로 구현했다 — 실제 reranker 모델 도입 시 교체 대상이다.
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


async def _search(query: str, top_k: int, extra_filters: dict | None = None) -> list[dict]:
    """Kiwi → ontology 확장 → 메타데이터 필터 → pgvector → fallback 파이프라인 전체를 태운다."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.rag.retriever import Retriever, _get_embedding_model
    from app.rag.vector_store import VectorStore
    from app.schemas import RagQuery
    from app.storage.db import get_engine

    model = _get_embedding_model()
    async with AsyncSession(get_engine()) as db:
        vector_store = VectorStore(db)
        retriever = Retriever(vector_store, model, top_k=top_k, score_threshold=0.0)
        result = await retriever.retrieve(RagQuery(question=query, filters=extra_filters or {}))
    return [_to_evidence_dict(e) for e in result.evidence]


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
    """벡터 검색 + Kiwi 키워드 기반 ontology 확장/메타데이터 필터를 결합한 검색.

    search_korean_evidence와 동일한 Retriever 파이프라인을 사용한다 - 그
    파이프라인 자체가 이미 "키워드로 유도한 메타데이터 필터 + 벡터 검색"이라는
    의미의 hybrid 검색이다. 별도 BM25 lexical scoring은 아직 없다 - 도입되면
    이 tool에서 vector score와 결합하는 방식으로 확장한다.

    query: 한국어 자연어 쿼리.
    """
    try:
        return _run_async_in_thread(_search(query, top_k))
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
