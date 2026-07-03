# Evidence Research/Critic Agent가 공유하는 근거 도메인 모델과 retriever 계약.
# 참고: 01_production_5_agent_agentic_rag_design.md §9.4, §9.5, §10.4, §16.1
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class EvidenceSearchQuery(BaseModel):
    query_ko: str | None = None
    query_en: str | None = None
    metrics: list[str] = []
    language_areas: list[str] = []
    population: list[str] = []
    source_types: list[str] = []
    top_k: int = Field(default=10, ge=1, le=50)


class EvidenceChunk(BaseModel):
    evidence_id: str
    source_id: str
    chunk_id: str
    source_type: str
    title: str
    publication_year: int | None = None
    population: list[str] = []
    metrics: list[str] = []
    language_areas: list[str] = []
    text: str
    retrieval_score: float
    rerank_score: float | None = None


class EvidenceRequirement(BaseModel):
    requirement_id: str
    soap_section: Literal["A", "P"]
    claim_type: str
    target: str
    minimum_sources: int = 1
    preferred_source_types: list[str] = []


class ResearchQueryRecord(BaseModel):
    requirement_id: str
    query_ko: str | None = None
    query_en: str | None = None
    expanded_terms: list[str] = []
    filters: dict[str, list[str]] = {}


class AcceptedEvidence(BaseModel):
    evidence_id: str
    requirement_ids: list[str]
    supported_claim_scope: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)
    directness: Literal["DIRECT", "INDIRECT", "BACKGROUND"]
    limitations: list[str] = []


class RejectedEvidence(BaseModel):
    evidence_id: str
    reason_code: str
    reason: str


class EvidenceRetriever(Protocol):
    """RAG backend(Bedrock Knowledge Bases / pgvector 등)를 감추는 검색 인터페이스.

    Agent/Graph 코드는 이 Protocol에만 의존하고 특정 backend에 결합되지 않는다.
    """
    async def search(self, query: EvidenceSearchQuery) -> list[EvidenceChunk]: ...
