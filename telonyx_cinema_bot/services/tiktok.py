from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


class TikTokError(Exception):
    pass


class TikTokClient:
    def __init__(self, access_token: str, client_key: str | None = None, client_secret: str | None = None) -> None:
        self.access_token = access_token
        self.client_key = client_key
        self.client_secret = client_secret
        self._http = httpx.AsyncClient(timeout=300.0)

    async def close(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, **kwargs) -> dict:
        url = f"{TIKTOK_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        resp = await self._http.post(url, headers=headers, **kwargs)
        data = resp.json()
        if resp.status_code != 200 or data.get("error", {}).get("code"):
            err = data.get("error", {}).get("message", resp.text)
            raise TikTokError(f"TikTok API error {resp.status_code}: {err}")
        return data.get("data", {})

    async def publish_video(self, video_path: Path, caption: str) -> str:
        upload_info = await self._init_upload()
        upload_url = upload_info["upload_url"]
        publish_id = upload_info["publish_id"]

        await self._upload_file(upload_url, video_path)

        await self._check_status(publish_id)

        result = await self._publish(publish_id, caption)
        return result.get("id", "")

    async def _init_upload(self) -> dict:
        data = {
            "source_info": {"source": "FILE_UPLOAD", "video_size": 0, "chunk_size": 0, "total_chunk_count": 0},
        }
        result = await self._post("/video/upload/", json=data)
        return result

    async def _upload_file(self, upload_url: str, video_path: Path) -> None:
        with open(video_path, "rb") as f:
            video_data = f.read()
        resp = await self._http.put(upload_url, content=video_data)
        if resp.status_code not in (200, 201):
            raise TikTokError(f"Video upload failed: {resp.status_code} {resp.text[:500]}")

    async def _check_status(self, publish_id: str) -> None:
        import asyncio

        for _ in range(30):
            resp = await self._http.get(
                f"{TIKTOK_API_BASE}/video/publish/status/",
                params={"publish_id": publish_id},
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            data = resp.json()
            status = data.get("data", {}).get("status")
            if status == "COMPLETE":
                return
            if status in ("FAILED",):
                raise TikTokError(f"TikTok upload failed: {data}")
            await asyncio.sleep(2)
        raise TikTokError("TikTok upload status check timed out")

    async def _publish(self, publish_id: str, caption: str) -> dict:
        result = await self._post(
            "/video/publish/",
            json={"publish_id": publish_id, "title": caption, "privacy_level": "PUBLIC_TO_EVERYONE"},
        )
        return result
