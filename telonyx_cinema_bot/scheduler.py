from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker

from telonyx_cinema_bot.bot.publisher import AiogramPublisher
from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.services.campaign import CampaignPublisherService

logger = logging.getLogger(__name__)

# ── Fixed broadcast schedule (Europe/Kiev) ──────────────────────────────
# 11:00 — Teaser (video)
# 14:00 — Review (poster + description + rating)
# 17:00 — Fact / Quote
# 20:00 — Recommendations (3 similar films)
# 10:00 (next day) — Poll ("Which film have you seen?")


def configure_scheduler(
    settings: Settings,
    session_factory: async_sessionmaker,
    publisher: AiogramPublisher,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.zoneinfo)
    common_args = [settings, session_factory, publisher]

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
    
    # News scraper runs every few hours
    scheduler.add_job(
        _run_news_scraper, "cron", hour="8,14,20", minute=30,
        args=[settings, session_factory], id="news_scraper", replace_existing=True,
    )
    
    # News publisher fills gaps
    scheduler.add_job(
        _run_news_publisher, "cron", hour="12,13,15,16,18,19,21", minute=0,
        args=common_args, id="news_publisher", replace_existing=True,
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
    logger.info("Running news scraper")
    from telonyx_cinema_bot.services.news import NewsService
    from telonyx_cinema_bot.services.gemini import GeminiCopywriter
    from aiogram import Bot
    
    async with session_factory() as session:
        async with session.begin():
            svc = NewsService(session, GeminiCopywriter(settings.gemini_api_key, settings.gemini_model))
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
            post = await svc.get_next_approved_news()
            if post:
                try:
                    msg_id = await publisher.publish_text(post.text)
                    post.published_msg_id = msg_id
                    from telonyx_cinema_bot.models import NewsStatus
                    post.status = NewsStatus.published
                except Exception as e:
                    logger.error(f"Failed to publish news {post.id}: {e}")
