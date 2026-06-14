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
    
    migrations = [
        # Старая колонка из MVP — убираем NOT NULL чтобы не блокировала вставки
        "ALTER TABLE submissions ALTER COLUMN tiktok_url DROP NOT NULL",
        "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS video_file_id VARCHAR(255)",
        "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS video_file_id VARCHAR(255)",
        "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS review_text TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS fact_text TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS recommendations_text TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS title VARCHAR(512)",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS image_url VARCHAR(1024)",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS source_url VARCHAR(1024)",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'pending'",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMP WITH TIME ZONE",
        "CREATE TABLE IF NOT EXISTS news_urls (id SERIAL PRIMARY KEY, url VARCHAR(512) UNIQUE NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())",
    ]
    
    for sql in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
        except Exception:
            pass

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _clear_legacy_news(engine)


async def _clear_legacy_news(engine: AsyncEngine) -> None:
    from sqlalchemy import text

    migration_name = "clear_legacy_news_posts_v1"
    async with engine.begin() as conn:
        applied = await conn.scalar(
            text("SELECT 1 FROM schema_migrations WHERE name = :name"),
            {"name": migration_name},
        )
        if applied:
            return

        await conn.execute(text("DELETE FROM news_posts"))
        await conn.execute(text("DELETE FROM news_urls"))
        await conn.execute(
            text("INSERT INTO schema_migrations (name) VALUES (:name)"),
            {"name": migration_name},
        )


async def session_scope(session_factory: async_sessionmaker) -> AsyncIterator:
    async with session_factory() as session:
        async with session.begin():
            yield session
