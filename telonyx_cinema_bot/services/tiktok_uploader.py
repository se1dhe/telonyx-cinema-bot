from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def init_tiktok_session(account_name: str, storage_dir: Path) -> bool:
    import json
    import pickle

    try:
        cookies_dir = storage_dir / "tiktok" / "CookiesDir"
        cookies_dir.mkdir(parents=True, exist_ok=True)
        cookie_file = cookies_dir / f"tiktok_session-{account_name}.cookie"

        env_cookies = os.environ.get("TIKTOK_SESSION_COOKIE_BASE64")
        bundled_dir = Path(__file__).resolve().parent.parent / "tiktok_cookies"
        old_json = bundled_dir / f"TK_cookies_{account_name}.json"

        # Если есть свежий источник (env или bundled JSON) — сбрасываем старый файл,
        # чтобы избежать проблемы с устаревшими/битыми куками на persistent storage.
        if env_cookies or old_json.exists():
            if cookie_file.exists():
                cookie_file.unlink()
                logger.info("Removed stale cookie file for %s", account_name)

        if env_cookies:
            try:
                data = base64.b64decode(env_cookies)
                cookie_file.write_bytes(data)
                logger.info("Loaded TikTok session cookie for %s from env", account_name)
                return True
            except Exception:
                logger.exception("Failed to decode TIKTOK_SESSION_COOKIE_BASE64")

        # 2. Try converting bundled JSON cookies to pickle
        bundled_dir = Path(__file__).resolve().parent.parent / "tiktok_cookies"
        old_json = bundled_dir / f"TK_cookies_{account_name}.json"
        if old_json.exists():
            try:
                cookies = json.loads(old_json.read_text(encoding="utf-8"))
                cookie_file.write_bytes(pickle.dumps(cookies))
                logger.info("Converted JSON cookies to pickle for %s", account_name)
                return True
            except Exception:
                logger.exception("Failed to convert bundled cookies for %s", account_name)

        logger.warning(
            "No TikTok session cookie for %s. "
            "Log in locally: 'python cli.py login -n %s' "
            "then base64-encode CookiesDir/tiktok_session-%s.cookie "
            "and set TIKTOK_SESSION_COOKIE_BASE64 env var.",
            account_name, account_name, account_name,
        )
        return False
    except SystemExit:
        logger.error("TikTok session init triggered sys.exit for %s", account_name)
        return False
    except Exception:
        logger.exception("TikTok session init failed for %s", account_name)
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
    import io
    from contextlib import redirect_stdout

    try:
        from tiktok_uploader import tiktok
        from tiktok_uploader.Config import Config

        # Point library paths into persistent storage.
        # Config is a singleton — class-level assignments like Config.COOKIES_DIR = ...
        # DON'T affect the _options dict that the singleton properties actually read.
        cookies_dir = storage_dir / "tiktok" / "CookiesDir"
        videos_dir = storage_dir / "tiktok" / "VideosDirPath"
        cookies_dir.mkdir(parents=True, exist_ok=True)
        videos_dir.mkdir(parents=True, exist_ok=True)

        config = Config.get()
        config._options["COOKIES_DIR"] = str(cookies_dir)
        config._options["VIDEOS_DIR"] = str(videos_dir)
        config._options["POST_PROCESSING_VIDEO_PATH"] = str(videos_dir)

        if not init_tiktok_session(account_name, storage_dir):
            return False

        # Библиотека печатает ответы TikTok в stdout — перехватываем их в лог
        buf = io.StringIO()
        with redirect_stdout(buf):
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
        library_output = buf.getvalue()
        if library_output:
            # Показываем последние 2kb вывода библиотеки
            logger.info("TikTok library output:\n%s", library_output.strip()[-2048:])
            # Парсим URL из строки "Published successfully!  ID=...  URL=..."
            if "Published successfully" in library_output:
                import re as _re
                m = _re.search(r'URL=(\S+)', library_output)
                url = m.group(1) if m else ""
                if url:
                    logger.info("TikTok video URL: %s", url)

        if ok:
            logger.info("TikTok upload ok for %s", account_name)
            return True
        else:
            logger.warning("TikTok upload returned falsy for %s", account_name)
            return False
    except SystemExit as exc:
        # The tiktok-autouploader library calls sys.exit(1) on auth failure.
        # We must NOT let it kill the entire bot process.
        logger.error(
            "TikTok upload triggered sys.exit(%s) for %s — treating as failure",
            exc.code if hasattr(exc, "code") else "?",
            account_name,
        )
        return False
    except Exception:
        logger.exception("TikTok upload failed for %s", account_name)
        return False
