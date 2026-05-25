"""
SQLAlchemy ORM 기반 테이블 생성 스크립트.

docker-compose 대신 직접 PostgreSQL을 사용할 때, 또는
테이블 구조 변경 후 재생성이 필요할 때 실행한다.

실행 전 .env 파일에 DATABASE_URL이 설정돼 있어야 한다.

사용법:
    python scripts/create_tables.py
"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.storage.db import engine, Base
from app.rag.vector_store import RagChunkORM  # noqa: F401 — Base에 ORM 모델 등록


async def main() -> None:
    print("테이블 생성 시작...")
    async with engine.begin() as conn:
        # pgvector 확장이 활성화돼 있어야 Vector 타입이 동작한다
        await conn.execute(__import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    print("완료: rag_chunks 테이블 생성")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
