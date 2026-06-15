from telonyx_cinema_bot.services.formatting import (
    format_editorial_post,
    format_review,
    format_fact,
    format_recommendations,
    format_poll_options,
    format_news_post,
    format_recommended_movie,
    format_video_caption,
    poster_url_from_path,
)
from telonyx_cinema_bot.models import EditorialPost, EditorialPostType
from telonyx_cinema_bot.services.tmdb import MovieMetadata, normalize_movie
from telonyx_cinema_bot.bot.handlers import _parse_draft_callback


def movie(
    title: str = "Interstellar",
    tmdb_id: int = 1,
    release_year: int | None = 2014,
    imdb_rating: str | None = "8.7",
    similar_movies: list[dict] | None = None,
) -> MovieMetadata:
    return MovieMetadata(
        tmdb_id=tmdb_id,
        title=title,
        original_title=title,
        release_year=release_year,
        overview="A team travels through a wormhole.",
        poster_path="/poster.jpg",
        imdb_id="tt0816692",
        imdb_rating=imdb_rating,
        genres=["Science Fiction"],
        similar_movies=similar_movies
        if similar_movies is not None
        else [
            {"tmdb_id": 2, "title": "Arrival", "release_year": 2016},
            {"tmdb_id": 3, "title": "Gravity", "release_year": 2013},
            {"tmdb_id": 4, "title": "The Martian", "release_year": 2015},
        ],
        raw_metadata={},
    )


def test_normalize_movie_extracts_tmdb_metadata() -> None:
    normalized = normalize_movie(
        {
            "id": 42,
            "title": "Her",
            "original_title": "Her",
            "release_date": "2013-12-18",
            "overview": "A lonely writer develops a relationship with an OS.",
            "poster_path": "/her.jpg",
            "genres": [{"name": "Romance"}, {"name": "Science Fiction"}],
            "external_ids": {"imdb_id": "tt1798709"},
            "similar": {
                "results": [
                    {
                        "id": 99,
                        "title": "Lost in Translation",
                        "release_date": "2003-09-18",
                        "poster_path": "/lost.jpg",
                    }
                ]
            },
        }
    )

    assert normalized.display_title == "Her (2013)"
    assert normalized.imdb_id == "tt1798709"
    assert normalized.genres == ["Romance", "Science Fiction"]
    assert normalized.similar_movies[0]["title"] == "Lost in Translation"
    assert normalized.similar_movies[0]["poster_path"] == "/lost.jpg"


def test_format_review_includes_title_and_genres() -> None:
    text = format_review(movie(), "A quiet ache in deep space.")

    assert "Interstellar (2014)" in text
    assert "Science Fiction" in text
    assert "8.7" in text


def test_format_review_omits_missing_fields() -> None:
    text = format_review(movie(imdb_rating=None, similar_movies=[]), "A quiet ache.")

    assert "Interstellar (2014)" in text
    assert "TMDb:" not in text


def test_format_fact_wraps_in_italics() -> None:
    text = format_fact(movie(), "Снимали на реальной кукурузной ферме.")

    assert "<i>" in text
    assert "кукурузной ферме" in text


def test_format_recommendations_lists_similar_films() -> None:
    text = format_recommendations(movie(), "Если вам понравился, смотрите:")

    assert "Arrival" in text
    assert "Gravity" in text
    assert "The Martian" in text


def test_format_poll_options_from_similar() -> None:
    options = format_poll_options(movie())
    assert len(options) == 3
    assert options[0] == "Arrival"


def test_format_poll_options_fallback() -> None:
    options = format_poll_options(movie(similar_movies=[]))
    assert "Смотрел(а)" in options


def test_draft_callback_parser() -> None:
    assert _parse_draft_callback("draft:approve:42") == ("approve", 42)
    assert _parse_draft_callback("draft:reject:42") == ("reject", 42)
    assert _parse_draft_callback("draft:approve:nope") == (None, None)


def test_format_news_post_uses_html_and_escapes_source() -> None:
    text = format_news_post("Disclosure Day", "Spielberg & aliens", "https://example.com/?a=1&b=2")

    assert "<b>Disclosure Day</b>" in text
    assert "Spielberg &amp; aliens" in text
    assert "a=1&amp;b=2" in text
    assert "**" not in text


def test_format_editorial_news_post_has_tags_and_no_source_link() -> None:
    post = EditorialPost(
        post_type=EditorialPostType.news,
        title="Big Trailer",
        text="Студия показала первый трейлер.",
        hashtags=["#новости", "#трейлеры", "#telonyxcinema"],
        image_url="https://example.com/poster.jpg",
        source_url="https://example.com/source",
    )

    text = format_editorial_post(post)

    assert "<b>Киноновость</b>" in text
    assert "#новости" in text
    assert "https://example.com/source" not in text


def test_format_video_caption_includes_rating_and_overview() -> None:
    text = format_video_caption(movie(), "A quiet ache.")

    assert "Interstellar (2014)" in text
    assert "IMDb/TMDb:" in text
    assert "A team travels" in text
    assert "A quiet ache." in text


def test_format_recommended_movie_and_poster_url() -> None:
    item = {
        "title": "Arrival",
        "release_year": 2016,
        "overview": "First contact with language at the center.",
        "poster_path": "/arrival.jpg",
    }

    assert "Arrival" in format_recommended_movie(item)
    assert poster_url_from_path(item["poster_path"]).endswith("/arrival.jpg")
