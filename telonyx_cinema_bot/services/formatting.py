from __future__ import annotations

from dataclasses import dataclass
from html import escape

from telonyx_cinema_bot.services.tmdb import MovieMetadata


@dataclass(frozen=True)
class DraftCard:
    text: str
    metadata_snapshot: dict


def build_film_card(
    movie: MovieMetadata,
    tiktok_url: str,
    emotional_description: str,
    quote: str | None = None,
) -> DraftCard:
    lines = [
        f"<b>{escape(movie.display_title)}</b>",
        "",
        escape(emotional_description),
    ]

    if movie.genres:
        lines.extend(["", f"<b>Жанр:</b> {escape(', '.join(movie.genres[:3]))}"])

    if movie.imdb_rating:
        lines.extend(["", f"TMDb: <b>{escape(movie.imdb_rating)}</b>"])

    similar_titles = _similar_titles(movie)
    if similar_titles:
        lines.extend(["", "<b>Похожее настроение:</b>"])
        lines.extend(f"- {escape(title)}" for title in similar_titles)

    if quote:
        lines.extend(["", f"<i>\"{escape(quote)}\"</i>"])

    lines.extend(["", f'<a href="{escape(tiktok_url)}">Источник в TikTok</a>'])

    return DraftCard(
        text="\n".join(lines),
        metadata_snapshot={
            "tmdb_id": movie.tmdb_id,
            "imdb_id": movie.imdb_id,
            "display_title": movie.display_title,
            "similar_movies": movie.similar_movies,
            "poster_url": movie.poster_url,
        },
    )


def build_digest_text(movies: list[MovieMetadata]) -> str | None:
    if not movies:
        return None

    lines = ["<b>Сегодня в TELONYX CINEMA:</b>", ""]
    lines.extend(f"- {escape(movie.display_title)}" for movie in movies)
    lines.extend(["", "Выберите фильм, который станет выбором дня:"])
    return "\n".join(lines)


def build_recommendation_text(winner: MovieMetadata, recommendations: list[MovieMetadata]) -> str:
    lines = [f"Если вам понравился <b>{escape(winner.display_title)}</b>, посмотрите ещё:", ""]
    lines.extend(f"- {escape(movie.display_title)}" for movie in recommendations[:3])
    return "\n".join(lines)


def _similar_titles(movie: MovieMetadata) -> list[str]:
    titles: list[str] = []
    for item in movie.similar_movies[:3]:
        title = item.get("title")
        year = item.get("release_year")
        if title and year:
            titles.append(f"{title} ({year})")
        elif title:
            titles.append(title)
    return titles
