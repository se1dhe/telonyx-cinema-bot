from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yt_dlp

from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.models import ShortsQueue, ShortsQueueStatus
from telonyx_cinema_bot.services.gemini import GeminiCopywriter
from telonyx_cinema_bot.services.overlay import render_with_overlay
from telonyx_cinema_bot.services.tiktok_uploader import upload_to_tiktok
from telonyx_cinema_bot.services.tmdb import TMDbClient

logger = logging.getLogger(__name__)


async def extract_yt_metadata(url: str, yt_dlp_bin: str) -> dict[str, Any] | None:
    cmd = [
        yt_dlp_bin,
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        url,
    ]
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


async def download_video(url: str, output_dir: Path, yt_dlp_bin: str) -> Path:
    output_template = str(output_dir / "%(id)s.%(ext)s")
    cmd = [
        yt_dlp_bin,
        "--no-playlist",
        "--merge-output-format", "mp4",
        "--remux-video", "mp4",
        "--format", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
        "--output", output_template,
        url,
    ]
    logger.info("Downloading video: %s", " ".join(cmd))
    await asyncio_subprocess(cmd)

    for f in output_dir.iterdir():
        if f.suffix in (".mp4", ".mkv", ".webm") and not f.name.startswith("."):
            return f
    raise RuntimeError("No video file found after download")


def parse_movie_from_title(raw_title: str) -> str:
    cleaned = re.sub(r"#\S+", "", raw_title)
    cleaned = re.sub(r"@\S+", "", cleaned)
    cleaned = re.sub(r"(shorts|youtube|ytshorts)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[|–—\-•·]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for prefix in ["обзор", "реакция", "разбор", "кинопересказ", "кино", "фильм", "момент из"]:
        cleaned = re.sub(rf"^{prefix}\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()[:120]


async def generate_shorts_description(
    movie_title: str,
    movie_year: str,
    movie_genre: str,
    copywriter: GeminiCopywriter,
) -> str:
    prompt = (
        "Напиши короткое описание для поста в Telegram с кино-видео.\n"
        "Формат:\n"
        f"{movie_title} | краткое описание момента 🔥 Наш тг: @telonyx_cinema\n\n"
        "Потом добавь 5-7 виральных хештегов по теме (на русском и английском, через пробел).\n"
        f"Фильм: {movie_title} ({movie_year}), жанр: {movie_genre}.\n"
        "Только текст и хештеги, без лишнего."
    )
    try:
        text = await copywriter._generate_text(prompt)
        return text.strip()
    except Exception:
        return f"{movie_title} | 🔥 Наш тг: @telonyx_cinema\n#кино #фильм #telonyxcinema"


async def process_shorts_item(
    item_id: int,
    session: Any,
    bot: Any,
    settings: Settings,
    copywriter: GeminiCopywriter,
) -> None:
    from sqlalchemy import select

    result = await session.execute(select(ShortsQueue).where(ShortsQueue.id == item_id))
    item: ShortsQueue | None = result.scalar_one_or_none()
    if item is None:
        logger.warning("ShortsQueue item %s not found", item_id)
        return

    work_dir = Path(settings.storage_dir) / "shorts" / str(item_id)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        item.status = ShortsQueueStatus.downloading
        await session.flush()

        video_path = await download_video(item.url, work_dir, settings.yt_dlp_bin)

        if not item.movie_title:
            raw_meta = yt_dlp.YoutubeDL().extract_info(item.url, download=False)
            raw_title = raw_meta.get("title", "")
            parsed = parse_movie_from_title(raw_title)
            tmdb = TMDbClient(settings.tmdb_api_key)
            movie = await tmdb.search_best_match(parsed)
            if movie:
                item.movie_title = movie.title
                item.movie_year = str(movie.release_year or "")
                item.movie_genre = ", ".join(movie.genres[:3]) if movie.genres else ""
                item.tmdb_id = movie.tmdb_id
            else:
                item.movie_title = parsed
                item.movie_year = ""
                item.movie_genre = ""

        item.status = ShortsQueueStatus.rendering
        await session.flush()

        output_path = work_dir / "final.mp4"
        await render_with_overlay(
            ffmpeg_bin=settings.ffmpeg_bin,
            ffprobe_bin=settings.ffprobe_bin,
            input_path=video_path,
            output_path=output_path,
            work_dir=work_dir,
            movie_title=item.movie_title or "",
            movie_year=item.movie_year or "",
            movie_genre=item.movie_genre or "",
        )

        description = await generate_shorts_description(
            item.movie_title or "",
            item.movie_year or "",
            item.movie_genre or "",
            copywriter,
        )

        item.status = ShortsQueueStatus.ready
        await session.flush()

        if settings.tiktok_account_name:
            logger.info("Uploading to TikTok as %s", settings.tiktok_account_name)
            storage_dir = Path(settings.storage_dir)
            tiktok_ok = await upload_to_tiktok(
                video_path=output_path,
                description=description,
                account_name=settings.tiktok_account_name,
                storage_dir=storage_dir,
            )
            if tiktok_ok:
                logger.info("TikTok upload complete")
            else:
                logger.warning("TikTok upload failed, continuing to Telegram")

        from aiogram.types import FSInputFile

        msg = await bot.send_video(
            settings.telegram_channel_id,
            video=FSInputFile(str(output_path)),
            caption=description,
            parse_mode="HTML",
            supports_streaming=True,
        )

        item.telegram_file_id = msg.video.file_id
        item.video_path = str(output_path)
        item.status = ShortsQueueStatus.published
        item.published_at = datetime.now(timezone.utc)

        if item.admin_msg_id:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            await bot.edit_message_text(
                chat_id=settings.admin_user_ids[0] if settings.admin_user_ids else 0,
                message_id=item.admin_msg_id,
                text=f"✅ Опубликовано: {item.movie_title}\n{msg.get_url()}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="📺 Посмотреть", url=msg.get_url())]]
                ),
                disable_web_page_preview=True,
            )

    except Exception as exc:
        logger.exception("Failed to process shorts item %s", item_id)
        item.status = ShortsQueueStatus.failed
        item.error_message = str(exc)[:1000]

        if settings.admin_user_ids:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            admin_id = settings.admin_user_ids[0]
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Заменить видео", callback_data=f"shorts:retry:{item_id}")],
                ]
            )
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
        await session.flush()
