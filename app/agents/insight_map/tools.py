"""Strands @tool definitions for the insight map query resolver agent.

Both tools read from the existing RAG ontology dictionary
(app/rag/ontology.yaml via app/rag/semantic_layer.py) instead of maintaining
a second copy — this agent never owns concept data, it only looks it up.
"""

from __future__ import annotations

from strands.tools import tool

from app.rag.semantic_layer import _ONTOLOGY


@tool
def search_ontology_concepts(query: str) -> str:
    """검색어와 관련된 온톨로지 concept 후보를 찾는다.

    query: 자연어 검색어 또는 키워드. 예: '낮은 MLU', '짧은 발화'.
    """
    query_lower = query.lower()
    matches = []
    for concept_key, data in _ONTOLOGY["concepts"].items():
        haystack = [concept_key.lower(), data.get("ko", "").lower()]
        haystack += [t.lower() for t in data.get("related_terms", [])]
        if any(h and (h in query_lower or query_lower in h) for h in haystack):
            related = ", ".join(data.get("related_terms", [])[:5])
            matches.append(f"{concept_key} (ko: {data.get('ko', '')}, related: {related})")

    if not matches:
        return "관련 concept을 찾지 못했습니다."
    return "\n".join(matches)


@tool
def search_synonyms(concept_key: str) -> str:
    """특정 concept의 동의어/관련어 목록을 반환한다.

    concept_key: ontology.yaml에 정의된 concept 키. 예: 'MLU', 'short_utterance'.
    """
    data = _ONTOLOGY["concepts"].get(concept_key)
    if data is None:
        return f"concept '{concept_key}'을 찾을 수 없습니다."
    related = ", ".join(data.get("related_terms", []))
    return related or "동의어가 등록되지 않았습니다."
