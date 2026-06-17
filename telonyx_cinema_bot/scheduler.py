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
    scheduler.add_job(
        _run_review_collector,
        "interval",
        hours=4,
        args=[settings, session_factory],
        id="review_collector",
        replace_existing=True,
        next_run_time=now + timedelta(minutes=2),
    )
    scheduler.add_job(
        _run_shorts_queue,
        "interval",
        minutes=1,
        args=[settings, session_factory, publisher],
        id="shorts_queue",
        replace_existing=True,
        next_run_time=now + timedelta(seconds=15),
    )
    return scheduler


async def _build_copywriter(settings: Settings):
    from telonyx_cinema_bot.services.gemini import FallbackCopywriter, GeminiCopywriter
    from telonyx_cinema_bot.services.groq import GroqCopywriter

    fallback: FallbackCopywriter
    if settings.groq_api_key:
        fallback = GroqCopywriter(settings.groq_api_key, settings.groq_model)
    else:
        fallback = FallbackCopywriter()

    return GeminiCopywriter(settings.gemini_api_key, settings.gemini_model, fallback=fallback)


async def _run_review_collector(settings: Settings, session_factory) -> None:
    from sqlalchemy import func, select

    from telonyx_cinema_bot.models import Film
    from telonyx_cinema_bot.services.editorial import EditorialService
    from telonyx_cinema_bot.services.tmdb import MovieMetadata

    logger.info("Collecting review post")
    async with session_factory() as session:
        copywriter = await _build_copywriter(settings)
        editorial = EditorialService(session, settings, copywriter)

        result = await session.execute(
            select(Film)
            .where(Film.poster_path.is_not(None))
            .where(Film.poster_path != "")
            .order_by(func.random())
            .limit(1)
        )
        film = result.scalar_one_or_none()
        if film is None:
            logger.info("No films available for review post")
            return

        movie = MovieMetadata(
            tmdb_id=film.tmdb_id,
            title=film.title,
            original_title=film.original_title,
            release_year=film.release_year,
            overview=film.overview,
            poster_path=film.poster_path,
            imdb_id=film.imdb_id,
            imdb_rating=film.imdb_rating,
            genres=film.genres,
            similar_movies=film.similar_movies,
            raw_metadata=film.raw_metadata,
        )
        post = await editorial.enqueue_review_post(movie)
        if post:
            logger.info("Queued review post for %s", movie.display_title)
        else:
            logger.info("Review post skipped (duplicate?)")


async def _run_shorts_queue(
    settings: Settings,
    session_factory,
    publisher: AiogramPublisher,
) -> None:
    from sqlalchemy import select

    from telonyx_cinema_bot.models import ShortsQueue, ShortsQueueStatus
    from telonyx_cinema_bot.services.shorts import process_shorts_item

    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(ShortsQueue)
                .where(ShortsQueue.status == ShortsQueueStatus.pending)
                .where(ShortsQueue.scheduled_for <= datetime.now(settings.zoneinfo))
                .order_by(ShortsQueue.scheduled_for, ShortsQueue.created_at)
                .limit(1)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return

            item.status = ShortsQueueStatus.downloading

    logger.info("Processing shorts queue item #%s: %s", item.id, item.url)
    try:
        copywriter = await _build_copywriter(settings)
        async with session_factory() as session:
            await process_shorts_item(item.id, session, publisher.bot, settings, copywriter)
    except Exception:
        logger.exception("Shorts queue processing failed for item #%s", item.id)


async def _run_editorial_collector(settings: Settings, session_factory) -> None:
    from telonyx_cinema_bot.services.editorial import EditorialService
    from telonyx_cinema_bot.services.news import NewsService

    logger.info("Collecting editorial news")
    async with session_factory() as session:
        copywriter = await _build_copywriter(settings)
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

    logger.info("Running editorial publisher tick")
    async with session_factory() as session:
        async with session.begin():
            copywriter = await _build_copywriter(settings)
            editorial = EditorialService(session, settings, copywriter)
            await editorial.maybe_publish_next(publisher)
