from __future__ import annotations

from collections.abc import AsyncIterator
import logging

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from telonyx_cinema_bot.models import Base

logger = logging.getLogger(__name__)


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    migrations = [
        "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS video_file_id VARCHAR(255)",
        "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS video_file_id VARCHAR(255)",
        "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS review_text TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS fact_text TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS recommendations_text TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS title VARCHAR(512)",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS image_url VARCHAR(1024)",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS image_urls JSON DEFAULT '[]'",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS source_url VARCHAR(1024)",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'pending'",
        "ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMP WITH TIME ZONE",
        "CREATE TABLE IF NOT EXISTS news_urls (id SERIAL PRIMARY KEY, url VARCHAR(512) UNIQUE NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())",
    ]

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _drop_legacy_not_null(engine, "submissions", "tiktok_url")
    await _drop_legacy_not_null(engine, "drafts", "card_text")
    for sql in migrations:
        async with engine.begin() as conn:
            await conn.execute(text(sql))

    await _clear_legacy_news(engine)


async def _clear_legacy_news(engine: AsyncEngine) -> None:
    async def run_once(name: str, statements: list[str]) -> None:
        async with engine.begin() as conn:
            applied = await conn.scalar(
                text("SELECT 1 FROM schema_migrations WHERE name = :name"),
                {"name": name},
            )
            if applied:
                return

            for sql in statements:
                await conn.execute(text(sql))
            await conn.execute(
                text("INSERT INTO schema_migrations (name) VALUES (:name)"),
                {"name": name},
            )

    await run_once("clear_legacy_news_posts_v1", ["DELETE FROM news_posts", "DELETE FROM news_urls"])
    await run_once(
        "clear_news_without_images_v1",
        ["DELETE FROM news_posts WHERE image_url IS NULL OR image_url = ''"],
    )


async def _drop_legacy_not_null(engine: AsyncEngine, table: str, column: str) -> None:
    allowed_columns = {
        ("submissions", "tiktok_url"),
        ("drafts", "card_text"),
    }
    if (table, column) not in allowed_columns:
        raise ValueError(f"Unexpected legacy column migration: {table}.{column}")

    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL"))
    except ProgrammingError as exc:
        message = str(exc.orig if getattr(exc, "orig", None) else exc)
        if column not in message and "UndefinedColumn" not in message:
            raise
        logger.info("Legacy %s.%s column is absent; skipping NOT NULL migration", table, column)


async def session_scope(session_factory: async_sessionmaker) -> AsyncIterator:
    async with session_factory() as session:
        async with session.begin():
            yield session
