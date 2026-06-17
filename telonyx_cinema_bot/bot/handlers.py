from __future__ import annotations

import datetime

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.models import ShortsQueue, ShortsQueueStatus
from telonyx_cinema_bot.services.editorial import EditorialService


class ManualPostStates(StatesGroup):
    waiting_for_post = State()
    waiting_for_confirmation = State()


class AddShortsStates(StatesGroup):
    waiting_for_url = State()


def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎛 Редакционная очередь", callback_data="editorial:queue")],
            [
                InlineKeyboardButton(text="▶️ Автопоток", callback_data="editorial:resume"),
                InlineKeyboardButton(text="⏸ Пауза", callback_data="editorial:pause"),
            ],
            [InlineKeyboardButton(text="🚀 Опубликовать сейчас", callback_data="editorial:publish_now")],
            [InlineKeyboardButton(text="📰 Ручной пост", callback_data="manual:start")],
            [InlineKeyboardButton(text="🎬 Shorts", callback_data="shorts:add")],
        ]
    )


def _cancel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:cancel")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")],
        ]
    )


async def _replace_callback_message(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: ParseMode | None = ParseMode.HTML,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except TelegramBadRequest:
        pass

    if message.caption is not None:
        try:
            await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return
        except TelegramBadRequest:
            pass

    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


def build_router(
    settings: Settings,
    session_factory: async_sessionmaker,
    copywriter,
) -> Router:
    router = Router()

    def _is_admin_msg(message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in settings.admin_user_ids)

    def _is_admin_cb(callback: CallbackQuery) -> bool:
        return bool(callback.from_user and callback.from_user.id in settings.admin_user_ids)

    async def _editorial_svc(session) -> EditorialService:
        return EditorialService(session, settings, copywriter)

    async def _show_main_menu(callback: CallbackQuery, state: FSMContext, text: str) -> None:
        await state.clear()
        if callback.message:
            await _replace_callback_message(callback.message, text, reply_markup=_main_menu())

    @router.message(Command("start"))
    async def cmd_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        if _is_admin_msg(message):
            await message.answer(
                "🎬 <b>TELONYX CINEMA: редакция</b>\nВыберите действие:",
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu(),
            )
            return

        await message.answer(
            "Привет! Это редакционный бот канала <b>Telonyx Cinema</b>.",
            parse_mode=ParseMode.HTML,
        )

    @router.callback_query(F.data == "menu:cancel")
    async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        await _show_main_menu(callback, state, "Действие отменено. Выберите действие:")
        await callback.answer()

    @router.callback_query(F.data == "menu:back")
    async def cb_back(callback: CallbackQuery, state: FSMContext) -> None:
        await _show_main_menu(callback, state, "Выберите действие:")
        await callback.answer()

    @router.callback_query(F.data == "editorial:queue")
    async def cb_editorial_queue(callback: CallbackQuery) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        async with session_factory() as session:
            editorial = await _editorial_svc(session)
            control = await editorial.get_or_create_control()
            posts = await editorial.queue_status(limit=12)

        pause_text = ""
        if control.paused_until:
            pause_text = f"\nПауза до: <b>{control.paused_until:%d.%m %H:%M}</b>"
        text = (
            "🎛 <b>Редакционный автопоток</b>\n"
            f"Статус: <b>{'включен' if control.autopublish_enabled else 'выключен'}</b>"
            f"{pause_text}\n\n"
        )
        if not posts:
            text += "Очередь пуста. Бот собирает новости и при необходимости сделает fallback-пост."
        else:
            lines = []
            for post in posts:
                slot = post.scheduled_for.strftime("%d.%m %H:%M") if post.scheduled_for else "ближайший слот"
                lines.append(
                    f"#{post.id} · {post.post_type.value} · {slot}\n"
                    f"<b>{post.title or 'Без заголовка'}</b>"
                )
            text += "\n\n".join(lines)

        if callback.message:
            await _replace_callback_message(
                callback.message,
                text,
                reply_markup=_main_menu(),
                parse_mode=ParseMode.HTML,
            )
        await callback.answer()

    @router.callback_query(F.data == "editorial:pause")
    async def cb_editorial_pause(callback: CallbackQuery) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        async with session_factory() as session:
            async with session.begin():
                editorial = await _editorial_svc(session)
                control = await editorial.pause_for_hours(6, now=datetime.datetime.now(settings.zoneinfo))

        if callback.message:
            await _replace_callback_message(
                callback.message,
                f"⏸ Автопоток поставлен на паузу до <b>{control.paused_until:%d.%m %H:%M}</b>.",
                reply_markup=_main_menu(),
            )
        await callback.answer("Пауза включена")

    @router.callback_query(F.data == "editorial:resume")
    async def cb_editorial_resume(callback: CallbackQuery) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        async with session_factory() as session:
            async with session.begin():
                editorial = await _editorial_svc(session)
                await editorial.set_autopublish(True)

        if callback.message:
            await _replace_callback_message(
                callback.message,
                "▶️ Автопоток снова включен.",
                reply_markup=_main_menu(),
            )
        await callback.answer("Автопоток включен")

    @router.callback_query(F.data == "editorial:publish_now")
    async def cb_editorial_publish_now(callback: CallbackQuery, bot: Bot) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        from telonyx_cinema_bot.bot.publisher import AiogramPublisher

        async with session_factory() as session:
            async with session.begin():
                editorial = await _editorial_svc(session)
                post = await editorial.maybe_publish_next(
                    AiogramPublisher(bot, settings.telegram_channel_id),
                    now=datetime.datetime.now(settings.zoneinfo),
                )

        text = "🚀 Пост опубликован." if post else "Пока нечего публиковать или автопоток на паузе."
        if callback.message:
            await _replace_callback_message(callback.message, text, reply_markup=_main_menu())
        await callback.answer(text)

    @router.callback_query(F.data == "manual:start")
    async def cb_manual_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        await state.set_state(ManualPostStates.waiting_for_post)
        if callback.message:
            await _replace_callback_message(
                callback.message,
                "📰 <b>Ручной пост</b>\nПришлите готовый пост с фото, видео или текстом.",
                parse_mode=ParseMode.HTML,
                reply_markup=_cancel_menu(),
            )
        await callback.answer()

    @router.message(StateFilter(ManualPostStates.waiting_for_post))
    async def fsm_receive_manual_post(message: Message, state: FSMContext) -> None:
        if not _is_admin_msg(message):
            return

        text = message.html_text or message.text or ""
        if not text and not message.photo and not message.video:
            await message.answer("⚠️ Пустое сообщение.", reply_markup=_cancel_menu())
            return

        await state.update_data(
            source_chat_id=message.chat.id,
            source_message_id=message.message_id,
        )
        await state.set_state(ManualPostStates.waiting_for_confirmation)

        confirm_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Опубликовать", callback_data="manual:publish")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:cancel")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")],
            ]
        )
        await message.copy_to(message.chat.id, reply_markup=confirm_kb)

    @router.callback_query(StateFilter(ManualPostStates.waiting_for_confirmation), F.data == "manual:publish")
    async def fsm_manual_publish(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if not _is_admin_cb(callback):
            return

        data = await state.get_data()
        source_chat_id = data.get("source_chat_id")
        source_message_id = data.get("source_message_id")
        await state.clear()

        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("⏳ Публикую пост...")

        try:
            await bot.copy_message(
                chat_id=settings.telegram_channel_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
            )
            text_res = "✅ Пост опубликован."
        except Exception as exc:
            text_res = f"❌ Ошибка публикации: {exc}"

        if callback.message:
            await callback.message.answer(text_res, reply_markup=_main_menu())
        await callback.answer()

    @router.callback_query(F.data == "shorts:add")
    async def cb_shorts_add(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        await state.set_state(AddShortsStates.waiting_for_url)
        if callback.message:
            await _replace_callback_message(
                callback.message,
                "🎬 <b>Добавить Shorts</b>\n"
                "Пришлите ссылку на YouTube Shorts.\n\n"
                "Бот скачает видео, наложит плашку с названием фильма, "
                "опубликует в TikTok и Telegram по расписанию.",
                parse_mode=ParseMode.HTML,
                reply_markup=_cancel_menu(),
            )
        await callback.answer()

    @router.message(StateFilter(AddShortsStates.waiting_for_url))
    async def fsm_receive_shorts_url(message: Message, state: FSMContext) -> None:
        if not _is_admin_msg(message):
            return

        url = (message.text or "").strip()
        if not url.startswith("http"):
            await message.answer("⚠️ Нужна ссылка (начинается с http).", reply_markup=_cancel_menu())
            return

        async with session_factory() as session:
            async with session.begin():
                item = ShortsQueue(url=url, status=ShortsQueueStatus.pending)
                session.add(item)
                await session.flush()
                item_id = item.id

            msg = await message.answer(
                f"📥 Shorts #{item_id} добавлен в очередь.\n"
                f"URL: {url}\n"
                "Статус: <b>ожидает обработки</b>",
                parse_mode=ParseMode.HTML,
            )
            async with session.begin():
                item = await session.get(ShortsQueue, item_id)
                item.admin_msg_id = msg.message_id

        await state.clear()

    @router.callback_query(F.data.startswith("shorts:retry:"))
    async def cb_shorts_retry(callback: CallbackQuery) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        item_id = int(callback.data.split(":")[2])
        async with session_factory() as session:
            async with session.begin():
                item = await session.get(ShortsQueue, item_id)
                if item is None:
                    await callback.answer("Запись не найдена.", show_alert=True)
                    return
                item.status = ShortsQueueStatus.pending
                item.error_message = None

        if callback.message:
            await _replace_callback_message(
                callback.message,
                f"🔄 Shorts #{item_id} поставлен в очередь на повторную обработку.",
            )
        await callback.answer()

    return router


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
