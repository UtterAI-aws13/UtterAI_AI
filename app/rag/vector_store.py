# pgvector 기반 벡터 저장소 (로컬 개발 전용)
# 프로덕션에서는 Bedrock KB + Aurora/RDS pgvector로 대체된다.
#
# init_db.sql 스키마 기준:
#   chunk_id TEXT PRIMARY KEY
#   document_id TEXT NOT NULL
#   content TEXT NOT NULL
#   embedding VECTOR(1024) NOT NULL
#   metadata_json JSONB NOT NULL DEFAULT '{}'
from sqlalchemy import Column, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from pgvector.sqlalchemy import Vector

from app.storage.db import Base
from app.schemas import RagChunk, RagEvidence


class RagChunkORM(Base):
    __tablename__ = "rag_chunks"

    chunk_id = Column(String, primary_key=True)
    document_id = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1024), nullable=False)
    metadata_json = Column(JSONB, nullable=False, default=dict)


class VectorStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, chunks: list[RagChunk], embeddings: list[list[float]]) -> None:
        """청크와 임베딩을 저장한다. 동일 chunk_id면 덮어쓴다."""
        for chunk, emb in zip(chunks, embeddings):
            obj = RagChunkORM(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                content=chunk.content,
                embedding=emb,
                metadata_json=chunk.metadata.model_dump(),
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
            .limit(top_k * 3)
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

            if allowed_areas:
                chunk_areas = meta.get("language_area") or []
                if isinstance(chunk_areas, str):
                    chunk_areas = [chunk_areas]
                if not any(area in allowed_areas for area in chunk_areas):
                    continue

            evidence.append(RagEvidence(
                document_id=chunk_orm.document_id,
                chunk_id=chunk_orm.chunk_id,
                title=meta.get("title", ""),
                source_type=meta.get("source_type", ""),
                score=round(score, 4),
                text=chunk_orm.content,
                metadata=meta,
            ))

            if len(evidence) >= top_k:
                break

        return evidence