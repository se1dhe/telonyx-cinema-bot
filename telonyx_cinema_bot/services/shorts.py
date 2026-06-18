from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.models import ShortsQueue, ShortsQueueStatus
from telonyx_cinema_bot.services.gemini import GeminiCopywriter
from telonyx_cinema_bot.services.overlay import render_with_overlay
from telonyx_cinema_bot.services.tmdb import TMDbClient

logger = logging.getLogger(__name__)

_COOKIES_PATH: Path | None = None


def init_cookies_file(settings: Settings) -> str | None:
    global _COOKIES_PATH
    if _COOKIES_PATH is not None:
        return str(_COOKIES_PATH)

    if settings.yt_dlp_cookies_file:
        _COOKIES_PATH = Path(settings.yt_dlp_cookies_file)
        if _COOKIES_PATH.exists():
            return str(_COOKIES_PATH)
        logger.warning("YT_DLP_COOKIES_FILE %s not found", _COOKIES_PATH)
        _COOKIES_PATH = None

    if settings.yt_dlp_cookies_base64:
        try:
            decoded = base64.b64decode(settings.yt_dlp_cookies_base64).decode("utf-8")
            path = Path(settings.storage_dir) / "yt-dlp-cookies.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(decoded, encoding="utf-8")
            path.chmod(0o600)
            _COOKIES_PATH = path
            logger.info("Decoded YT_DLP_COOKIES_BASE64 to %s", path)
            return str(path)
        except Exception:
            logger.exception("Failed to decode YT_DLP_COOKIES_BASE64")

    return None


def _cookies_args(cookies_path: str | None) -> list[str]:
    if cookies_path:
        return ["--cookies", cookies_path]
    return []


async def extract_yt_metadata(url: str, yt_dlp_bin: str, *, cookies: str | None = None) -> dict[str, Any] | None:
    cmd = [
        yt_dlp_bin,
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        "--remote-components", "ejs:npm",
    ]
    cmd.extend(_cookies_args(cookies))
    cmd.append(url)
    proc = await asyncio_subprocess(cmd)
    try:
        return json.loads(proc)
    except (json.JSONDecodeError, RuntimeError):
        logger.exception("Failed to extract metadata for %s", url)
        return None


async def asyncio_subprocess(cmd: list[str]) -> str:
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{stderr.decode()[-2000:]}")
    return stdout.decode().strip()


async def download_video(url: str, output_dir: Path, yt_dlp_bin: str, *, cookies: str | None = None) -> Path:
    output_template = str(output_dir / "%(id)s.%(ext)s")
    cmd = [
        yt_dlp_bin,
        "--no-playlist",
        "--merge-output-format", "mp4",
        "--remux-video", "mp4",
        "--remote-components", "ejs:npm",
        "--format", "bestvideo+bestaudio/best",
        "--output", output_template,
    ]
    cmd.extend(_cookies_args(cookies))
    cmd.append(url)
    logger.info("Downloading video: %s", " ".join(cmd))
    await asyncio_subprocess(cmd)

    for f in output_dir.iterdir():
        if f.suffix in (".mp4", ".mkv", ".webm") and not f.name.startswith("."):
            return f
    raise RuntimeError("No video file found after download")


async def process_shorts_item(
    item_id: int,
    session: Any,
    bot: Any,
    settings: Settings,
    copywriter: GeminiCopywriter,
    *,
    target_admin_id: int | None = None,
) -> None:
    from sqlalchemy import select

    result = await session.execute(select(ShortsQueue).where(ShortsQueue.id == item_id))
    item: ShortsQueue | None = result.scalar_one_or_none()
    if item is None:
        logger.warning("ShortsQueue item %s not found", item_id)
        return

    work_dir = Path(settings.storage_dir) / "shorts" / str(item_id)
    work_dir.mkdir(parents=True, exist_ok=True)

    cookies_path = init_cookies_file(settings)

    try:
        admin_id = target_admin_id or (settings.admin_user_ids[0] if settings.admin_user_ids else 0)
        item.status = ShortsQueueStatus.downloading
        await session.flush()

        video_path = await download_video(item.url, work_dir, settings.yt_dlp_bin, cookies=cookies_path)

        if not item.movie_title or not item.tmdb_id:
            if not item.movie_title:
                raw_meta = await extract_yt_metadata(item.url, settings.yt_dlp_bin, cookies=cookies_path)
                raw_title = (raw_meta or {}).get("title", "") or ""
                ai_title, ai_year = await copywriter.identify_movie_from_title(raw_title)
                item.yt_raw_title = raw_title
            else:
                ai_title = item.movie_title
                ai_year = item.movie_year or ""

            # Primary: TMDb search (multi-strategy)
            tmdb = TMDbClient(settings.tmdb_api_key)
            movie = await tmdb.search_best_match(ai_title, year=ai_year)

            # Fallback: OMDb → TMDb by imdbID
            if not movie and settings.omdb_api_key:
                from telonyx_cinema_bot.services.omdb import OMDbClient

                omdb = OMDbClient(settings.omdb_api_key)
                omdb_result = await omdb.search(ai_title, year=ai_year)
                if omdb_result and omdb_result.imdb_id:
                    logger.info("OMDb found %s (%s), trying TMDb find", omdb_result.imdb_id, omdb_result.title)
                    movie = await tmdb.find_by_imdb_id(omdb_result.imdb_id)

            if movie:
                item.movie_title = movie.title
                item.movie_year = str(movie.release_year or "")
                item.movie_genre = movie.genres[0] if movie.genres else ""
                item.tmdb_id = movie.tmdb_id
            else:
                item.movie_title = ai_title
                item.movie_year = ai_year or ""
                item.movie_genre = ""
                item.tmdb_id = None  # ensure no card is posted

            if not movie and not item.movie_title:
                # No title at all — stop and ask admin
                if admin_id:
                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[[
                            InlineKeyboardButton(
                                text="🎬 Указать фильм",
                                callback_data=f"shorts:identify:{item_id}",
                            )
                        ]]
                    )
                    await bot.send_message(
                        admin_id,
                        f"⚠️ Shorts #{item_id}: не удалось определить фильм.\n"
                        f"YouTube: {item.url}\n\n"
                        "Укажи фильм вручную.",
                        parse_mode="HTML",
                        reply_markup=kb,
                    )
                item.status = ShortsQueueStatus.failed
                item.error_message = "Фильм не определён"
                return

        item.status = ShortsQueueStatus.rendering
        await session.flush()

        output_path = work_dir / "final.mp4"
        await render_with_overlay(
            ffmpeg_bin=settings.ffmpeg_bin,
            input_path=video_path,
            output_path=output_path,
            work_dir=work_dir,
        )

        item.status = ShortsQueueStatus.ready
        await session.flush()

        # 4. Post Telegram card (7-day dedup)
        from telonyx_cinema_bot.services.movie_card import format_movie_card, generate_tiktok_caption
        from telonyx_cinema_bot.services.tmdb import MovieMetadata
        from datetime import timedelta

        telegram_url = settings.channel_link or f"https://t.me/{settings.telegram_channel_id.lstrip('@')}"

        card_movie: MovieMetadata | None = None
        if item.tmdb_id:
            try:
                tmdb = TMDbClient(settings.tmdb_api_key)
                card_movie = await tmdb.fetch_movie(item.tmdb_id)
            except Exception:
                logger.exception("Failed to fetch movie metadata for card")

        should_post_card = False
        if card_movie:
            seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
            recent_card = await session.scalar(
                select(ShortsQueue)
                .where(
                    ShortsQueue.tmdb_id == item.tmdb_id,
                    ShortsQueue.telegram_file_id.isnot(None),
                    ShortsQueue.published_at >= seven_days_ago,
                    ShortsQueue.id != item.id,
                )
                .limit(1)
            )
            if recent_card is None:
                should_post_card = True

        if should_post_card:
            card_text = format_movie_card(card_movie)
            poster_path: Path | None = None
            poster_url = card_movie.poster_url
            if poster_url:
                try:
                    import aiohttp

                    async with aiohttp.ClientSession() as s:
                        async with s.get(poster_url) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                poster_path = work_dir / "poster.jpg"
                                poster_path.write_bytes(data)
                except Exception:
                    logger.exception("Failed to download poster")

            if poster_path:
                from aiogram.types import FSInputFile

                caption = card_text[:1021] + "..." if len(card_text) > 1024 else card_text
                msg = await bot.send_photo(
                    settings.telegram_channel_id,
                    photo=FSInputFile(str(poster_path)),
                    caption=caption,
                    parse_mode="HTML",
                )
                item.telegram_file_id = msg.photo[-1].file_id if msg.photo else None
            else:
                msg = await bot.send_message(
                    settings.telegram_channel_id,
                    text=card_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                item.telegram_file_id = None

            telegram_url = msg.get_url()
        else:
            if card_movie:
                logger.info("Card for tmdb_id %s was posted within 7 days — skipping", item.tmdb_id)
            else:
                logger.info("No TMDb data for item %s — skipping Telegram card", item_id)
            item.telegram_file_id = None

        # 5. TikTok caption with movie title + Telegram pitch + viral hashtags
        tiktok_caption = generate_tiktok_caption(card_movie, telegram_url, fallback_title=item.movie_title or "Фильм")

        # 6. Send admin a download link + TikTok caption + Next button
        if admin_id:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            next_button = InlineKeyboardButton(text="⏭ Следующее видео", callback_data="shorts:next_video")
            if domain:
                download_link = f"{domain}/shorts/{item_id}"
                admin_text = (
                    f"🎬 <b>{item.movie_title or 'Фильм'}</b>\n\n"
                    f"📥 <a href='{download_link}'>Скачать видео</a>\n\n"
                    f"📝 <b>Подпись для TikTok (скопируйте):</b>\n"
                    f"<code>{tiktok_caption}</code>"
                )
                await bot.send_message(
                    admin_id,
                    admin_text,
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[next_button]]),
                )
            else:
                await bot.send_message(
                    admin_id,
                    f"🎬 <b>{item.movie_title or 'Фильм'}</b>\n\n"
                    f"📝 Подпись для TikTok:\n<code>{tiktok_caption}</code>\n\n"
                    f"⚠️ PUBLIC_DOMAIN не настроен — ссылку на скачивание сгенерировать не удалось.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[next_button]]),
                )

        # 7. Mark published
        item.video_path = str(output_path)
        item.status = ShortsQueueStatus.published
        item.published_at = datetime.now(timezone.utc)

        if item.admin_msg_id:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            next_button = InlineKeyboardButton(text="⏭ Следующее видео", callback_data="shorts:next_video")
            await bot.edit_message_text(
                chat_id=admin_id if admin_id else 0,
                message_id=item.admin_msg_id,
                text=f"✅ Опубликовано: {item.movie_title or '?'}\n{telegram_url}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="📺 Посмотреть", url=telegram_url)],
                        [next_button],
                    ]
                ),
                disable_web_page_preview=True,
            )

    except Exception as exc:
        logger.exception("Failed to process shorts item %s", item_id)
        item.status = ShortsQueueStatus.failed
        item.error_message = str(exc)[:1000]

        if admin_id:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            buttons = [
                [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"shorts:retry:{item_id}")],
            ]
            if not item.tmdb_id and item.movie_title:
                buttons.insert(0, [
                    InlineKeyboardButton(text="🎬 Указать фильм", callback_data=f"shorts:identify:{item_id}")
                ])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            text = (
                f"❌ Ошибка обработки Shorts #{item_id}\n"
                f"URL: {item.url}\n"
                f"Ошибка: {str(exc)[:300]}"
            )
            if item.admin_msg_id:
                await bot.edit_message_text(chat_id=admin_id, message_id=item.admin_msg_id, text=text, reply_markup=kb)
            else:
                msg = await bot.send_message(admin_id, text, reply_markup=kb)
                item.admin_msg_id = msg.message_id

    finally:
        await session.commit()



