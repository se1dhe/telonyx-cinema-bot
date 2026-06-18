from __future__ import annotations

from telonyx_cinema_bot.services.tmdb import MovieMetadata


def format_movie_card(movie: MovieMetadata) -> str:
    lines: list[str] = []

    lines.append(f"<b>{movie.title}</b>")
    if movie.original_title and movie.original_title.lower() != movie.title.lower():
        lines.append(f"<i>{movie.original_title}</i>")

    lines.append("")

    meta_parts = []
    if movie.release_year:
        meta_parts.append(f"📅 <b>Год:</b> {movie.release_year}")
    if movie.genres:
        meta_parts.append(f"🎭 <b>Жанр:</b> {', '.join(movie.genres)}")
    lines.extend(meta_parts)

    if movie.director:
        lines.append(f"🎬 <b>Режиссёр:</b> {movie.director}")

    if movie.cast:
        cast_str = "\n".join(
            f"  👤 <b>{c['name']}</b> — {c['character']}"
            for c in movie.cast
        )
        lines.append(f"👥 <b>В ролях:</b>\n{cast_str}")

    if movie.imdb_rating:
        rating = movie.imdb_rating
        lines.append(f"⭐️ <b>Рейтинг:</b> {rating}/10")

    if movie.overview:
        lines.append("")
        lines.append(movie.overview)

    imdb_link = _imdb_url(movie.imdb_id)
    if imdb_link:
        lines.append("")
        lines.append(f"🔗 <a href='{imdb_link}'>Смотреть на IMDb</a>")

    return "\n".join(lines)


def _imdb_url(imdb_id: str | None) -> str | None:
    if not imdb_id:
        return None
    return f"https://www.imdb.com/title/{imdb_id}/"
