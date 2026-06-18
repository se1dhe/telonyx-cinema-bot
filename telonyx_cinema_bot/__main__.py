from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher

from telonyx_cinema_bot.bot.handlers import build_router
from telonyx_cinema_bot.bot.publisher import AiogramPublisher
from telonyx_cinema_bot.config import get_settings
from telonyx_cinema_bot.db import create_engine, create_schema, create_session_factory
from telonyx_cinema_bot.scheduler import configure_scheduler
from telonyx_cinema_bot.services.gemini import FallbackCopywriter, GeminiCopywriter
from telonyx_cinema_bot.services.groq import GroqCopywriter
from telonyx_cinema_bot.web import build_app


def _build_copywriter(settings) -> GeminiCopywriter:
    fallback: FallbackCopywriter
    if settings.groq_api_key:
        fallback = GroqCopywriter(settings.groq_api_key, settings.groq_model)
    else:
        fallback = FallbackCopywriter()

    return GeminiCopywriter(
        settings.gemini_api_key,
        settings.gemini_model,
        fallback=fallback,
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    await create_schema(engine)
    session_factory = create_session_factory(engine)

    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    copywriter = _build_copywriter(settings)
    publisher = AiogramPublisher(bot, settings.telegram_channel_id)

    dispatcher.include_router(
        build_router(settings, session_factory, copywriter)
    )
    scheduler = configure_scheduler(
        settings,
        session_factory,
        publisher,
    )
    scheduler.start()

    # Start FastAPI file server alongside the bot
    fastapi_app = build_app(settings)
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)

    bot_task = asyncio.create_task(_run_bot(dispatcher, bot))
    web_task = asyncio.create_task(server.serve())

    try:
        await asyncio.gather(bot_task, web_task)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()


async def _run_bot(dispatcher, bot) -> None:
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
