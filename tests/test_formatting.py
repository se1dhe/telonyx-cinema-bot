from telonyx_cinema_bot.services.formatting import (
    build_digest_text,
    build_film_card,
    build_recommendation_text,
)
from telonyx_cinema_bot.services.tmdb import MovieMetadata, normalize_movie


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
            "similar": {"results": [{"id": 99, "title": "Lost in Translation", "release_date": "2003-09-18"}]},
        }
    )

    assert normalized.display_title == "Her (2013)"
    assert normalized.imdb_id == "tt1798709"
    assert normalized.genres == ["Romance", "Science Fiction"]
    assert normalized.similar_movies[0]["title"] == "Lost in Translation"


def test_film_card_omits_missing_optional_fields() -> None:
    card = build_film_card(
        movie(imdb_rating=None, similar_movies=[]),
        "https://www.tiktok.com/@telonyx/video/1",
        "A quiet ache in deep space.",
    )

    assert "Interstellar (2014)" in card.text
    assert "IMDb:" not in card.text
    assert "Similar mood:" not in card.text
    assert "TikTok source" in card.text


def test_digest_skips_empty_day() -> None:
    assert build_digest_text([]) is None


def test_digest_and_recommendation_texts_are_stable() -> None:
    digest = build_digest_text([movie(), movie("Her", 2, 2013)])
    recommendation = build_recommendation_text(
        movie(),
        [movie("Arrival", 2, 2016), movie("Gravity", 3, 2013), movie("The Martian", 4, 2015)],
    )

    assert "Today in TELONYX CINEMA" in digest
    assert "- Interstellar (2014)" in digest
    assert "If you liked <b>Interstellar (2014)</b>" in recommendation
    assert "- Arrival (2016)" in recommendation

