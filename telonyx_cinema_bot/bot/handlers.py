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
from telonyx_cinema_bot.services.shorts import process_shorts_item


class ManualPostStates(StatesGroup):
    waiting_for_post = State()
    waiting_for_confirmation = State()


class AddShortsStates(StatesGroup):
    waiting_for_url = State()
    waiting_for_movie_title = State()
    waiting_for_movie_year = State()
    waiting_for_next_url = State()


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
            [InlineKeyboardButton(text="📹 Shorts очередь", callback_data="shorts:queue")],
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
                "отправит готовое видео и подпись для TikTok вам в личку.",
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
                from sqlalchemy import select
                from datetime import timedelta

                last_time = await session.scalar(
                    select(ShortsQueue.scheduled_for)
                    .where(ShortsQueue.status.in_([ShortsQueueStatus.pending, ShortsQueueStatus.published]))
                    .order_by(ShortsQueue.scheduled_for.desc())
                    .limit(1)
                )
                if last_time is None:
                    last_time = await session.scalar(
                        select(ShortsQueue.published_at)
                        .where(ShortsQueue.status == ShortsQueueStatus.published)
                        .order_by(ShortsQueue.published_at.desc())
                        .limit(1)
                    )
                now = datetime.datetime.now(settings.zoneinfo)
                if last_time:
                    next_slot = max(now, last_time + timedelta(minutes=settings.shorts_interval_minutes))
                else:
                    next_slot = now

                item = ShortsQueue(url=url, status=ShortsQueueStatus.pending, scheduled_for=next_slot)
                session.add(item)
                await session.flush()
                item_id = item.id

            msg = await message.answer(
                f"📥 Shorts #{item_id} добавлен в очередь.\n"
                f"URL: {url}\n"
                "Статус: <b>ожидает обработки</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="🚀 Опубликовать сейчас", callback_data=f"shorts:publish_now:{item_id}"),
                            InlineKeyboardButton(text="➕ Добавить еще", callback_data="shorts:add"),
                        ],
                    ]
                ),
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
                from sqlalchemy import select
                from datetime import timedelta

                item = await session.get(ShortsQueue, item_id)
                if item is None:
                    await callback.answer("Запись не найдена.", show_alert=True)
                    return

                last_slot = await session.scalar(
                    select(ShortsQueue.scheduled_for)
                    .where(ShortsQueue.status.in_([ShortsQueueStatus.pending, ShortsQueueStatus.published]))
                    .where(ShortsQueue.id != item_id)
                    .order_by(ShortsQueue.scheduled_for.desc())
                    .limit(1)
                )
                if last_slot is None:
                    last_slot = await session.scalar(
                        select(ShortsQueue.published_at)
                        .where(ShortsQueue.status == ShortsQueueStatus.published)
                        .where(ShortsQueue.id != item_id)
                        .order_by(ShortsQueue.published_at.desc())
                        .limit(1)
                    )
                now = datetime.datetime.now(settings.zoneinfo)
                if last_slot:
                    next_slot = max(now, last_slot + timedelta(minutes=settings.shorts_interval_minutes))
                else:
                    next_slot = now

                item.status = ShortsQueueStatus.pending
                item.error_message = None
                item.scheduled_for = next_slot

        if callback.message:
            await _replace_callback_message(
                callback.message,
                f"🔄 Shorts #{item_id} поставлен в очередь на повторную обработку.",
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("shorts:identify:"))
    async def cb_shorts_identify(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        item_id = int(callback.data.split(":")[2])
        await state.update_data(shorts_item_id=item_id)
        await state.set_state(AddShortsStates.waiting_for_movie_title)
        await callback.message.answer(
            f"🎬 Shorts #{item_id}\n"
            "Введи <b>название фильма/сериала</b> по-русски:",
            parse_mode=ParseMode.HTML,
        )
        await callback.answer()

    @router.message(StateFilter(AddShortsStates.waiting_for_movie_title))
    async def fsm_receive_movie_title(message: Message, state: FSMContext) -> None:
        if not _is_admin_msg(message):
            return
        title = (message.text or "").strip()
        if not title:
            await message.answer("Название не может быть пустым. Попробуй ещё раз:")
            return
        await state.update_data(movie_title=title)
        await state.set_state(AddShortsStates.waiting_for_movie_year)
        await message.answer("Теперь введи <b>год выпуска</b> (или 0, если не знаешь):", parse_mode=ParseMode.HTML)

    @router.message(StateFilter(AddShortsStates.waiting_for_movie_year))
    async def fsm_receive_movie_year(message: Message, state: FSMContext) -> None:
        if not _is_admin_msg(message):
            return
        year_raw = (message.text or "").strip()
        if not year_raw.isdigit():
            await message.answer("Год должен быть числом. Попробуй ещё раз:")
            return
        data = await state.get_data()
        item_id = data.get("shorts_item_id")
        title = data.get("movie_title", "")
        year = year_raw if year_raw != "0" else ""
        await state.clear()

        async with session_factory() as session:
            async with session.begin():
                item = await session.get(ShortsQueue, item_id)
                if item is None:
                    await message.answer(f"❌ Shorts #{item_id} не найден в базе.")
                    return
                item.movie_title = title
                item.movie_year = year
                item.status = ShortsQueueStatus.pending
                item.error_message = None

        await message.answer(
            f"✅ Shorts #{item_id}: <b>{title}</b> ({year or 'год неизвестен'})\n"
            "Поставлен в очередь на повторную обработку.",
            parse_mode=ParseMode.HTML,
        )

    @router.callback_query(F.data == "shorts:next_video")
    async def cb_shorts_next_video(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return
        await state.set_state(AddShortsStates.waiting_for_next_url)
        if callback.message:
            await _replace_callback_message(
                callback.message,
                "🎬 <b>Следующее видео</b>\nПришли ссылку на YouTube Shorts.",
                reply_markup=_cancel_menu(),
                parse_mode="HTML",
            )
        await callback.answer()

    @router.message(StateFilter(AddShortsStates.waiting_for_next_url))
    async def fsm_receive_next_url(message: Message, state: FSMContext, bot: Bot) -> None:
        if not _is_admin_msg(message):
            return
        url = (message.text or "").strip()
        if not url.startswith("http"):
            await message.answer("⚠️ Нужна ссылка (начинается с http).", reply_markup=_cancel_menu())
            return

        from sqlalchemy import select
        from datetime import timedelta
        from datetime import datetime
        from telonyx_cinema_bot.services.shorts import process_shorts_item

        async with session_factory() as session:
            async with session.begin():
                now = datetime.now(settings.zoneinfo)
                item = ShortsQueue(url=url, status=ShortsQueueStatus.pending, scheduled_for=now)
                session.add(item)
                await session.flush()
                item_id = item.id

        try:
            async with session_factory() as session:
                async with session.begin():
                    item = await session.get(ShortsQueue, item_id)
                    if item is not None:
                        item.status = ShortsQueueStatus.downloading

            async with session_factory() as session:
                await process_shorts_item(item_id, session, bot, settings, copywriter, target_admin_id=message.from_user.id)

        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).exception("Next video processing failed for shorts %s", item_id)
            await bot.send_message(message.from_user.id, f"❌ Ошибка при обработке Shorts #{item_id}:\n{str(exc)[:300]}")
        finally:
            await state.clear()

    @router.callback_query(F.data == "shorts:queue")
    async def cb_shorts_queue(callback: CallbackQuery) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        from sqlalchemy import select

        async with session_factory() as session:
            result = await session.execute(
                select(ShortsQueue)
                .where(ShortsQueue.status.in_([ShortsQueueStatus.pending, ShortsQueueStatus.failed]))
                .order_by(ShortsQueue.id.desc())
                .limit(20)
            )
            items = list(result.scalars())

        if not items:
            text = "📹 Shorts очередь пуста."
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Обновить", callback_data="shorts:queue")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")],
                ]
            )
        else:
            text_lines = ["📹 <b>Shorts очередь</b>\n\n"]
            item_buttons = []
            for item in items:
                slot = ""
                if item.scheduled_for:
                    slot = f" · ⏰ {item.scheduled_for:%d.%m %H:%M}"
                status_icon = "⏳" if item.status == ShortsQueueStatus.pending else "❌"
                line = (
                    f"{status_icon} #{item.id} · {item.status.value}{slot}\n"
                    f"🔗 {item.url[:60]}\n"
                )
                if item.movie_title:
                    line += f"🎬 {item.movie_title}\n"
                text_lines.append(line)
                item_buttons.append(
                    [InlineKeyboardButton(text=f"🚀 Опублик. #{item.id}", callback_data=f"shorts:publish_now:{item.id}")]
                )
            text = "\n".join(text_lines)

            kb = InlineKeyboardMarkup(
                inline_keyboard=item_buttons + [
                    [InlineKeyboardButton(text="🔄 Обновить", callback_data="shorts:queue")],
                    [InlineKeyboardButton(text="🗑 Очистить очередь", callback_data="shorts:clear")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")],
                ]
            )
        if callback.message:
            await _replace_callback_message(callback.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
        await callback.answer()

    @router.callback_query(F.data.startswith("shorts:publish_now:"))
    async def cb_shorts_publish_now(callback: CallbackQuery, bot: Bot) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        item_id = int(callback.data.split(":")[2])
        admin_id = callback.from_user.id

        await callback.answer("Запускаю публикацию...")

        if callback.message:
            await _replace_callback_message(
                callback.message,
                f"⏳ Обработка Shorts #{item_id}...",
            )

        try:
            async with session_factory() as session:
                async with session.begin():
                    item = await session.get(ShortsQueue, item_id)
                    if item is None or item.status not in (ShortsQueueStatus.pending, ShortsQueueStatus.failed):
                        await bot.send_message(admin_id, "❌ Запись не найдена или уже обрабатывается.")
                        return
                    item.status = ShortsQueueStatus.downloading

            async with session_factory() as session:
                await process_shorts_item(item_id, session, bot, settings, copywriter, target_admin_id=admin_id)

            async with session_factory() as session:
                item = await session.get(ShortsQueue, item_id)
                next_btn = InlineKeyboardButton(text="⏭ Следующее видео", callback_data="shorts:next_video")
                msg_parts = [f"✅ Shorts #{item_id} обработан."]
                if item and item.status == ShortsQueueStatus.published:
                    msg_parts.append("📢 Telegram: опубликовано")
                    msg_parts.append("📤 Видео отправлено администратору")
                elif item and item.status == ShortsQueueStatus.failed:
                    msg_parts.append(f"❌ Ошибка: {item.error_message or 'неизвестно'}")
                else:
                    msg_parts.append(f"⚠️ Статус: {item.status.value if item else '???'}")

                await bot.send_message(
                    admin_id,
                    "\n".join(msg_parts),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[next_btn]]),
                )

        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).exception("Manual publish failed for shorts %s", item_id)
            await bot.send_message(admin_id, "❌ Ошибка при публикации Shorts #{}:\n{}".format(item_id, str(exc)[:300]))

    @router.callback_query(F.data == "shorts:clear")
    async def cb_shorts_clear(callback: CallbackQuery) -> None:
        if not _is_admin_cb(callback):
            await callback.answer("Только для администраторов.", show_alert=True)
            return

        from sqlalchemy import delete

        async with session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(ShortsQueue)
                    .where(ShortsQueue.status.in_([ShortsQueueStatus.pending, ShortsQueueStatus.failed]))
                )
                deleted_count = result.rowcount

        await callback.answer(f"Удалено {deleted_count} записей.", show_alert=True)
        if callback.message:
            await _replace_callback_message(
                callback.message,
                "🗑 Очередь shorts очищена.",
                reply_markup=_main_menu(),
            )

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
