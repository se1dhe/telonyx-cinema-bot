from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker

from telonyx_cinema_bot.bot.publisher import AiogramPublisher, TelegramPollReader
from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.services.content import ContentService


def configure_scheduler(
    settings: Settings,
    session_factory: async_sessionmaker,
    publisher: AiogramPublisher,
    movie_provider,
    copywriter,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.zoneinfo)
    digest_hour, digest_minute = _parse_time(settings.digest_time)
    recommendation_hour, recommendation_minute = _parse_time(settings.recommendation_time)

    scheduler.add_job(
        _run_digest,
        "cron",
        hour=digest_hour,
        minute=digest_minute,
        args=[settings, session_factory, publisher, movie_provider, copywriter],
        id="daily_digest",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_recommendation,
        "cron",
        hour=recommendation_hour,
        minute=recommendation_minute,
        args=[settings, session_factory, publisher, movie_provider, copywriter],
        id="daily_recommendation",
        replace_existing=True,
    )
    return scheduler


async def _run_digest(settings, session_factory, publisher, movie_provider, copywriter) -> None:
    local_date = datetime.now(settings.zoneinfo).date()
    async with session_factory() as session:
        async with session.begin():
            service = ContentService(session, movie_provider, copywriter)
            await service.create_digest(publisher, local_date)


async def _run_recommendation(settings, session_factory, publisher, movie_provider, copywriter) -> None:
    local_date = datetime.now(settings.zoneinfo).date()
    async with session_factory() as session:
        async with session.begin():
            service = ContentService(session, movie_provider, copywriter)
            await service.create_recommendation(publisher, TelegramPollReader(), local_date)


def _parse_time(value: str) -> tuple[int, int]:
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)

