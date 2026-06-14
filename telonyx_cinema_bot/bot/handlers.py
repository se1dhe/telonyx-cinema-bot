from __future__ import annotations

from aiogram import Bot, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, Poll
from sqlalchemy.ext.asyncio import async_sessionmaker

from telonyx_cinema_bot.bot.publisher import AiogramPublisher, TelegramPollReader
from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.services.content import ContentService
from telonyx_cinema_bot.services.dates import local_date_now


def build_router(
    settings: Settings,
    session_factory: async_sessionmaker,
    movie_provider,
    copywriter,
) -> Router:
    router = Router()

    def is_admin(message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in settings.admin_user_ids)

    async def service_for_session(session) -> ContentService:
        return ContentService(session, movie_provider, copywriter)

    @router.message(Command("submit"))
    async def submit(message: Message) -> None:
        if not is_admin(message):
            return
        payload = _command_payload(message.text)
        if not payload or "|" not in payload:
            await message.answer("Usage: /submit <tiktok_url> | <movie title>")
            return

        tiktok_url, title = [part.strip() for part in payload.split("|", 1)]
        if not tiktok_url or not title:
            await message.answer("Usage: /submit <tiktok_url> | <movie title>")
            return

        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                draft = await service.submit(tiktok_url, title, message.from_user.id)
                await message.answer(
                    f"Draft #{draft.id} created:\n\n{draft.card_text}\n\n"
                    f"Approve with /approve {draft.id} or reject with /reject {draft.id}",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )

    @router.message(Command("pending"))
    async def pending(message: Message) -> None:
        if not is_admin(message):
            return
        async with session_factory() as session:
            service = await service_for_session(session)
            drafts = await service.pending_drafts()
        if not drafts:
            await message.answer("No pending drafts.")
            return
        lines = ["Pending drafts:"]
        lines.extend(f"#{draft.id} - {draft.film.title}" for draft in drafts)
        await message.answer("\n".join(lines))

    @router.message(Command("approve"))
    async def approve(message: Message, bot: Bot) -> None:
        if not is_admin(message):
            return
        draft_id = _int_payload(message.text)
        if draft_id is None:
            await message.answer("Usage: /approve <draft_id>")
            return
        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                await service.approve(draft_id, publisher, local_date_now(settings.zoneinfo))
        await message.answer(f"Draft #{draft_id} published.")

    @router.message(Command("reject"))
    async def reject(message: Message) -> None:
        if not is_admin(message):
            return
        draft_id = _int_payload(message.text)
        if draft_id is None:
            await message.answer("Usage: /reject <draft_id>")
            return
        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                await service.reject(draft_id)
        await message.answer(f"Draft #{draft_id} rejected.")

    @router.message(Command("digest_now"))
    async def digest_now(message: Message, bot: Bot) -> None:
        if not is_admin(message):
            return
        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                digest = await service.create_digest(publisher, local_date_now(settings.zoneinfo))
        await message.answer("Digest posted." if digest else "No films for today; digest skipped.")

    @router.message(Command("recommend_now"))
    async def recommend_now(message: Message, bot: Bot) -> None:
        if not is_admin(message):
            return
        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                recommendation = await service.create_recommendation(
                    publisher,
                    TelegramPollReader(),
                    local_date_now(settings.zoneinfo),
                )
        await message.answer(
            "Recommendation posted." if recommendation else "No digest found; recommendation skipped."
        )

    @router.poll()
    async def poll_update(poll: Poll) -> None:
        votes = [option.voter_count for option in poll.options]
        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                await service.update_poll_votes(poll.id, votes)

    return router


def _command_payload(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else None


def _int_payload(text: str | None) -> int | None:
    payload = _command_payload(text)
    if payload is None:
        return None
    try:
        return int(payload)
    except ValueError:
        return None
