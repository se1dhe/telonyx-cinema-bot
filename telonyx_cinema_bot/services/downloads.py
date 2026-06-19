from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.services.shorts import download_video, init_cookies_file


@dataclass(frozen=True)
class DownloadResult:
    download_id: str
    path: Path
    url: str | None


async def prepare_video_download(url: str, settings: Settings) -> DownloadResult:
    download_id = uuid4().hex
    output_dir = Path(settings.storage_dir) / "downloads" / download_id
    output_dir.mkdir(parents=True, exist_ok=False)

    cookies_path = init_cookies_file(settings)
    downloaded_path = await download_video(
        url,
        output_dir,
        settings.yt_dlp_bin,
        cookies=cookies_path,
    )

    final_path = output_dir / "video.mp4"
    if downloaded_path != final_path:
        downloaded_path.replace(final_path)

    public_domain = settings.resolved_public_domain
    public_url = f"{public_domain}/downloads/{download_id}" if public_domain else None

    return DownloadResult(download_id=download_id, path=final_path, url=public_url)
