from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from telonyx_cinema_bot.models import Base


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    from sqlalchemy import text
    async with engine.begin() as conn:
        # Автоматическая миграция: добавим новые колонки, если их нет (для Railway)
        try:
            await conn.execute(text("ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'pending'"))
            await conn.execute(text("ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMP WITH TIME ZONE"))
        except Exception as e:
            pass
        
        await conn.run_sync(Base.metadata.create_all)


async def session_scope(session_factory: async_sessionmaker) -> AsyncIterator:
    async with session_factory() as session:
        async with session.begin():
            yield session

