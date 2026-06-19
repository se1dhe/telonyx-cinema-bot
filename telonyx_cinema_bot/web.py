from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from telonyx_cinema_bot.config import Settings


def build_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    storage_dir = Path(settings.storage_dir)

    @app.get("/shorts/{item_id}")
    async def download_shorts(item_id: int) -> FileResponse:
        path = storage_dir / "shorts" / str(item_id) / "final.mp4"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(
            str(path),
            media_type="video/mp4",
            filename=f"shorts_{item_id}.mp4",
        )

    @app.get("/downloads/{download_id}")
    async def download_video(download_id: str) -> FileResponse:
        path = storage_dir / "downloads" / download_id / "video.mp4"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(
            str(path),
            media_type="video/mp4",
            filename=f"video_{download_id}.mp4",
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
