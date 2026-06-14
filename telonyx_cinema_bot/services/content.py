from __future__ import annotations

import datetime
from typing import Protocol

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from telonyx_cinema_bot.models import (
    Campaign,
    Draft,
    DraftStatus,
    Film,
    Submission,
    SubmissionStatus,
)
from telonyx_cinema_bot.services.tmdb import MovieMetadata


class MovieProvider(Protocol):
    async def search_best_match(self, title: str) -> MovieMetadata | None: ...
    async def fetch_movie(self, tmdb_id: int) -> MovieMetadata: ...


class Copywriter(Protocol):
    async def generate_campaign_texts(self, movie: MovieMetadata) -> tuple[str, str, str]: ...
    async def generate_review(self, movie: MovieMetadata) -> str: ...
    async def generate_fact(self, movie: MovieMetadata) -> str: ...
    async def generate_recommendations(self, movie: MovieMetadata) -> str: ...


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

    async def submit(
        self,
        video_file_id: str,
        title: str,
        admin_user_id: int,
        tmdb_id: int | None = None,
    ) -> Draft:
        if tmdb_id:
            movie = await self.movie_provider.fetch_movie(tmdb_id)
        else:
            movie = await self.movie_provider.search_best_match(title)

        if movie is None:
            raise ValueError(f"TMDb не нашёл фильм: {title}")

        film = await self._upsert_film(movie)
        submission = Submission(
            video_file_id=video_file_id,
            submitted_title=title,
            status=SubmissionStatus.drafted,
            admin_user_id=admin_user_id,
        )
        self.session.add(submission)
        await self.session.flush()

        review_text, fact_text, recs_text = await self.copywriter.generate_campaign_texts(movie)

        draft = Draft(
            submission_id=submission.id,
            film_id=film.id,
            status=DraftStatus.pending,
            video_file_id=video_file_id,
            review_text=review_text,
            fact_text=fact_text,
            recommendations_text=recs_text,
            metadata_snapshot=movie.raw_metadata if movie.raw_metadata else {},
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

    async def queue_draft(self, draft_id: int) -> Campaign:
        draft = await self._get_draft(draft_id)
        if draft.status != DraftStatus.pending:
            raise ValueError(f"Черновик {draft_id} уже не на проверке")

        today = datetime.date.today()

        max_date_result = await self.session.execute(
            select(func.max(Campaign.local_date))
        )
        max_date = max_date_result.scalar()

        if max_date and max_date >= today:
            next_date = max_date + datetime.timedelta(days=1)
        else:
            next_date = today

        draft.status = DraftStatus.approved
        draft.submission.status = SubmissionStatus.approved

        campaign = Campaign(
            draft_id=draft.id,
            local_date=next_date,
        )
        campaign.draft = draft
        self.session.add(campaign)
        await self.session.flush()
        return campaign

    async def reject(self, draft_id: int) -> Draft:
        draft = await self._get_draft(draft_id)
        if draft.status != DraftStatus.pending:
            raise ValueError(f"Черновик {draft_id} уже не на проверке")
        draft.status = DraftStatus.rejected
        draft.submission.status = SubmissionStatus.rejected
        await self.session.flush()
        return draft

    async def _get_draft(self, draft_id: int) -> Draft:
        draft = await self.session.scalar(
            select(Draft)
            .where(Draft.id == draft_id)
            .options(selectinload(Draft.submission), selectinload(Draft.film))
        )
        if draft is None:
            raise ValueError(f"Черновик {draft_id} не найден")
        return draft

    async def _upsert_film(self, movie: MovieMetadata) -> Film:
        film = await self.session.scalar(
            select(Film).where(Film.tmdb_id == movie.tmdb_id)
        )
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
