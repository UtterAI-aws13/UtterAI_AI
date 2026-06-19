# DB 연결 설정
# SQLAlchemy async 엔진과 세션을 설정한다
# pgvector 확장이 설치된 PostgreSQL을 사용하며,
# rag_chunks 테이블의 embedding 컬럼에 벡터 검색을 적용한다
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from app.config import settings

def get_engine():
    # NullPool 환경에서는 엔진 객체 자체가 이벤트 루프에 종속된 상태를 가질 수 있다.
    # asyncio.run()은 호출마다 새 루프를 만들고 닫으므로, 싱글톤 엔진을 재사용하면
    # 두 번째 메시지부터 닫힌 루프를 바라보다 hang/error가 발생한다.
    # NullPool에서 엔진 생성 비용은 커넥션 비용과 무관하게 매우 저렴하므로 매번 생성한다.
    ssl_mode = "disable" if settings.app_env == "local" else "require"
    return create_async_engine(
        settings.database_url,
        connect_args={"sslmode": ssl_mode},
        poolclass=NullPool,
    )


class Base(DeclarativeBase):
    """SQLAlchemy ORM 모델의 기반 클래스. 모든 테이블 모델이 이를 상속한다."""
    pass


async def get_session() -> AsyncSession:
    """FastAPI dependency injection용 DB 세션 생성기."""
    async with AsyncSession(get_engine()) as session:
        yield session
