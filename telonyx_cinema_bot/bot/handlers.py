from __future__ import annotations

from aiogram import Bot, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Poll
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import async_sessionmaker

from telonyx_cinema_bot.bot.publisher import AiogramPublisher, TelegramPollReader
from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.services.content import ContentService
from telonyx_cinema_bot.services.dates import local_date_now


class SubmitMovieStates(StatesGroup):
    waiting_for_link_and_title = State()


def get_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Предложить фильм", callback_data="menu:submit")],
            [InlineKeyboardButton(text="⏳ На модерации", callback_data="menu:pending")],
            [
                InlineKeyboardButton(text="📰 Дайджест", callback_data="menu:digest"),
                InlineKeyboardButton(text="🍿 Подборка", callback_data="menu:recommend"),
            ]
        ]
    )


def get_cancel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:cancel")]
        ]
    )


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

    @router.message(Command("start"))
    async def start(message: Message, state: FSMContext) -> None:
        if is_admin(message):
            await state.clear()
            await message.answer(
                "Привет, админ! Выберите действие из меню ниже:",
                reply_markup=get_main_menu()
            )
        else:
            await message.answer("Привет! Я бот-помощник для Telonyx Cinema. У вас нет прав администратора.")

    @router.callback_query(F.data == "menu:cancel")
    async def cancel_action(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin_callback(callback):
            return
        await state.clear()
        if callback.message:
            await callback.message.edit_text("Действие отменено.", reply_markup=get_main_menu())

    @router.callback_query(F.data == "menu:submit")
    async def submit_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin_callback(callback):
            return
        await state.set_state(SubmitMovieStates.waiting_for_link_and_title)
        if callback.message:
            await callback.message.edit_text(
                "Отправьте ссылку на TikTok и название фильма в формате:\n"
                "`<ссылка> | <название>`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_cancel_menu()
            )

    @router.message(StateFilter(SubmitMovieStates.waiting_for_link_and_title))
    async def submit_process(message: Message, state: FSMContext) -> None:
        if not is_admin(message):
            return
        
        payload = message.text
        if not payload or "|" not in payload:
            await message.answer(
                "Неверный формат. Пожалуйста, используйте:\n`<ссылка> | <название>`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_cancel_menu()
            )
            return

        tiktok_url, title = [part.strip() for part in payload.split("|", 1)]
        if not tiktok_url or not title:
            await message.answer(
                "Ссылка или название пустые. Пожалуйста, используйте формат:\n`<ссылка> | <название>`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_cancel_menu()
            )
            return

        await state.clear()
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
        await message.answer("Главное меню:", reply_markup=get_main_menu())

    @router.callback_query(F.data == "menu:pending")
    async def pending(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback):
            return
        async with session_factory() as session:
            service = await service_for_session(session)
            drafts = await service.pending_drafts()
            
        if not drafts:
            if callback.message:
                await callback.message.edit_text("Черновиков на проверке нет.", reply_markup=get_main_menu())
            return
            
        if callback.message:
            await callback.message.delete()
            await callback.message.answer(f"Черновиков на проверке: {len(drafts)}")
            
        for draft in drafts:
            if callback.message:
                await callback.message.answer(
                    f"Черновик #{draft.id}\n\n{draft.card_text}",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=_draft_actions(draft.id),
                )
        if callback.message:
            await callback.message.answer("Главное меню:", reply_markup=get_main_menu())

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

    @router.callback_query(F.data == "menu:digest")
    async def digest_now(callback: CallbackQuery, bot: Bot) -> None:
        if not is_admin_callback(callback):
            return
        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                digest = await service.create_digest(publisher, local_date_now(settings.zoneinfo))
                
        text = "Дайджест опубликован." if digest else "Сегодня фильмов нет, дайджест пропущен."
        if callback.message:
            await callback.message.edit_text(text, reply_markup=get_main_menu())

    @router.callback_query(F.data == "menu:recommend")
    async def recommend_now(callback: CallbackQuery, bot: Bot) -> None:
        if not is_admin_callback(callback):
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
                
        text = "Подборка опубликована." if recommendation else "Дайджест не найден, подборка пропущена."
        if callback.message:
            await callback.message.edit_text(text, reply_markup=get_main_menu())

    @router.poll()
    async def poll_update(poll: Poll) -> None:
        votes = [option.voter_count for option in poll.options]
        async with session_factory() as session:
            async with session.begin():
                service = await service_for_session(session)
                await service.update_poll_votes(poll.id, votes)

    return router


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
