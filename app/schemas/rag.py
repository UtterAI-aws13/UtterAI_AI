# RAG(Retrieval-Augmented Generation) 관련 스키마
# 언어발달/치료 문서를 검색해 EXAONE 리포트 생성의 근거로 사용한다
from datetime import datetime
from pydantic import BaseModel


class ChunkMetadata(BaseModel):
    """RAG 문서 청크에 부착되는 메타데이터.

    age_group, language_area, metric 필드는 검색 시 필터링에 사용된다.
    예: age_group=preschool, language_area=expressive_language, metric=[MLU, NDW]
    """
    document_id: str
    chunk_id: str
    title: str
    source_type: str        # 예: clinical_guide, therapy_activity, soap_template
    age_group: str | None = None
    language_area: str | None = None
    metric: list[str] = []
    page: int | None = None
    section: str | None = None
    created_at: datetime | None = None


class RagChunk(BaseModel):
    """pgvector에 저장되는 청크 단위. embedding은 KURE-v1이 생성한 1024차원 벡터."""
    chunk_id: str
    document_id: str
    content: str
    metadata: ChunkMetadata
    score: float | None = None  # 검색 시 cosine similarity 점수


class RagEvidence(BaseModel):
    """검색 결과에서 score_threshold를 통과한 근거 청크.

    LLM 프롬프트에 삽입되며, 리포트에 evidence_chunk_ids로 출처가 기록된다.
    """
    document_id: str
    chunk_id: str
    title: str
    source_type: str
    score: float
    text: str
    metadata: dict = {}


class RagQuery(BaseModel):
    """검색 요청. 자유 텍스트 질문 외에 세션 지표와 필터를 함께 전달할 수 있다."""
    question: str
    session_metrics: dict | None = None  # 지표 수치를 쿼리 컨텍스트로 활용
    filters: dict = {}                   # age_group, language_area 등 메타데이터 필터


class RagResult(BaseModel):
    """검색 결과. 원본 쿼리, ontology 확장된 쿼리, 선택된 근거 목록을 포함."""
    query: str
    expanded_query: list[str] = []  # ontology.yaml 기반으로 확장된 관련어 목록
    evidence: list[RagEvidence]
