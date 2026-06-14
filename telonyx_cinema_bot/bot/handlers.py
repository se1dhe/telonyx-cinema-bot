from __future__ import annotations

from aiogram import Bot, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Poll
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

    def is_admin_callback(callback: CallbackQuery) -> bool:
        return bool(callback.from_user and callback.from_user.id in settings.admin_user_ids)

    async def service_for_session(session) -> ContentService:
        return ContentService(session, movie_provider, copywriter)

    @router.message(Command("submit"))
    async def submit(message: Message) -> None:
        if not is_admin(message):
            return
        payload = _command_payload(message.text)
        if not payload or "|" not in payload:
            await message.answer("Формат: /submit <ссылка TikTok> | <название фильма>")
            return

        tiktok_url, title = [part.strip() for part in payload.split("|", 1)]
        if not tiktok_url or not title:
            await message.answer("Формат: /submit <ссылка TikTok> | <название фильма>")
            return

        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                draft = await service.submit(tiktok_url, title, message.from_user.id)
                await message.answer(
                    f"Черновик #{draft.id} создан:\n\n{draft.card_text}\n\n"
                    "Проверьте карточку перед публикацией.",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=_draft_actions(draft.id),
                )

    @router.message(Command("pending"))
    async def pending(message: Message) -> None:
        if not is_admin(message):
            return
        async with session_factory() as session:
            service = await service_for_session(session)
            drafts = await service.pending_drafts()
        if not drafts:
            await message.answer("Черновиков на проверке нет.")
            return
        await message.answer(f"Черновиков на проверке: {len(drafts)}")
        for draft in drafts:
            await message.answer(
                f"Черновик #{draft.id}\n\n{draft.card_text}",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=_draft_actions(draft.id),
            )

    @router.message(Command("approve"))
    async def approve(message: Message, bot: Bot) -> None:
        if not is_admin(message):
            return
        draft_id = _int_payload(message.text)
        if draft_id is None:
            await message.answer("Формат: /approve <id черновика>")
            return
        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                await service.approve(draft_id, publisher, local_date_now(settings.zoneinfo))
        await message.answer(f"Черновик #{draft_id} опубликован.")

    @router.message(Command("reject"))
    async def reject(message: Message) -> None:
        if not is_admin(message):
            return
        draft_id = _int_payload(message.text)
        if draft_id is None:
            await message.answer("Формат: /reject <id черновика>")
            return
        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                await service.reject(draft_id)
        await message.answer(f"Черновик #{draft_id} отклонён.")

    @router.callback_query(lambda callback: callback.data and callback.data.startswith("draft:"))
    async def draft_action(callback: CallbackQuery, bot: Bot) -> None:
        if not is_admin_callback(callback):
            await callback.answer("Только для администратора.", show_alert=True)
            return

        action, draft_id = _parse_draft_callback(callback.data)
        if action is None or draft_id is None:
            await callback.answer("Неизвестное действие.", show_alert=True)
            return

        try:
            async with session_factory() as session:
                async with session.begin():
                    service = await service_for_session(session)
                    if action == "approve":
                        publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                        await service.approve(draft_id, publisher, local_date_now(settings.zoneinfo))
                        status_text = f"Черновик #{draft_id} опубликован."
                    elif action == "reject":
                        await service.reject(draft_id)
                        status_text = f"Черновик #{draft_id} отклонён."
                    else:
                        await callback.answer("Неизвестное действие.", show_alert=True)
                        return
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return

        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(status_text)
        await callback.answer(status_text)

    @router.message(Command("digest_now"))
    async def digest_now(message: Message, bot: Bot) -> None:
        if not is_admin(message):
            return
        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                digest = await service.create_digest(publisher, local_date_now(settings.zoneinfo))
        await message.answer("Дайджест опубликован." if digest else "Сегодня фильмов нет, дайджест пропущен.")

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
            "Подборка опубликована." if recommendation else "Дайджест не найден, подборка пропущена."
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


def _draft_actions(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Опубликовать", callback_data=f"draft:approve:{draft_id}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"draft:reject:{draft_id}"),
            ]
        ]
    )


def _parse_draft_callback(data: str | None) -> tuple[str | None, int | None]:
    if not data:
        return None, None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "draft":
        return None, None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None, None
