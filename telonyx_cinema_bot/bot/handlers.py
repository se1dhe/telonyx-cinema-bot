from __future__ import annotations

import datetime

from aiogram import Bot, Router, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.bot.publisher import AiogramPublisher
from telonyx_cinema_bot.models import Campaign
from telonyx_cinema_bot.services.campaign import CampaignPublisherService
from telonyx_cinema_bot.services.content import ContentService
from telonyx_cinema_bot.services.formatting import format_news_post


class SubmitMovieStates(StatesGroup):
    waiting_for_video = State()
    waiting_for_title = State()
    waiting_for_confirmation = State()


class SubmitNewsStates(StatesGroup):
    waiting_for_news = State()
    waiting_for_confirmation = State()


def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Отправить фильм", callback_data="menu:submit")],
            [InlineKeyboardButton(text="📰 Опубликовать (руками)", callback_data="menu:news")],
            [InlineKeyboardButton(text="📋 Черновики фильмов", callback_data="menu:pending")],
            [InlineKeyboardButton(text="🗞 Модерация новостей", callback_data="menu:news_pending")],
            [InlineKeyboardButton(text="⚙️ Статус очереди", callback_data="menu:queue_status")],
        ]
    )


def _cancel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:cancel")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")],
        ]
    )


def _draft_actions(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"draft:approve:{draft_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"draft:reject:{draft_id}")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")],
        ]
    )


def _news_draft_actions(news_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ В очередь", callback_data=f"news_draft:approve:{news_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"news_draft:reject:{news_id}")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")],
        ]
    )


def _back_to_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")],
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

    async def _show_main_menu(callback: CallbackQuery, state: FSMContext, text: str) -> None:
        await state.clear()
        if not callback.message:
            return

        try:
            await callback.message.edit_text(text, reply_markup=_main_menu())
        except TelegramBadRequest:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
            await callback.message.answer(text, reply_markup=_main_menu())

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
        await _show_main_menu(callback, state, "Действие отменено. Выберите действие:")
        await callback.answer()

    # ── back to main menu ───────────────────────────────────────────────

    @router.callback_query(F.data == "menu:back")
    async def cb_back(callback: CallbackQuery, state: FSMContext) -> None:
        await _show_main_menu(callback, state, "Выберите действие:")
        await callback.answer()

    # ── submit: step 1 – ask for video ──────────────────────────────────

    @router.callback_query(F.data == "menu:submit")
    async def cb_submit_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return
        await state.set_state(SubmitMovieStates.waiting_for_video)
        if callback.message:
            await callback.message.edit_text(
                "📎 <b>Шаг 1/2</b>\nЗагрузите видеофайл (MP4) или отправьте ссылку:",
                parse_mode=ParseMode.HTML,
                reply_markup=_cancel_menu(),
            )
        await callback.answer()

    # ── submit: step 1 handler – receive video, ask for title ──────────────

    @router.message(StateFilter(SubmitMovieStates.waiting_for_video))
    async def fsm_receive_video(message: Message, state: FSMContext) -> None:
        if not _is_admin_msg(message):
            return
        
        video_id = None
        if message.video:
            video_id = message.video.file_id
        elif message.text:
            video_id = message.text.strip()
            
        if not video_id:
            await message.answer(
                "⚠️ Пожалуйста, загрузите видео или отправьте ссылку:",
                reply_markup=_cancel_menu(),
            )
            return
            
        await state.update_data(video_file_id=video_id)
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
                [InlineKeyboardButton(text="✅ Да, это он", callback_data="submit:confirm_yes")],
                [InlineKeyboardButton(text="❌ Нет, другой", callback_data="submit:confirm_no")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:cancel")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")],
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
        video_file_id = data.get("video_file_id", "")
        title = data.get("title", "")
        tmdb_id = data.get("tmdb_id")
        await state.clear()

        if callback.message:
            await callback.message.edit_text("⏳ Генерирую кампанию на весь день (это займет немного времени)...")

        try:
            async with session_factory() as session:
                async with session.begin():
                    service = await _svc(session)
                    draft = await service.submit(video_file_id, title, callback.from_user.id, tmdb_id=tmdb_id)
                    text = (
                        f"✅ <b>Черновик кампании #{draft.id}</b> создан:\n\n"
                        f"<b>[14:00] Обзор:</b>\n{draft.review_text}\n\n"
                        f"<b>[17:00] Факт:</b>\n{draft.fact_text}\n\n"
                        f"<b>[20:00] Подборка:</b>\n{draft.recommendations_text}\n\n"
                        "Отправить в очередь публикаций?"
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
                    f"📋 <b>Черновик кампании #{draft.id}</b>\n\n"
                    f"<b>[14:00] Обзор:</b>\n{draft.review_text}\n\n"
                    f"<b>[17:00] Факт:</b>\n{draft.fact_text}\n\n"
                    f"<b>[20:00] Подборка:</b>\n{draft.recommendations_text}\n\n",
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

    # ── pending news drafts ─────────────────────────────────────────────

    @router.callback_query(F.data == "menu:news_pending")
    async def cb_news_pending(callback: CallbackQuery) -> None:
        if not _is_admin_cb(callback):
            return

        from telonyx_cinema_bot.services.news import NewsService
        from telonyx_cinema_bot.services.gemini import GeminiCopywriter

        async with session_factory() as session:
            news_svc = NewsService(
                session,
                GeminiCopywriter(settings.gemini_api_key, settings.gemini_model),
            )
            news_drafts = await news_svc.get_pending_news()

        if not news_drafts:
            if callback.message:
                await callback.message.edit_text(
                    "📭 Новых сгенерированных новостей нет.",
                    reply_markup=_main_menu(),
                )
            await callback.answer()
            return

        if callback.message:
            await callback.message.delete()

        for nd in news_drafts:
            if callback.message:
                text = format_news_post(nd.title or "Киноновость", nd.text, nd.source_url)
                if nd.image_url:
                    await callback.message.answer_photo(
                        nd.image_url,
                        caption=text,
                        reply_markup=_news_draft_actions(nd.id),
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await callback.message.answer(
                        text,
                        reply_markup=_news_draft_actions(nd.id),
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=False,
                    )

        if callback.message:
            await callback.message.answer(
                f"Всего новостей на модерации: <b>{len(news_drafts)}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu(),
            )
        await callback.answer()

    @router.callback_query(lambda cb: cb.data and cb.data.startswith("news_draft:"))
    async def cb_news_draft_action(callback: CallbackQuery) -> None:
        if not _is_admin_cb(callback):
            return
        
        parts = callback.data.split(":")
        action, news_id = parts[1], int(parts[2])

        from telonyx_cinema_bot.services.news import NewsService
        from telonyx_cinema_bot.services.gemini import GeminiCopywriter

        try:
            async with session_factory() as session:
                async with session.begin():
                    news_svc = NewsService(
                        session,
                        GeminiCopywriter(settings.gemini_api_key, settings.gemini_model),
                    )
                    if action == "approve":
                        await news_svc.approve_news(news_id)
                        status_text = f"✅ Новость #{news_id} добавлена в очередь."
                    elif action == "reject":
                        await news_svc.reject_news(news_id)
                        status_text = f"🗑 Новость #{news_id} отклонена."
                    else:
                        return
        except Exception as exc:
            await callback.answer(str(exc), show_alert=True)
            return

        if callback.message:
            await callback.message.edit_text(status_text, reply_markup=_back_to_main_menu())
        await callback.answer(status_text)

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
                        campaign = await service.queue_draft(draft_id)
                        publisher = AiogramPublisher(bot, settings.telegram_channel_id)
                        campaign_publisher = CampaignPublisherService(session, publisher)
                        await campaign_publisher.publish_campaign_teaser(campaign)
                        status_text = (
                            f"✅ Кампания #{draft_id} запланирована. "
                            "Видео с карточкой фильма опубликовано."
                        )
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
            await callback.message.edit_text(status_text, reply_markup=_back_to_main_menu())
        await callback.answer(status_text)

    # ── queue status ──────────────────────────────────────────────────────

    @router.callback_query(F.data == "menu:queue_status")
    async def cb_queue_status(callback: CallbackQuery) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        async with session_factory() as session:
            stmt = (
                select(Campaign)
                .where(Campaign.local_date >= datetime.date.today())
                .options(selectinload(Campaign.draft))
            )
            result = await session.execute(stmt)
            campaigns = result.scalars().all()
            
            if not campaigns:
                text = "📭 Очередь пуста. Загрузите новые фильмы!"
            else:
                text = f"📅 <b>В очереди {len(campaigns)} кампаний:</b>\n\n"
                for c in sorted(campaigns, key=lambda x: x.local_date):
                    text += f"- {c.local_date.strftime('%d.%m.%Y')}: Фильм #{c.draft.film_id}\n"

        if callback.message:
            try:
                await callback.message.edit_text(text, reply_markup=_main_menu(), parse_mode=ParseMode.HTML)
            except Exception:
                pass
        await callback.answer()




    # ── news submission ───────────────────────────────────────────────────

    @router.callback_query(F.data == "menu:news")
    async def cb_news_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin_cb(callback):
            return
        await state.set_state(SubmitNewsStates.waiting_for_news)
        if callback.message:
            await callback.message.edit_text(
                "📰 <b>Отправьте новость</b>\n"
                "Пришлите текст новости. Если нужно прикрепить фото/видео, отправьте их вместе с подписью.",
                parse_mode=ParseMode.HTML,
                reply_markup=_cancel_menu(),
            )
        await callback.answer()

    @router.message(StateFilter(SubmitNewsStates.waiting_for_news))
    async def fsm_receive_news(message: Message, state: FSMContext) -> None:
        if not _is_admin_msg(message):
            return

        text = message.html_text or message.text or ""
        if not text and not message.photo and not message.video:
            await message.answer("⚠️ Пустое сообщение.", reply_markup=_cancel_menu())
            return

        await state.update_data(
            source_chat_id=message.chat.id,
            source_message_id=message.message_id,
            text=text,
        )
        await state.set_state(SubmitNewsStates.waiting_for_confirmation)
        
        confirm_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Опубликовать", callback_data="news:publish")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:cancel")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")],
            ]
        )
        await message.copy_to(message.chat.id, reply_markup=confirm_kb)
        
    @router.callback_query(StateFilter(SubmitNewsStates.waiting_for_confirmation), F.data == "news:publish")
    async def fsm_news_publish(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if not _is_admin_cb(callback):
            return

        data = await state.get_data()
        source_chat_id = data.get("source_chat_id")
        source_message_id = data.get("source_message_id")
        text_content = data.get("text", "")
        await state.clear()

        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("⏳ Публикую новость...")

        try:
            msg_id = await bot.copy_message(
                chat_id=settings.telegram_channel_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id
            )
            from telonyx_cinema_bot.models import NewsPost
            async with session_factory() as session:
                async with session.begin():
                    post = NewsPost(text=text_content, published_msg_id=msg_id.message_id)
                    session.add(post)
            text_res = "✅ Новость опубликована!"
        except Exception as exc:
            text_res = f"❌ Ошибка публикации: {exc}"

        if callback.message:
            await callback.message.answer(text_res, reply_markup=_main_menu())
        await callback.answer()

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
