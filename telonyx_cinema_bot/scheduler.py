from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker

from telonyx_cinema_bot.bot.publisher import AiogramPublisher
from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.services.campaign import CampaignPublisherService

logger = logging.getLogger(__name__)

# ── Editorial v2 schedule (Europe/Kiev) ────────────────────────────────
# A frequent editorial tick keeps the queue warm and publishes only when
# cadence rules allow it. Legacy campaign jobs stay as compatibility hooks
# for already queued film campaigns.


def configure_scheduler(
    settings: Settings,
    session_factory: async_sessionmaker,
    publisher: AiogramPublisher,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.zoneinfo)
    common_args = [settings, session_factory, publisher]
    now = datetime.now(settings.zoneinfo)

    scheduler.add_job(
        _run_teaser, "cron", hour=11, minute=0,
        args=common_args, id="campaign_teaser", replace_existing=True,
    )
    scheduler.add_job(
        _run_review, "cron", hour=14, minute=0,
        args=common_args, id="campaign_review", replace_existing=True,
    )
    scheduler.add_job(
        _run_fact, "cron", hour=17, minute=0,
        args=common_args, id="campaign_fact", replace_existing=True,
    )
    scheduler.add_job(
        _run_recommendations, "cron", hour=20, minute=0,
        args=common_args, id="campaign_recommendations", replace_existing=True,
    )
    scheduler.add_job(
        _run_poll, "cron", hour=10, minute=0,
        args=common_args, id="campaign_poll", replace_existing=True,
    )
    
    scheduler.add_job(
        _run_editorial_collector, "interval", minutes=15,
        args=[settings, session_factory], id="editorial_collector", replace_existing=True,
        next_run_time=now,
    )
    scheduler.add_job(
        _run_editorial_publisher, "interval", minutes=5,
        args=common_args, id="editorial_publisher", replace_existing=True,
        next_run_time=now + timedelta(seconds=45),
    )
    return scheduler


async def _run_teaser(settings: Settings, session_factory, publisher: AiogramPublisher) -> None:
    local_date = datetime.now(settings.zoneinfo).date()
    logger.info("Campaign teaser for %s", local_date)
    async with session_factory() as session:
        async with session.begin():
            svc = CampaignPublisherService(session, publisher)
            await svc.publish_teaser(local_date)


async def _run_review(settings: Settings, session_factory, publisher: AiogramPublisher) -> None:
    local_date = datetime.now(settings.zoneinfo).date()
    logger.info("Campaign review for %s", local_date)
    async with session_factory() as session:
        async with session.begin():
            svc = CampaignPublisherService(session, publisher)
            await svc.publish_review(local_date)


async def _run_fact(settings: Settings, session_factory, publisher: AiogramPublisher) -> None:
    local_date = datetime.now(settings.zoneinfo).date()
    logger.info("Campaign fact for %s", local_date)
    async with session_factory() as session:
        async with session.begin():
            svc = CampaignPublisherService(session, publisher)
            await svc.publish_fact(local_date)


async def _run_recommendations(settings: Settings, session_factory, publisher: AiogramPublisher) -> None:
    local_date = datetime.now(settings.zoneinfo).date()
    logger.info("Campaign recommendations for %s", local_date)
    async with session_factory() as session:
        async with session.begin():
            svc = CampaignPublisherService(session, publisher)
            await svc.publish_recommendations(local_date)


async def _run_poll(settings: Settings, session_factory, publisher: AiogramPublisher) -> None:
    # The poll refers to YESTERDAY's campaign
    yesterday = datetime.now(settings.zoneinfo).date() - timedelta(days=1)
    logger.info("Campaign poll (for yesterday %s)", yesterday)
    async with session_factory() as session:
        async with session.begin():
            svc = CampaignPublisherService(session, publisher)
            await svc.publish_poll(yesterday)

async def _run_news_scraper(settings: Settings, session_factory) -> None:
    from telonyx_cinema_bot.services.news import NewsService
    from telonyx_cinema_bot.services.gemini import GeminiCopywriter
    from aiogram import Bot

    local_date = datetime.now(settings.zoneinfo).date()
    logger.info("Checking news approval queue for %s", local_date)
    
    async with session_factory() as session:
        async with session.begin():
            svc = NewsService(session, GeminiCopywriter(settings.gemini_api_key, settings.gemini_model))
            if await svc.has_news_for_date(local_date):
                logger.info("News for %s is already approved or published", local_date)
                return
            if await svc.has_pending_news():
                logger.info("Pending news already exists; waiting for admin approval")
                return

            count = await svc.fetch_and_prepare_news()
            
            if count > 0:
                bot = Bot(token=settings.bot_token)
                try:
                    for admin_id in settings.admin_user_ids:
                        try:
                            await bot.send_message(
                                chat_id=admin_id,
                                text=f"🗞 Найдено {count} новых новостей! Зайдите в меню модерации."
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify admin {admin_id}: {e}")
                finally:
                    await bot.session.close()

async def _run_news_publisher(settings: Settings, session_factory, publisher: AiogramPublisher) -> None:
    logger.info("Running news publisher to fill the gap")
    from telonyx_cinema_bot.services.news import NewsService
    from telonyx_cinema_bot.services.gemini import GeminiCopywriter
    
    async with session_factory() as session:
        async with session.begin():
            svc = NewsService(session, GeminiCopywriter(settings.gemini_api_key, settings.gemini_model))
            local_date = datetime.now(settings.zoneinfo).date()
            post = await svc.get_next_approved_news(local_date)
            if post:
                try:
                    from telonyx_cinema_bot.services.formatting import format_news_post

                    text = format_news_post(post.title or "Киноновость", post.text, post.source_url)
                    msg_id = await publisher.publish_news(text, post.image_url or post.photo_file_id)
                    post.published_msg_id = msg_id
                    from telonyx_cinema_bot.models import NewsStatus
                    post.status = NewsStatus.published
                except Exception as e:
                    logger.error(f"Failed to publish news {post.id}: {e}")


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
