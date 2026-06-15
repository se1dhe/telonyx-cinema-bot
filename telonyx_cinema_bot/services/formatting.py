from __future__ import annotations

from html import escape

from telonyx_cinema_bot.models import EditorialPost
from telonyx_cinema_bot.services.tmdb import MovieMetadata

TELEGRAM_MEDIA_CAPTION_LIMIT = 1024


def format_video_caption(movie: MovieMetadata, review_text: str | None = None) -> str:
    lines = [
        f"🎬 <b>{escape(movie.display_title)}</b>",
    ]
    if movie.original_title and movie.original_title != movie.title:
        lines.append(f"<i>{escape(movie.original_title)}</i>")
    if movie.genres:
        lines.append(f"<b>Жанр:</b> {escape(', '.join(movie.genres[:3]))}")
    if movie.imdb_rating:
        lines.append(f"<b>IMDb/TMDb:</b> {escape(movie.imdb_rating)}")
    if movie.overview:
        lines.extend(["", escape(movie.overview)])
    if review_text:
        lines.extend(["", escape(review_text)])
    return _trim_caption("\n".join(lines))


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

    return _trim_caption("\n".join(lines))


def format_fact(movie: MovieMetadata, fact_text: str) -> str:
    return _trim_caption(
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
    
    return _trim_caption("\n".join(lines))


def format_recommended_movie(item: dict) -> str:
    title = item.get("title") or "Фильм"
    year = item.get("release_year")
    overview = item.get("overview")
    lines = [
        f"🎞 <b>{escape(title)}</b>" + (f" ({year})" if year else ""),
    ]
    if overview:
        lines.extend(["", escape(str(overview))])
    return _trim_caption("\n".join(lines))


def poster_url_from_path(path: str | None) -> str | None:
    if not path:
        return None
    return f"https://image.tmdb.org/t/p/w780{path}"


def _trim_caption(text: str) -> str:
    if len(text) <= TELEGRAM_MEDIA_CAPTION_LIMIT:
        return text
    return text[: TELEGRAM_MEDIA_CAPTION_LIMIT - 3].rstrip() + "..."


def format_poll_options(movie: MovieMetadata) -> list[str]:
    options = []
    for item in movie.similar_movies[:3]:
        title = item.get("title", "")
        if title:
            options.append(title[:100])
    if not options:
        options = ["Смотрел(а)", "Не смотрел(а)", "Хочу посмотреть"]
    return options


def format_news_post(title: str, body: str, source_url: str | None = None) -> str:
    clean_title = escape(title.strip() or "Киноновость")
    clean_body = escape(body.strip())
    if len(clean_body) > 720:
        clean_body = clean_body[:717].rstrip() + "..."

    lines = [
        f"🗞 <b>{clean_title}</b>",
        "",
        clean_body,
    ]
    if source_url:
        lines.extend(["", f"<a href=\"{escape(source_url, quote=True)}\">Источник</a>"])
    return _trim_caption("\n".join(line for line in lines if line is not None))


def normalize_hashtag(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    normalized = normalized.replace(" ", "")
    if not normalized.startswith("#"):
        normalized = f"#{normalized}"
    return normalized


def format_editorial_post(post: EditorialPost) -> str:
    title = escape((post.title or "").strip())
    body = escape(post.text.strip())
    hashtags = [normalize_hashtag(tag) for tag in post.hashtags if normalize_hashtag(tag)]
    hashtag_line = " ".join(dict.fromkeys(hashtags))

    prefix_by_type = {
        "news": "Киноновость",
        "review": "Разбор",
        "selection": "Что смотреть",
        "poll": "Голосование",
        "discussion": "Тема дня",
    }
    label = prefix_by_type.get(getattr(post.post_type, "value", str(post.post_type)), "Telonyx Cinema")

    lines = [f"<b>{escape(label)}</b>"]
    if title:
        lines.extend(["", f"<b>{title}</b>"])
    lines.extend(["", body])
    if hashtag_line:
        lines.extend(["", escape(hashtag_line)])
    return _trim_caption("\n".join(lines))
