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
        lines.append(f"⭐️ <b>Рейтинг:</b> {movie.imdb_rating}/10")

    if movie.overview:
        lines.append("")
        lines.append(movie.overview)

    imdb_link = _imdb_url(movie.imdb_id)
    if imdb_link:
        lines.append("")
        lines.append(f"🔗 <a href='{imdb_link}'>Смотреть на IMDb</a>")

    return "\n".join(lines)


def generate_tiktok_caption(movie: MovieMetadata | None, telegram_url: str) -> str:
    title_line = movie.display_title if movie else "Новинка кино"
    pitch = "Разборы, интересные факты и подборки на вечер — в нашем Telegram 👇"

    hashtags: list[str] = []

    if movie:
        tag = _clean_hashtag(movie.title)
        if tag:
            hashtags.append(f"#{tag}")
        for c in movie.cast[:3]:
            name = _clean_hashtag(c["name"])
            if name and len(hashtags) < 10:
                hashtags.append(f"#{name}")
        for genre in movie.genres[:2]:
            g = _clean_hashtag(genre)
            if g and len(hashtags) < 10:
                hashtags.append(f"#{g}")

    viral = ["#кино", "#shorts", "#кинообзор", "#рекомендации", "#чтопосмотреть"]
    for tag in viral:
        if len(hashtags) < 10:
            hashtags.append(tag)

    return (
        f"🎬 {title_line}\n\n"
        f"{pitch}\n"
        f"{telegram_url}\n\n"
        f"{' '.join(hashtags)}"
    )


def _clean_hashtag(text: str) -> str:
    cleaned = ""
    for ch in text:
        if ch.isalnum() or ch in ("_",):
            cleaned += ch
        elif ch in (" ", "-", ".", ":", "!", "?", "'", '"', ",", "(", ")"):
            cleaned += ""
        else:
            cleaned += ""
    return cleaned


def _imdb_url(imdb_id: str | None) -> str | None:
    if not imdb_id:
        return None
    return f"https://www.imdb.com/title/{imdb_id}/"
