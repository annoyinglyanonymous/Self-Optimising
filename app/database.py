from app.config import settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

engine=create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV=="development",
    pool_pre_ping=True
)
AsyncSessionLocal=async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)
class Base(DeclarativeBase):
    pass
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except:
            await session.rollback()
            raise
        finally:
            await session.close()