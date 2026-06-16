# RAG 검색기
# LangGraph 기반 rag_graph를 래핑해 외부에서 단일 메서드로 호출할 수 있게 한다
from app.schemas import RagQuery, RagResult
from app.rag.rag_graph import build_rag_graph, RagState
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.rag.vector_store import VectorStore
from app.storage.db import get_engine


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


_embedding_model = None


def _get_embedding_model() -> KUREEmbeddingWrapper:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = KUREEmbeddingWrapper(model_name="nlpai-lab/KURE-v1")
        _embedding_model.load()
    return _embedding_model


async def retrieve_evidence(
    metrics: dict,
    session: dict,
    top_k: int = 5,
    embedding_model: KUREEmbeddingWrapper | None = None,
) -> list[dict]:
    """Bedrock 파이프라인용 간편 검색 함수. RagEvidence 대신 dict 목록 반환."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.config import settings

    age_months = session.get("patient_age_months", 0)
    mlu = metrics.get("mlu_morpheme", 0)
    ttr = metrics.get("ttr", 0)
    ndw = metrics.get("ndw", 0)
    latency = metrics.get("avg_response_latency_sec", 0)

    question = (
        f"만 {age_months // 12}세 아동 언어치료 세션. "
        f"MLU {mlu:.1f}, NDW {ndw}, TTR {ttr:.3f}, "
        f"평균 반응 지연 {latency:.2f}초. "
        f"이 지표를 SOAP Note에 어떻게 해석하고 기록해야 하는가?"
    )

    model = embedding_model if embedding_model is not None else _get_embedding_model()
    query_embedding = model.predict([question])[0]

    async with AsyncSession(get_engine()) as db_session:
        vector_store = VectorStore(db_session)
        results = await vector_store.search(
            embedding=query_embedding,
            filters={},
            top_k=top_k,
            score_threshold=settings.rag_score_threshold,
        )

    return [{"chunk_id": e.chunk_id, "title": e.title, "content": e.text, "score": e.score} for e in results]
