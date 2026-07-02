from app.observability.phoenix import OI_LLM, OI_SPAN_KIND, safe_id, set_openinference_span_kind, set_safe_attributes
from app.config import settings


class DummySpan:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


def test_safe_id_hashes_without_exposing_raw_value():
    raw = "session-123"

    hashed = safe_id(raw)

    assert hashed != raw
    assert hashed == safe_id(raw)
    assert len(hashed) == 16


def test_set_safe_attributes_skips_complex_values(monkeypatch):
    monkeypatch.setattr(settings, "phoenix_tracing_enabled", True)
    span = DummySpan()

    set_safe_attributes(span, {
        "prompt.text": "do-not-use-this-helper-for-raw-prompts",
        "count": 3,
        "nested": {"raw": "value"},
        "empty": None,
    })

    assert span.attributes == {
        "count": 3,
    }


def test_set_openinference_span_kind(monkeypatch):
    monkeypatch.setattr(settings, "phoenix_tracing_enabled", True)
    span = DummySpan()

    set_openinference_span_kind(span, OI_LLM)

    assert span.attributes == {
        OI_SPAN_KIND: OI_LLM,
    }


def test_rag_observability_attributes_include_comparison_metrics(monkeypatch):
    from app.pipelines.report_pipeline import _rag_observability_attributes

    monkeypatch.setattr(settings, "rag_query_strategy", "hybrid-rerank")
    monkeypatch.setattr(settings, "rag_index_version", "pgvector-cosine-v2")
    monkeypatch.setattr(settings, "embedding_model_name", "nlpai-lab/KURE-v1")
    monkeypatch.setattr(settings, "rag_score_threshold", 0.55)
    monkeypatch.setattr(settings, "rag_rerank_enabled", True)
    monkeypatch.setattr(settings, "rag_rerank_top_k", 3)

    attrs = _rag_observability_attributes([
        {"chunk_id": "a", "score": 0.8, "content": "raw text is ignored"},
        {"chunk_id": "b", "score": 0.6},
        {"chunk_id": "c", "score": 0.7},
    ])

    assert attrs == {
        "rag.evidence_count": 3,
        "rag.query_strategy": "hybrid-rerank",
        "rag.index_version": "pgvector-cosine-v2",
        "rag.embedding_model": "nlpai-lab/KURE-v1",
        "rag.score_threshold": 0.55,
        "rag.rerank_enabled": True,
        "rag.rerank_top_k": 3,
        "rag.score_top1": 0.8,
        "rag.score_avg": 0.7,
        "rag.score_min": 0.6,
    }
