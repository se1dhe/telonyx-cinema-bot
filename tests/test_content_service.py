from __future__ import annotations

from datetime import date

import pytest

from telonyx_cinema_bot.db import create_engine, create_schema, create_session_factory
from telonyx_cinema_bot.models import DraftStatus, Film
from telonyx_cinema_bot.services.content import ContentService
from telonyx_cinema_bot.services.tmdb import MovieMetadata


class FakeMovieProvider:
    async def search_best_match(self, title: str) -> MovieMetadata | None:
        return make_movie(title=title)


class FakeCopywriter:
    async def emotional_description(self, movie: MovieMetadata) -> str:
        return f"{movie.title} feels lonely and luminous."


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.next_message_id = 100

    async def publish_card(self, text: str, poster_url: str | None = None) -> int:
        self.messages.append(("card", text))
        return self._message_id()

    async def publish_poll(self, text: str, options: list[str]) -> tuple[int, str | None]:
        self.messages.append(("poll", text + "\n" + "|".join(options)))
        return self._message_id(), "poll-1"

    async def publish_text(self, text: str) -> int:
        self.messages.append(("text", text))
        return self._message_id()

    def _message_id(self) -> int:
        self.next_message_id += 1
        return self.next_message_id


class FakePollReader:
    def __init__(self, votes: list[int] | None) -> None:
        self.votes = votes

    async def poll_votes(self, poll_id: str, poll_message_id: int | None) -> list[int] | None:
        return self.votes


@pytest.fixture
async def session_factory():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    await create_schema(engine)
    factory = create_session_factory(engine)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_submit_approve_digest_and_recommendation_flow(session_factory) -> None:
    publisher = FakePublisher()
    today = date(2026, 6, 14)

    async with session_factory() as session:
        async with session.begin():
            service = ContentService(session, FakeMovieProvider(), FakeCopywriter())
            draft = await service.submit(
                "https://www.tiktok.com/@telonyx/video/1",
                "Interstellar",
                admin_user_id=7,
            )
            assert draft.status == DraftStatus.pending
            assert "Interstellar feels lonely" in draft.card_text

    async with session_factory() as session:
        async with session.begin():
            service = ContentService(session, FakeMovieProvider(), FakeCopywriter())
            await service.approve(1, publisher, today)

    async with session_factory() as session:
        async with session.begin():
            service = ContentService(session, FakeMovieProvider(), FakeCopywriter())
            digest = await service.create_digest(publisher, today)
            assert digest is not None
            assert digest.poll_id == "poll-1"

    async with session_factory() as session:
        async with session.begin():
            service = ContentService(session, FakeMovieProvider(), FakeCopywriter())
            recommendation = await service.create_recommendation(
                publisher,
                FakePollReader([3]),
                today,
            )
            assert recommendation is not None

    assert publisher.messages[0][0] == "card"
    assert publisher.messages[1][0] == "poll"
    assert publisher.messages[2][0] == "text"
    assert "If you liked <b>Interstellar (2014)</b>" in publisher.messages[2][1]
    assert "- Arrival (2016)" in publisher.messages[2][1]


async def test_digest_skips_day_without_published_films(session_factory) -> None:
    async with session_factory() as session:
        async with session.begin():
            service = ContentService(session, FakeMovieProvider(), FakeCopywriter())
            digest = await service.create_digest(FakePublisher(), date(2026, 6, 14))

    assert digest is None


async def test_poll_votes_are_persisted_and_used(session_factory) -> None:
    publisher = FakePublisher()
    today = date(2026, 6, 14)

    async with session_factory() as session:
        async with session.begin():
            service = ContentService(session, FakeMovieProvider(), FakeCopywriter())
            first = await service.submit("https://tiktok.test/1", "Interstellar", 7)
            second = await service.submit("https://tiktok.test/2", "Her", 7)
            await service.approve(first.id, publisher, today)
            await service.approve(second.id, publisher, today)
            await service.create_digest(publisher, today)
            await service.update_poll_votes("poll-1", [1, 5])
            recommendation = await service.create_recommendation(
                publisher,
                FakePollReader(None),
                today,
            )
            winner = await session.get(Film, recommendation.winner_film_id)

    assert recommendation is not None
    assert winner.title == "Her"


def make_movie(title: str = "Interstellar") -> MovieMetadata:
    tmdb_id = 1 if title == "Interstellar" else 2
    return MovieMetadata(
        tmdb_id=tmdb_id,
        title=title,
        original_title=title,
        release_year=2014 if title == "Interstellar" else 2013,
        overview="A film about distance and longing.",
        poster_path="/poster.jpg",
        imdb_id=f"tt{tmdb_id}",
        imdb_rating="8.7",
        genres=["Drama"],
        similar_movies=[
            {"tmdb_id": 10, "title": "Arrival", "release_year": 2016},
            {"tmdb_id": 11, "title": "Gravity", "release_year": 2013},
            {"tmdb_id": 12, "title": "The Martian", "release_year": 2015},
        ],
        raw_metadata={"id": tmdb_id},
    )
