from __future__ import annotations

from html import escape

from telonyx_cinema_bot.services.tmdb import MovieMetadata


def format_review(movie: MovieMetadata, review_text: str) -> str:
    lines = [
        f"<b>{escape(movie.display_title)}</b>",
        "",
        escape(review_text),
    ]

    if movie.genres:
        lines.extend(["", f"<b>Жанр:</b> {escape(', '.join(movie.genres[:3]))}"])

    if movie.imdb_rating:
        lines.extend(["", f"TMDb: <b>{escape(movie.imdb_rating)}</b>"])

    return "\n".join(lines)


def format_fact(movie: MovieMetadata, fact_text: str) -> str:
    return (
        f"<b>{escape(movie.display_title)}</b>\n\n"
        f"<i>{escape(fact_text)}</i>"
    )


def format_recommendations(movie: MovieMetadata, rec_text: str) -> str:
    lines = [
        f"<b>{escape(movie.display_title)}</b>: что посмотреть после?",
        "",
        escape(rec_text),
        "",
    ]
    for item in movie.similar_movies[:3]:
        title = item.get("title", "")
        year = item.get("release_year", "")
        if title:
            lines.append(f"- <b>{escape(title)}</b> ({year})" if year else f"- <b>{escape(title)}</b>")
    
    return "\n".join(lines)


def format_poll_options(movie: MovieMetadata) -> list[str]:
    options = []
    for item in movie.similar_movies[:3]:
        title = item.get("title", "")
        if title:
            options.append(title[:100])
    if not options:
        options = ["Смотрел(а)", "Не смотрел(а)", "Хочу посмотреть"]
    return options
