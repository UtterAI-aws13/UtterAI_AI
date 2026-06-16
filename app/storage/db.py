# DB 연결 설정
# SQLAlchemy async 엔진과 세션을 설정한다
# pgvector 확장이 설치된 PostgreSQL을 사용하며,
# rag_chunks 테이블의 embedding 컬럼에 벡터 검색을 적용한다
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

_engine = None

def get_engine():
    global _engine
    if _engine is None:
        ssl_mode = "disable" if settings.app_env == "local" else "require"
        _engine = create_async_engine(
            settings.database_url,
            connect_args={"sslmode": ssl_mode},
        )
    return _engine


class Base(DeclarativeBase):
    """SQLAlchemy ORM 모델의 기반 클래스. 모든 테이블 모델이 이를 상속한다."""
    pass


async def get_session() -> AsyncSession:
    """FastAPI dependency injection용 DB 세션 생성기."""
    async with AsyncSession(get_engine()) as session:
        yield session
