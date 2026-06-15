from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker

from telonyx_cinema_bot.bot.publisher import AiogramPublisher
from telonyx_cinema_bot.config import Settings

logger = logging.getLogger(__name__)


def configure_scheduler(
    settings: Settings,
    session_factory: async_sessionmaker,
    publisher: AiogramPublisher,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.zoneinfo)
    now = datetime.now(settings.zoneinfo)

    scheduler.add_job(
        _run_editorial_collector,
        "interval",
        minutes=15,
        args=[settings, session_factory],
        id="editorial_collector",
        replace_existing=True,
        next_run_time=now,
    )
    scheduler.add_job(
        _run_editorial_publisher,
        "interval",
        minutes=5,
        args=[settings, session_factory, publisher],
        id="editorial_publisher",
        replace_existing=True,
        next_run_time=now + timedelta(seconds=45),
    )
    return scheduler


async def _run_editorial_collector(settings: Settings, session_factory) -> None:
    from telonyx_cinema_bot.services.editorial import EditorialService
    from telonyx_cinema_bot.services.gemini import GeminiCopywriter
    from telonyx_cinema_bot.services.news import NewsService

    logger.info("Collecting editorial news")
    async with session_factory() as session:
        copywriter = GeminiCopywriter(settings.gemini_api_key, settings.gemini_model)
        editorial = EditorialService(session, settings, copywriter)
        news = NewsService(session, copywriter)
        try:
            count = await news.fetch_and_enqueue_editorial_news(editorial)
            logger.info("Queued %s editorial news posts", count)
        except Exception:
            logger.exception("Failed to collect editorial news")


async def _run_editorial_publisher(
    settings: Settings,
    session_factory,
    publisher: AiogramPublisher,
) -> None:
    from telonyx_cinema_bot.services.editorial import EditorialService
    from telonyx_cinema_bot.services.gemini import GeminiCopywriter

    logger.info("Running editorial publisher tick")
    async with session_factory() as session:
        async with session.begin():
            copywriter = GeminiCopywriter(settings.gemini_api_key, settings.gemini_model)
            editorial = EditorialService(session, settings, copywriter)
            await editorial.maybe_publish_next(publisher)
