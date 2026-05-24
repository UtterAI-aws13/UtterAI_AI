# RAG 검색기
# LangGraph 기반 rag_graph를 래핑해 외부에서 단일 메서드로 호출할 수 있게 한다
from app.schemas import RagQuery, RagResult
from app.rag.rag_graph import build_rag_graph, RagState
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.rag.vector_store import VectorStore


class Retriever:
    def __init__(
        self,
        vector_store: VectorStore,
        embedding_model: KUREEmbeddingWrapper,
        top_k: int = 5,
        score_threshold: float = 0.5,
    ):
        self._graph = build_rag_graph(embedding_model, vector_store, top_k, score_threshold)

    async def retrieve(self, query: RagQuery) -> RagResult:
        initial_state: RagState = {
            "question": query.question,
            "kiwi_keywords": [],
            "expanded_keywords": [],
            "filters": query.filters,
            "evidence": [],
            "retry_count": 0,
            "rag_result": None,
        }
        final_state = await self._graph.ainvoke(initial_state)
        return final_state["rag_result"]
