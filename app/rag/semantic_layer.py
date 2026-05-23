import yaml
from pathlib import Path

_ONTOLOGY_PATH = Path(__file__).parent / "ontology.yaml"

with open(_ONTOLOGY_PATH, encoding="utf-8") as f:
    _ONTOLOGY: dict = yaml.safe_load(f)


def expand_query(keywords: list[str]) -> list[str]:
    """키워드를 ontology 기반으로 관련어로 확장"""
    expanded = set(keywords)
    for kw in keywords:
        for concept, data in _ONTOLOGY["concepts"].items():
            if kw in (concept, data.get("ko", "")) or kw in data.get("related_terms", []):
                expanded.update(data.get("related_terms", []))
    return list(expanded)


def get_metadata_filters(keywords: list[str]) -> dict:
    """키워드에서 language_area, metric 필터 추출"""
    language_areas: set[str] = set()
    metrics: set[str] = set()
    for kw in keywords:
        for concept, data in _ONTOLOGY["concepts"].items():
            if kw in (concept, data.get("ko", "")) or kw in data.get("related_terms", []):
                language_areas.update(data.get("language_area", []))
                metrics.update(data.get("metrics", []))
    return {"language_area": list(language_areas), "metric": list(metrics)}
