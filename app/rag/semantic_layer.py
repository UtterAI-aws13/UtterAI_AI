# RAG Semantic Layer
# Kiwi가 추출한 키워드를 ontology.yaml의 도메인 개념 사전으로 확장한다
# 예) "MLU" → "평균 발화 길이", "형태소 수", "발화 복잡도", "표현언어"
# 확장된 쿼리로 pgvector를 검색하면 직접 언급되지 않은 관련 문서도 찾을 수 있다
import yaml
from pathlib import Path

_ONTOLOGY_PATH = Path(__file__).parent / "ontology.yaml"

with open(_ONTOLOGY_PATH, encoding="utf-8") as f:
    _ONTOLOGY: dict = yaml.safe_load(f)


def expand_query(keywords: list[str]) -> list[str]:
    """키워드가 ontology의 어떤 concept에 해당하는지 찾아 관련어 전체를 반환한다.

    concept 이름, 한국어 표기, related_terms 중 하나라도 일치하면 해당 concept의
    모든 related_terms를 확장 결과에 포함한다.
    """
    expanded = set(keywords)
    for kw in keywords:
        for concept, data in _ONTOLOGY["concepts"].items():
            if kw in (concept, data.get("ko", "")) or kw in data.get("related_terms", []):
                expanded.update(data.get("related_terms", []))
    return list(expanded)


def get_metadata_filters(keywords: list[str]) -> dict:
    """키워드와 연관된 language_area와 metric 필터를 추출한다.

    pgvector 검색 시 메타데이터 필터로 적용해 관련 없는 문서를 사전에 제거한다.
    예) MLU 관련 → language_area: [expressive_language], metric: [mlu_morpheme]
    """
    language_areas: set[str] = set()
    metrics: set[str] = set()
    for kw in keywords:
        for concept, data in _ONTOLOGY["concepts"].items():
            if kw in (concept, data.get("ko", "")) or kw in data.get("related_terms", []):
                language_areas.update(data.get("language_area", []))
                metrics.update(data.get("metrics", []))
    return {"language_area": list(language_areas), "metric": list(metrics)}
