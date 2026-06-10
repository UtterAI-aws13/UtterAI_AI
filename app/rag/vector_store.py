# pgvector 기반 벡터 저장소
# rag_chunks 테이블에 청크 텍스트와 KURE-v1 임베딩을 저장하고
# cosine similarity 기반 검색을 제공한다
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, func, select
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from pgvector.sqlalchemy import Vector

from app.storage.db import Base
from app.schemas import RagChunk, RagEvidence


class RagChunkORM(Base):
    """DB_SCHEMA.md AI DB 섹션 rag_chunks 테이블 정의."""

    __tablename__ = "rag_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type = Column(String(100), nullable=False)          # 예: clinical_guideline
    source_ref = Column(Text, nullable=True)                   # 원문 참조 경로 (document_id)
    chunk_text = Column(Text, nullable=False)                  # 청크 원문
    embedding = Column(Vector(1024), nullable=False)
    metadata_json = Column(JSONB, nullable=True)               # chunk_id, title, age_group 등
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class VectorStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, chunks: list[RagChunk], embeddings: list[list[float]]) -> None:
        """청크와 임베딩을 배치로 저장한다. 동일 chunk_id(metadata 내)가 있으면 덮어쓴다."""
        for chunk, emb in zip(chunks, embeddings):
            meta = chunk.metadata.model_dump()
            # chunk_id로 기존 행을 찾아 id를 재사용해 upsert
            existing = await self.session.execute(
                select(RagChunkORM).where(
                    RagChunkORM.metadata_json["chunk_id"].as_string() == chunk.chunk_id
                )
            )
            existing_row = existing.scalar_one_or_none()

            obj = RagChunkORM(
                id=existing_row.id if existing_row else uuid.uuid4(),
                source_type=chunk.metadata.source_type,
                source_ref=chunk.document_id,
                chunk_text=chunk.content,
                embedding=emb,
                metadata_json={**meta, "chunk_id": chunk.chunk_id},
            )
            await self.session.merge(obj)
        await self.session.commit()

    async def search(
        self,
        embedding: list[float],
        filters: dict,
        top_k: int,
        score_threshold: float = 0.0,
    ) -> list[RagEvidence]:
        """cosine similarity 기반 검색. filters에 language_area 목록이 있으면 적용한다."""
        distance_col = RagChunkORM.embedding.cosine_distance(embedding)
        score_col = (1 - distance_col).label("score")

        stmt = (
            select(RagChunkORM, score_col)
            .order_by(distance_col)
            .limit(top_k * 3)  # 메타데이터 필터 후 top_k를 채우기 위해 넉넉히 조회
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        evidence: list[RagEvidence] = []
        allowed_areas = filters.get("language_area") or []

        for row in rows:
            chunk_orm = row[0]
            score = float(row[1])

            if score < score_threshold:
                continue

            meta: dict = chunk_orm.metadata_json or {}

            if allowed_areas and meta.get("language_area") not in allowed_areas:
                continue

            evidence.append(RagEvidence(
                document_id=chunk_orm.source_ref or "",
                chunk_id=meta.get("chunk_id", str(chunk_orm.id)),
                title=meta.get("title", ""),
                source_type=chunk_orm.source_type,
                score=round(score, 4),
                text=chunk_orm.chunk_text,
                metadata=meta,
            ))

            if len(evidence) >= top_k:
                break

        return evidence
