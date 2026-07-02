"""document_id -> DOI 조회.

docs/papers/paper_metadata.json은 논문 수집 시점의 원본 메타데이터(doi 포함)를
담고 있지만, 인제스트 파이프라인(scripts/ingest_rag_docs.py)은 doi를 청크
메타데이터로 옮기지 않는다. 청크를 다시 인제스트하지 않아도 인사이트맵에서
원문 링크를 보여줄 수 있도록, 조회 시점에 이 파일을 직접 참조한다.
"""

from __future__ import annotations

import json
from pathlib import Path

_METADATA_PATH = Path(__file__).parent.parent.parent / "docs" / "papers" / "paper_metadata.json"

_cache: dict[str, dict] | None = None


def _load() -> dict[str, dict]:
    global _cache
    if _cache is None:
        if _METADATA_PATH.exists():
            _cache = json.loads(_METADATA_PATH.read_text())
        else:
            _cache = {}
    return _cache


def get_doi_url(document_id: str) -> str | None:
    """document_id에 매핑된 DOI가 있으면 https://doi.org/ 링크를, 없으면 None을 반환한다.

    국내 학술지 논문 등 DOI가 수집되지 않은 문서는 원문 링크를 제공하지 않는다.
    """
    entry = _load().get(document_id)
    doi = entry.get("doi") if entry else None
    return f"https://doi.org/{doi}" if doi else None
