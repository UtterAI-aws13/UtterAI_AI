"""
AI DB 테이블 생성 스크립트.

AI 서버 전용 PostgreSQL(pgvector 필수)에 rag_chunks 테이블을 생성한다.
BE RDS와 분리된 별도 DB를 대상으로 한다.

실행 전 환경 변수(또는 .env)에 DB 접속 정보를 설정해야 한다:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

사용법:
    python scripts/create_tables.py [--drop]

옵션:
    --drop  기존 테이블을 먼저 DROP한 뒤 재생성한다 (개발 환경 전용)
"""
import asyncio
import sys
from pathlib import Path

import sqlalchemy

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.storage.db import get_engine, Base
from app.rag.vector_store import RagChunkORM  # noqa: F401 — Base에 ORM 모델 등록


async def main(drop: bool = False) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))

        if drop:
            print("[경고] 기존 테이블 DROP 후 재생성합니다.")
            await conn.run_sync(Base.metadata.drop_all)

        await conn.run_sync(Base.metadata.create_all)

    tables = list(Base.metadata.tables.keys())
    print(f"완료: {tables}")
    await engine.dispose()


if __name__ == "__main__":
    drop_flag = "--drop" in sys.argv
    asyncio.run(main(drop=drop_flag))
