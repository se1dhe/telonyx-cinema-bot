from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

BUNDLED_COOKIES_DIR = Path(__file__).resolve().parent.parent / "tiktok_cookies"


def _ensure_cookie_file(account_name: str, tiktok_data: Path) -> None:
    target = tiktok_data / f"TK_cookies_{account_name}.json"
    if target.exists():
        return
    bundled = BUNDLED_COOKIES_DIR / f"TK_cookies_{account_name}.json"
    if bundled.exists():
        tiktok_data.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(bundled), str(target))
        logger.info("Copied bundled cookies to %s", target)


async def upload_to_tiktok(video_path: Path, description: str, account_name: str, storage_dir: Path) -> bool:
    loop = asyncio.get_running_loop()

    def _sync_upload() -> bool:
        original_cwd = os.getcwd()
        tiktok_data = storage_dir / "tiktok"
        tiktok_data.mkdir(parents=True, exist_ok=True)
        _ensure_cookie_file(account_name, tiktok_data)
        os.chdir(str(tiktok_data))

        try:
            from tiktokautouploader import TikTokUploadError
            from tiktokautouploader import upload_tiktok as tk_upload

            kwargs = dict(
                video=str(video_path),
                description=description,
                accountname=account_name,
                headless=True,
                stealth=True,
                suppressprint=False,
                copyrightcheck=True,
            )
            tk_upload(**kwargs)
            return True
        except TikTokUploadError:
            logger.exception("TikTok rejected the upload")
            return False
        except Exception:
            logger.exception("TikTok upload failed unexpectedly")
            return False
        finally:
            os.chdir(original_cwd)

    return await loop.run_in_executor(None, _sync_upload)
