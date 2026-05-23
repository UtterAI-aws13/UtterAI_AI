from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(settings.database_url)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncSession:
    async with AsyncSession(engine) as session:
        yield session
