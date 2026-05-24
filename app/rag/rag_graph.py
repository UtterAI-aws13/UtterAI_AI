# LangGraph 기반 RAG 쿼리 파이프라인
#
# 흐름:
#   extract_keywords → expand_query → retrieve
#     → (근거 충분) → finalize → END
#     → (근거 부족) → fallback_retrieve → finalize → END
#
# fallback_retrieve는 메타데이터 필터를 제거하고 검색 범위를 넓혀 재시도한다.
# retry_count >= 1 이후에는 결과 품질과 무관하게 finalize로 강제 진행한다.
from __future__ import annotations

from typing import TypedDict, Literal

from langgraph.graph import StateGraph, END

from app.schemas import RagResult, RagEvidence
from app.rag.semantic_layer import expand_query, get_metadata_filters
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.rag.vector_store import VectorStore

_kiwi = None


def _get_kiwi():
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi


def _extract_kiwi_keywords(text: str) -> list[str]:
    try:
        kiwi = _get_kiwi()
        tokens = kiwi.tokenize(text)
        pos_filter = {"NNG", "NNP", "VV", "VA"}
        return list({t.form for t in tokens if t.tag in pos_filter})
    except Exception:
        return text.split()


class RagState(TypedDict):
    question: str
    kiwi_keywords: list[str]
    expanded_keywords: list[str]
    filters: dict
    evidence: list[RagEvidence]
    retry_count: int
    rag_result: RagResult | None


def build_rag_graph(
    embedding_model: KUREEmbeddingWrapper,
    vector_store: VectorStore,
    top_k: int = 5,
    score_threshold: float = 0.5,
):
    """의존성을 주입받아 컴파일된 LangGraph RAG 그래프를 반환한다."""

    def node_extract_keywords(state: RagState) -> RagState:
        keywords = _extract_kiwi_keywords(state["question"])
        return {**state, "kiwi_keywords": keywords}

    def node_expand_query(state: RagState) -> RagState:
        expanded = expand_query(state["kiwi_keywords"])
        filters = get_metadata_filters(state["kiwi_keywords"])
        # 호출자가 전달한 명시적 필터와 병합
        merged_filters = {**filters, **state.get("filters", {})}
        return {**state, "expanded_keywords": expanded, "filters": merged_filters}

    async def node_retrieve(state: RagState) -> RagState:
        query_text = state["question"] + " " + " ".join(state["expanded_keywords"])
        embedding = embedding_model.predict([query_text])[0]
        evidence = await vector_store.search(
            embedding, state["filters"], top_k, score_threshold=0.0
        )
        return {**state, "evidence": evidence}

    async def node_fallback_retrieve(state: RagState) -> RagState:
        """필터를 제거하고 검색 범위를 넓혀 재시도한다."""
        query_text = state["question"] + " " + " ".join(state["expanded_keywords"])
        embedding = embedding_model.predict([query_text])[0]
        evidence = await vector_store.search(
            embedding, {}, top_k * 2, score_threshold=0.0
        )
        return {**state, "evidence": evidence, "retry_count": state.get("retry_count", 0) + 1}

    def node_finalize(state: RagState) -> RagState:
        good = [e for e in state["evidence"] if e.score >= score_threshold]
        rag_result = RagResult(
            query=state["question"],
            expanded_query=state["expanded_keywords"],
            evidence=good,
        )
        return {**state, "rag_result": rag_result}

    def route_evidence(state: RagState) -> Literal["fallback", "done"]:
        good = [e for e in state["evidence"] if e.score >= score_threshold]
        if len(good) >= 2 or state.get("retry_count", 0) >= 1:
            return "done"
        return "fallback"

    graph = StateGraph(RagState)
    graph.add_node("extract_keywords", node_extract_keywords)
    graph.add_node("expand_query", node_expand_query)
    graph.add_node("retrieve", node_retrieve)
    graph.add_node("fallback_retrieve", node_fallback_retrieve)
    graph.add_node("finalize", node_finalize)

    graph.set_entry_point("extract_keywords")
    graph.add_edge("extract_keywords", "expand_query")
    graph.add_edge("expand_query", "retrieve")
    graph.add_conditional_edges("retrieve", route_evidence, {
        "done": "finalize",
        "fallback": "fallback_retrieve",
    })
    graph.add_conditional_edges("fallback_retrieve", route_evidence, {
        "done": "finalize",
        "fallback": "finalize",  # 1회 재시도 후 강제 종료
    })
    graph.add_edge("finalize", END)

    return graph.compile()
