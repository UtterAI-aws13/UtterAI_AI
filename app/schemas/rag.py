from datetime import datetime
from pydantic import BaseModel


class ChunkMetadata(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    source_type: str
    age_group: str | None = None
    language_area: str | None = None
    metric: list[str] = []
    page: int | None = None
    section: str | None = None
    created_at: datetime | None = None


class RagChunk(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    metadata: ChunkMetadata
    score: float | None = None


class RagEvidence(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    source_type: str
    score: float
    text: str
    metadata: dict = {}


class RagQuery(BaseModel):
    question: str
    session_metrics: dict | None = None
    filters: dict = {}


class RagResult(BaseModel):
    query: str
    expanded_query: list[str] = []
    evidence: list[RagEvidence]
