from __future__ import annotations

from aiogram import Bot, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Poll
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import async_sessionmaker

from telonyx_cinema_bot.bot.publisher import AiogramPublisher
from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.services.content import ContentService
from telonyx_cinema_bot.services.dates import local_date_now


class SubmitMovieStates(StatesGroup):
    waiting_for_url = State()
    waiting_for_title = State()
    waiting_for_confirmation = State()


def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Предложить фильм", callback_data="menu:submit")],
            [InlineKeyboardButton(text="⏳ На модерации", callback_data="menu:pending")],
            [
                InlineKeyboardButton(text="📰 Дайджест", callback_data="menu:digest"),
                InlineKeyboardButton(text="🍿 Подборка", callback_data="menu:recommend"),
            ],
        ]
    )


def _cancel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:cancel")]
        ]
    )


def _draft_actions(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"draft:approve:{draft_id}"),
                InlineKeyboardButton(text="🗑 Отклонить", callback_data=f"draft:reject:{draft_id}"),
            ]
        ]
    )


def build_router(
    settings: Settings,
    session_factory: async_sessionmaker,
    movie_provider,
    copywriter,
) -> Router:
    router = Router()

    # ── helpers ──────────────────────────────────────────────────────────

    def _is_admin_msg(message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in settings.admin_user_ids)

    def _is_admin_cb(callback: CallbackQuery) -> bool:
        return bool(callback.from_user and callback.from_user.id in settings.admin_user_ids)

    async def _svc(session) -> ContentService:
        return ContentService(session, movie_provider, copywriter)

    # ── /start  →  main menu ────────────────────────────────────────────

    @router.message(Command("start"))
    async def cmd_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        if _is_admin_msg(message):
            await message.answer(
                "👋 <b>Привет, админ!</b>\nВыберите действие:",
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu(),
            )
        else:
            await message.answer(
                "Привет! Я бот-помощник канала <b>Telonyx Cinema</b>.\n"
                "У вас нет прав администратора.",
                parse_mode=ParseMode.HTML,
            )

    # ── cancel (from any FSM state) ─────────────────────────────────────

    @router.callback_query(F.data == "menu:cancel")
    async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                "Действие отменено. Выберите действие:",
                reply_markup=_main_menu(),
            )
        await callback.answer()

    # ── back to main menu ───────────────────────────────────────────────

    @router.callback_query(F.data == "menu:back")
    async def cb_back(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                "Выберите действие:",
                reply_markup=_main_menu(),
            )
        await callback.answer()

    # ── submit: step 1 – ask for TikTok URL ─────────────────────────────

    @router.callback_query(F.data == "menu:submit")
    async def cb_submit_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return
        await state.set_state(SubmitMovieStates.waiting_for_url)
        if callback.message:
            await callback.message.edit_text(
                "📎 <b>Шаг 1/2</b>\nОтправьте ссылку на TikTok:",
                parse_mode=ParseMode.HTML,
                reply_markup=_cancel_menu(),
            )
        await callback.answer()

    # ── submit: step 1 handler – receive URL, ask for title ──────────────

    @router.message(StateFilter(SubmitMovieStates.waiting_for_url))
    async def fsm_receive_url(message: Message, state: FSMContext) -> None:
        if not _is_admin_msg(message):
            return
        url = (message.text or "").strip()
        if not url:
            await message.answer(
                "⚠️ Пустое сообщение. Пожалуйста, отправьте ссылку на TikTok:",
                reply_markup=_cancel_menu(),
            )
            return
        await state.update_data(tiktok_url=url)
        await state.set_state(SubmitMovieStates.waiting_for_title)
        await message.answer(
            "🎬 <b>Шаг 2/2</b>\nТеперь отправьте название фильма:",
            parse_mode=ParseMode.HTML,
            reply_markup=_cancel_menu(),
        )

    # ── submit: step 2 handler – receive title, create draft ─────────────

    @router.message(StateFilter(SubmitMovieStates.waiting_for_title))
    async def fsm_receive_title(message: Message, state: FSMContext) -> None:
        if not _is_admin_msg(message):
            return
        title = (message.text or "").strip()
        if not title:
            await message.answer(
                "⚠️ Пустое сообщение. Пожалуйста, отправьте название фильма:",
                reply_markup=_cancel_menu(),
            )
            return

        movie = await movie_provider.search_best_match(title)
        if not movie:
            await message.answer(
                f"❌ TMDb не нашёл фильм «{title}». Попробуйте другое название (оригинальное или год):",
                reply_markup=_cancel_menu(),
            )
            return

        await state.update_data(title=title, tmdb_id=movie.tmdb_id)
        await state.set_state(SubmitMovieStates.waiting_for_confirmation)

        confirm_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да, это он", callback_data="submit:confirm_yes"),
                    InlineKeyboardButton(text="❌ Нет, другой", callback_data="submit:confirm_no"),
                ],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:cancel")]
            ]
        )
        await message.answer(
            f"🔎 <b>Найден фильм:</b>\n"
            f"Название: {movie.display_title}\n"
            f"Описание: {movie.overview or 'Нет описания'}\n\n"
            "Это тот фильм?",
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_kb,
        )

    # ── submit: step 3 handler – confirm match ─────────────

    @router.callback_query(StateFilter(SubmitMovieStates.waiting_for_confirmation), F.data.startswith("submit:confirm_"))
    async def fsm_confirm_match(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin_cb(callback):
            return

        action = callback.data.split(":")[1]
        if action == "confirm_no":
            await state.set_state(SubmitMovieStates.waiting_for_title)
            if callback.message:
                await callback.message.edit_text(
                    "Введите другое название фильма:",
                    reply_markup=_cancel_menu(),
                )
            await callback.answer()
            return

        data = await state.get_data()
        tiktok_url = data.get("tiktok_url", "")
        title = data.get("title", "")
        tmdb_id = data.get("tmdb_id")
        await state.clear()

        if callback.message:
            await callback.message.edit_text("⏳ Генерирую черновик...")

        try:
            async with session_factory() as session:
                async with session.begin():
                    service = await _svc(session)
                    draft = await service.submit(tiktok_url, title, callback.from_user.id, tmdb_id=tmdb_id)
                    text = (
                        f"✅ <b>Черновик #{draft.id}</b> создан:\n\n"
                        f"{draft.card_text}\n\n"
                        "Проверьте карточку и выберите действие:"
                    )
                    if callback.message:
                        await callback.message.answer(
                            text,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                            reply_markup=_draft_actions(draft.id),
                        )
        except ValueError as exc:
            if callback.message:
                await callback.message.answer(f"❌ Ошибка: {exc}")

        if callback.message:
            await callback.message.answer("Главное меню:", reply_markup=_main_menu())
        await callback.answer()

    # ── pending drafts ──────────────────────────────────────────────────

    @router.callback_query(F.data == "menu:pending")
    async def cb_pending(callback: CallbackQuery) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        async with session_factory() as session:
            service = await _svc(session)
            drafts = await service.pending_drafts()

        if not drafts:
            if callback.message:
                await callback.message.edit_text(
                    "📭 Черновиков на проверке нет.",
                    reply_markup=_main_menu(),
                )
            await callback.answer()
            return

        if callback.message:
            await callback.message.delete()

        for draft in drafts:
            if callback.message:
                await callback.message.answer(
                    f"📋 <b>Черновик #{draft.id}</b>\n\n{draft.card_text}",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=_draft_actions(draft.id),
                )

        if callback.message:
            await callback.message.answer(
                f"Всего на модерации: <b>{len(drafts)}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu(),
            )
        await callback.answer()

    # ── approve / reject via inline buttons ─────────────────────────────

    @router.callback_query(lambda cb: cb.data and cb.data.startswith("draft:"))
    async def cb_draft_action(callback: CallbackQuery, bot: Bot) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администратора.", show_alert=True)
            return

        action, draft_id = _parse_draft_callback(callback.data)
        if action is None or draft_id is None:
            await callback.answer("Неизвестное действие.", show_alert=True)
            return

        try:
            async with session_factory() as session:
                async with session.begin():
                    service = await _svc(session)
                    if action == "approve":
                        publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                        await service.approve(draft_id, publisher, local_date_now(settings.zoneinfo))
                        status_text = f"✅ Черновик #{draft_id} опубликован в канал."
                    elif action == "reject":
                        await service.reject(draft_id)
                        status_text = f"🗑 Черновик #{draft_id} отклонён."
                    else:
                        await callback.answer("Неизвестное действие.", show_alert=True)
                        return
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return

        if callback.message:
            await callback.message.edit_text(status_text, reply_markup=None)
        await callback.answer(status_text)

    # ── digest now ──────────────────────────────────────────────────────

    @router.callback_query(F.data == "menu:digest")
    async def cb_digest(callback: CallbackQuery, bot: Bot) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        if callback.message:
            await callback.message.edit_text("⏳ Формирую дайджест…")

        async with session_factory() as session:
            async with session.begin():
                service = await _svc(session)
                publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                digest = await service.create_digest(publisher, local_date_now(settings.zoneinfo))

        text = "📰 Дайджест опубликован!" if digest else "Сегодня фильмов нет, дайджест пропущен."
        if callback.message:
            await callback.message.edit_text(text, reply_markup=_main_menu())
        await callback.answer()

    # ── recommend now ───────────────────────────────────────────────────

    @router.callback_query(F.data == "menu:recommend")
    async def cb_recommend(callback: CallbackQuery, bot: Bot) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        if callback.message:
            await callback.message.edit_text("⏳ Формирую подборку…")

        async with session_factory() as session:
            async with session.begin():
                service = await _svc(session)
                publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                recommendation = await service.create_recommendation(
                    publisher,
                    local_date_now(settings.zoneinfo),
                )

        text = "🍿 Подборка опубликована!" if recommendation else "Дайджест не найден, подборка пропущена."
        if callback.message:
            await callback.message.edit_text(text, reply_markup=_main_menu())
        await callback.answer()

    # ── poll vote tracking ──────────────────────────────────────────────

    @router.poll()
    async def poll_update(poll: Poll) -> None:
        votes = [option.voter_count for option in poll.options]
        async with session_factory() as session:
            async with session.begin():
                service = await _svc(session)
                await service.update_poll_votes(poll.id, votes)

    return router


# ── private helpers ─────────────────────────────────────────────────────

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
