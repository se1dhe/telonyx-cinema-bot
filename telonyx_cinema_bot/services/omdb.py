from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)


class OMDbResult:
    def __init__(self, data: dict) -> None:
        self.imdb_id: str | None = data.get("imdbID")
        self.title: str = data.get("Title") or ""
        self.year: str = data.get("Year") or ""
        self.imdb_rating: str | None = None
        raw_rating = data.get("imdbRating")
        if raw_rating and raw_rating != "N/A":
            self.imdb_rating = raw_rating


class OMDbClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://www.omdbapi.com"

    async def search(self, title: str, year: str | None = None) -> OMDbResult | None:
        params: dict[str, str] = {
            "apikey": self.api_key,
            "t": title,
            "type": "movie",
        }
        if year:
            params["y"] = year

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.base_url, params=params) as resp:
                    if resp.status != 200:
                        logger.warning("OMDb returned status %s", resp.status)
                        return None
                    data = await resp.json()
                    if data.get("Response") != "True":
                        logger.info("OMDb not found: %s", data.get("Error", "unknown"))
                        return None
                    return OMDbResult(data)
            except Exception:
                logger.exception("OMDb search failed for %s", title)
                return None
