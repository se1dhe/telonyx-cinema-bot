from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp


TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w780"


@dataclass(frozen=True)
class MovieMetadata:
    tmdb_id: int
    title: str
    original_title: str | None
    release_year: int | None
    overview: str | None
    poster_path: str | None
    imdb_id: str | None
    imdb_rating: str | None
    genres: list[str]
    similar_movies: list[dict[str, Any]]
    raw_metadata: dict[str, Any]

    @property
    def display_title(self) -> str:
        if self.release_year:
            return f"{self.title} ({self.release_year})"
        return self.title

    @property
    def poster_url(self) -> str | None:
        if not self.poster_path:
            return None
        return f"{TMDB_IMAGE_BASE_URL}{self.poster_path}"


class TMDbClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"

    async def search_best_match(self, title: str) -> MovieMetadata | None:
        async with aiohttp.ClientSession() as session:
            search_payload = await self._get(
                session,
                "/search/movie",
                {"query": title, "include_adult": "false", "language": "ru-RU"},
            )
            results = search_payload.get("results", [])
            if not results:
                return None
            tmdb_id = results[0]["id"]
            return await self.fetch_movie(tmdb_id, session=session)

    async def fetch_movie(
        self, tmdb_id: int, session: aiohttp.ClientSession | None = None
    ) -> MovieMetadata:
        if session is None:
            async with aiohttp.ClientSession() as own_session:
                return await self.fetch_movie(tmdb_id, session=own_session)

        payload = await self._get(
            session,
            f"/movie/{tmdb_id}",
            {"append_to_response": "external_ids,similar", "language": "ru-RU"},
        )
        return normalize_movie(payload)

    async def _get(
        self, session: aiohttp.ClientSession, path: str, params: dict[str, str]
    ) -> dict[str, Any]:
        request_params = {"api_key": self.api_key, **params}
        async with session.get(f"{self.base_url}{path}", params=request_params) as response:
            response.raise_for_status()
            return await response.json()


def normalize_movie(payload: dict[str, Any]) -> MovieMetadata:
    release_year = _extract_year(payload.get("release_date"))
    genres = [genre["name"] for genre in payload.get("genres", []) if genre.get("name")]
    similar = [
        {
            "tmdb_id": item.get("id"),
            "title": item.get("title") or item.get("name"),
            "release_year": _extract_year(item.get("release_date")),
            "overview": item.get("overview"),
            "poster_path": item.get("poster_path"),
        }
        for item in payload.get("similar", {}).get("results", [])[:3]
        if item.get("title") or item.get("name")
    ]

    return MovieMetadata(
        tmdb_id=payload["id"],
        title=payload.get("title") or payload.get("name") or "Untitled",
        original_title=payload.get("original_title"),
        release_year=release_year,
        overview=payload.get("overview"),
        poster_path=payload.get("poster_path"),
        imdb_id=payload.get("external_ids", {}).get("imdb_id"),
        imdb_rating=_extract_imdb_rating(payload),
        genres=genres,
        similar_movies=similar,
        raw_metadata=payload,
    )


def _extract_year(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def _extract_imdb_rating(payload: dict[str, Any]) -> str | None:
    rating = payload.get("vote_average")
    if rating is None or rating == 0:
        return None
    return f"{rating:.1f}"
