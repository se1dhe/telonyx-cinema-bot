from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def init_tiktok_session(account_name: str, storage_dir: Path) -> bool:
    cookies_dir = storage_dir / "tiktok" / "CookiesDir"
    cookies_dir.mkdir(parents=True, exist_ok=True)
    cookie_file = cookies_dir / f"tiktok_session-{account_name}.cookie"

    if cookie_file.exists():
        return True

    env_cookies = os.environ.get("TIKTOK_SESSION_COOKIE_BASE64")
    if env_cookies:
        try:
            data = base64.b64decode(env_cookies)
            cookie_file.write_bytes(data)
            logger.info("Loaded TikTok session cookie for %s", account_name)
            return True
        except Exception:
            logger.exception("Failed to decode TIKTOK_SESSION_COOKIE_BASE64")
    else:
        logger.warning(
            "No TikTok session cookie for %s. "
            "Log in locally: 'python cli.py login -n %s' "
            "then base64-encode CookiesDir/tiktok_session-%s.cookie "
            "and set TIKTOK_SESSION_COOKIE_BASE64 env var.",
            account_name, account_name, account_name,
        )

    return False


async def upload_to_tiktok(
    video_path: Path,
    title: str,
    account_name: str,
    storage_dir: Path,
) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _sync_upload,
        video_path,
        title,
        account_name,
        storage_dir,
    )


def _sync_upload(
    video_path: Path,
    title: str,
    account_name: str,
    storage_dir: Path,
) -> bool:
    try:
        from tiktok_uploader import tiktok
        from tiktok_uploader.Config import Config

        # Point library paths into persistent storage
        cookies_dir = storage_dir / "tiktok" / "CookiesDir"
        videos_dir = storage_dir / "tiktok" / "VideosDirPath"
        cookies_dir.mkdir(parents=True, exist_ok=True)
        videos_dir.mkdir(parents=True, exist_ok=True)

        Config.COOKIES_DIR = str(cookies_dir)
        Config.VIDEOS_DIR = str(videos_dir)
        Config.POST_PROCESSING_VIDEO_PATH = str(videos_dir)

        if not init_tiktok_session(account_name, storage_dir):
            return False

        ok = tiktok.upload_video(
            session_user=account_name,
            video=str(video_path),
            title=title,
            schedule_time=0,
            allow_comment=1,
            allow_duet=0,
            allow_stitch=0,
            visibility_type=0,
            brand_organic_type=0,
            branded_content_type=0,
            ai_label=0,
            proxy=None,
        )

        if ok:
            logger.info("TikTok upload ok for %s", account_name)
            return True
        else:
            logger.warning("TikTok upload returned falsy for %s", account_name)
            return False
    except Exception:
        logger.exception("TikTok upload failed for %s", account_name)
        return False
