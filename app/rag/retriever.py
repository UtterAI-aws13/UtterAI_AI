from app.schemas import RagQuery, RagResult
from app.rag.semantic_layer import expand_query, get_metadata_filters


class Retriever:
    def __init__(self, vector_store, embedding_model, top_k: int = 5, score_threshold: float = 0.5):
        self.vector_store = vector_store
        self.embedding_model = embedding_model
        self.top_k = top_k
        self.score_threshold = score_threshold

    def retrieve(self, query: RagQuery, kiwi_keywords: list[str]) -> RagResult:
        expanded = expand_query(kiwi_keywords)
        filters = get_metadata_filters(kiwi_keywords)

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
