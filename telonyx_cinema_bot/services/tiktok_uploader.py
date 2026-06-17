from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


async def upload_to_tiktok(video_path: Path, description: str, account_name: str, storage_dir: Path) -> bool:
    loop = asyncio.get_running_loop()

    def _sync_upload() -> bool:
        original_cwd = os.getcwd()
        tiktok_data = storage_dir / "tiktok"
        tiktok_data.mkdir(parents=True, exist_ok=True)
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
