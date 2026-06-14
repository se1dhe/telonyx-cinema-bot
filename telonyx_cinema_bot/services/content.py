from __future__ import annotations

from datetime import date
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import selectinload

from telonyx_cinema_bot.models import (
    DailyDigest,
    DailyRecommendation,
    Draft,
    DraftStatus,
    Film,
    PublishedPost,
    Submission,
    SubmissionStatus,
)
from telonyx_cinema_bot.services.formatting import (
    build_digest_text,
    build_film_card,
    build_recommendation_text,
)
from telonyx_cinema_bot.services.tmdb import MovieMetadata


class MovieProvider(Protocol):
    async def search_best_match(self, title: str) -> MovieMetadata | None: ...


class Copywriter(Protocol):
    async def emotional_description(self, movie: MovieMetadata) -> str: ...


class TelegramPublisher(Protocol):
    async def publish_card(self, text: str, poster_url: str | None = None) -> int: ...

    async def publish_poll(self, text: str, options: list[str]) -> tuple[int, str | None]: ...

    async def publish_text(self, text: str) -> int: ...


class PollReader(Protocol):
    async def poll_votes(self, poll_id: str, poll_message_id: int | None) -> list[int] | None: ...


class ContentService:
    def __init__(
        self,
        session: AsyncSession,
        movie_provider: MovieProvider,
        copywriter: Copywriter,
    ) -> None:
        self.session = session
        self.movie_provider = movie_provider
        self.copywriter = copywriter

    async def submit(self, tiktok_url: str, title: str, admin_user_id: int) -> Draft:
        movie = await self.movie_provider.search_best_match(title)
        if movie is None:
            raise ValueError(f"No TMDb match found for: {title}")

        film = await self._upsert_film(movie)
        submission = Submission(
            tiktok_url=tiktok_url,
            submitted_title=title,
            status=SubmissionStatus.drafted,
            admin_user_id=admin_user_id,
        )
        self.session.add(submission)
        await self.session.flush()

        description = await self.copywriter.emotional_description(movie)
        card = build_film_card(movie, tiktok_url, description)
        draft = Draft(
            submission_id=submission.id,
            film_id=film.id,
            status=DraftStatus.pending,
            card_text=card.text,
            metadata_snapshot=card.metadata_snapshot,
        )
        self.session.add(draft)
        await self.session.flush()
        return draft

    async def pending_drafts(self) -> list[Draft]:
        result = await self.session.execute(
            select(Draft)
            .where(Draft.status == DraftStatus.pending)
            .options(selectinload(Draft.film), selectinload(Draft.submission))
            .order_by(Draft.created_at)
        )
        return list(result.scalars())

    async def approve(self, draft_id: int, publisher: TelegramPublisher, local_date: date) -> Draft:
        draft = await self._get_draft(draft_id)
        if draft.status != DraftStatus.pending:
            raise ValueError(f"Draft {draft_id} is not pending")

        message_id = await publisher.publish_card(
            draft.card_text, draft.metadata_snapshot.get("poster_url")
        )
        draft.status = DraftStatus.approved
        draft.submission.status = SubmissionStatus.approved
        self.session.add(
            PublishedPost(
                draft_id=draft.id,
                film_id=draft.film_id,
                telegram_message_id=message_id,
                local_date=local_date,
            )
        )
        await self.session.flush()
        return draft

    async def reject(self, draft_id: int) -> Draft:
        draft = await self._get_draft(draft_id)
        if draft.status != DraftStatus.pending:
            raise ValueError(f"Draft {draft_id} is not pending")
        draft.status = DraftStatus.rejected
        draft.submission.status = SubmissionStatus.rejected
        await self.session.flush()
        return draft

    async def create_digest(self, publisher: TelegramPublisher, local_date: date) -> DailyDigest | None:
        existing = await self.session.scalar(
            select(DailyDigest).where(DailyDigest.local_date == local_date)
        )
        if existing:
            return existing

        films = await self.published_films_for_date(local_date)
        movies = [_metadata_from_film(film) for film in films]
        digest_text = build_digest_text(movies)
        if digest_text is None:
            return None

        options = [movie.display_title[:100] for movie in movies]
        message_id, poll_id = await publisher.publish_poll(digest_text, options)
        digest = DailyDigest(
            local_date=local_date,
            included_film_ids=[film.id for film in films],
            poll_message_id=message_id,
            poll_id=poll_id,
            poll_options=[
                {"film_id": film.id, "title": movie.display_title, "votes": 0}
                for film, movie in zip(films, movies, strict=True)
            ],
        )
        self.session.add(digest)
        await self.session.flush()
        return digest

    async def create_recommendation(
        self,
        publisher: TelegramPublisher,
        poll_reader: PollReader,
        local_date: date,
    ) -> DailyRecommendation | None:
        existing = await self.session.scalar(
            select(DailyRecommendation).where(DailyRecommendation.local_date == local_date)
        )
        if existing:
            return existing

        digest = await self.session.scalar(select(DailyDigest).where(DailyDigest.local_date == local_date))
        if digest is None:
            return None

        winner = await self._select_winner(digest, poll_reader)
        if winner is None:
            return None

        recommendations = await self._recommendations_for(winner)
        text = build_recommendation_text(_metadata_from_film(winner), recommendations)
        message_id = await publisher.publish_text(text)
        recommendation = DailyRecommendation(
            local_date=local_date,
            winner_film_id=winner.id,
            recommended_film_ids=[movie.tmdb_id for movie in recommendations],
            telegram_message_id=message_id,
        )
        self.session.add(recommendation)
        await self.session.flush()
        return recommendation

    async def update_poll_votes(self, poll_id: str, votes: list[int]) -> DailyDigest | None:
        digest = await self.session.scalar(select(DailyDigest).where(DailyDigest.poll_id == poll_id))
        if digest is None:
            return None

        options = [dict(option) for option in digest.poll_options]
        for index, vote_count in enumerate(votes):
            if index < len(options):
                options[index]["votes"] = vote_count
        digest.poll_options = options
        flag_modified(digest, "poll_options")
        await self.session.flush()
        return digest

    async def published_films_for_date(self, local_date: date) -> list[Film]:
        result = await self.session.execute(
            select(Film)
            .join(PublishedPost, PublishedPost.film_id == Film.id)
            .where(PublishedPost.local_date == local_date)
            .order_by(PublishedPost.published_at)
        )
        return list(result.scalars())

    async def _get_draft(self, draft_id: int) -> Draft:
        draft = await self.session.scalar(
            select(Draft)
            .where(Draft.id == draft_id)
            .options(selectinload(Draft.submission), selectinload(Draft.film))
        )
        if draft is None:
            raise ValueError(f"Draft {draft_id} not found")
        return draft

    async def _select_winner(self, digest: DailyDigest, poll_reader: PollReader) -> Film | None:
        votes = None
        if digest.poll_id:
            votes = await poll_reader.poll_votes(digest.poll_id, digest.poll_message_id)

        options = list(digest.poll_options)
        if votes:
            for index, vote_count in enumerate(votes):
                if index < len(options):
                    options[index]["votes"] = vote_count

        if not options:
            return None

        winner_option = max(
            enumerate(options),
            key=lambda item: (
                item[1].get("votes", 0),
                -item[0],
            ),
        )[1]
        winner_film_id = winner_option["film_id"]
        return await self.session.get(Film, winner_film_id)

    async def _recommendations_for(self, winner: Film) -> list[MovieMetadata]:
        recommendations = []
        for item in winner.similar_movies[:3]:
            recommendations.append(
                MovieMetadata(
                    tmdb_id=item.get("tmdb_id") or 0,
                    title=item.get("title") or "Untitled",
                    original_title=None,
                    release_year=item.get("release_year"),
                    overview=item.get("overview"),
                    poster_path=None,
                    imdb_id=None,
                    imdb_rating=None,
                    genres=[],
                    similar_movies=[],
                    raw_metadata=item,
                )
            )
        return recommendations

    async def _upsert_film(self, movie: MovieMetadata) -> Film:
        film = await self.session.scalar(select(Film).where(Film.tmdb_id == movie.tmdb_id))
        if film is None:
            film = Film(tmdb_id=movie.tmdb_id)
            self.session.add(film)

        film.imdb_id = movie.imdb_id
        film.title = movie.title
        film.original_title = movie.original_title
        film.release_year = movie.release_year
        film.overview = movie.overview
        film.poster_path = movie.poster_path
        film.imdb_rating = movie.imdb_rating
        film.genres = movie.genres
        film.similar_movies = movie.similar_movies
        film.raw_metadata = movie.raw_metadata
        await self.session.flush()
        return film


def _metadata_from_film(film: Film) -> MovieMetadata:
    return MovieMetadata(
        tmdb_id=film.tmdb_id,
        title=film.title,
        original_title=film.original_title,
        release_year=film.release_year,
        overview=film.overview,
        poster_path=film.poster_path,
        imdb_id=film.imdb_id,
        imdb_rating=film.imdb_rating,
        genres=film.genres,
        similar_movies=film.similar_movies,
        raw_metadata=film.raw_metadata,
    )
