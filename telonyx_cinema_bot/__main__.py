from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from telonyx_cinema_bot.bot.handlers import build_router
from telonyx_cinema_bot.bot.publisher import AiogramPublisher
from telonyx_cinema_bot.config import get_settings
from telonyx_cinema_bot.db import create_engine, create_schema, create_session_factory
from telonyx_cinema_bot.scheduler import configure_scheduler
from telonyx_cinema_bot.services.gemini import GeminiCopywriter
from telonyx_cinema_bot.services.tmdb import TMDbClient


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    await create_schema(engine)
    session_factory = create_session_factory(engine)

    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    movie_provider = TMDbClient(settings.tmdb_api_key)
    copywriter = GeminiCopywriter(settings.gemini_api_key, settings.gemini_model)
    publisher = AiogramPublisher(bot, settings.telegram_channel_id)

    dispatcher.include_router(
        build_router(settings, session_factory, movie_provider, copywriter)
    )
    scheduler = configure_scheduler(
        settings,
        session_factory,
        publisher,
    )
    scheduler.start()

    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
