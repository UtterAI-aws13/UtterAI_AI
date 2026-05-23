# RAG 검색기
# 검색 흐름: Kiwi 키워드 → ontology 확장 → KURE-v1 임베딩 → pgvector 검색 → score 필터링
from app.schemas import RagQuery, RagResult
from app.rag.semantic_layer import expand_query, get_metadata_filters


class Retriever:
    """RAG 검색 파이프라인을 담당하는 클래스.

    vector_store: pgvector 검색 인터페이스
    embedding_model: KUREEmbeddingWrapper 인스턴스
    top_k: 검색 결과 상위 k개
    score_threshold: 이 점수 미만의 chunk는 근거에서 제외
    """
    def __init__(self, vector_store, embedding_model, top_k: int = 5, score_threshold: float = 0.5):
        self.vector_store = vector_store
        self.embedding_model = embedding_model
        self.top_k = top_k
        self.score_threshold = score_threshold

    def retrieve(self, query: RagQuery, kiwi_keywords: list[str]) -> RagResult:
        """질문과 Kiwi 키워드를 받아 관련 근거 chunk를 반환한다.

        1. ontology 기반 키워드 확장 및 메타데이터 필터 생성
        2. 확장된 쿼리를 KURE-v1으로 임베딩
        3. pgvector에서 cosine similarity 기반 top_k 검색
        4. score_threshold 미만 chunk 제거
        """
        expanded = expand_query(kiwi_keywords)
        filters = get_metadata_filters(kiwi_keywords)

        # 원본 질문과 확장된 관련어를 합쳐 임베딩 품질을 높인다
        query_text = query.question + " " + " ".join(expanded)
        embedding = self.embedding_model.predict([query_text])[0]

        # TODO: vector_store.search(embedding, filters, top_k) 호출
        chunks = []

        evidence = [
            c for c in chunks
            if (c.score or 0) >= self.score_threshold
        ]

        return RagResult(
            query=query.question,
            expanded_query=expanded,
            evidence=evidence,
        )
