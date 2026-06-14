from __future__ import annotations

from datetime import date

from telonyx_cinema_bot.models import Campaign, Draft, DraftStatus, Film, Submission
from telonyx_cinema_bot.services.content import ContentService
from telonyx_cinema_bot.services.tmdb import MovieMetadata


class FakeScalarResult:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items


class FakeResult:
    def __init__(self, value=None, items=None):
        self.value = value
        self.items = items or []

    def scalar(self):
        return self.value

    def scalars(self):
        return FakeScalarResult(self.items)


class FakeSession:
    def __init__(self) -> None:
        self.next_id = 1
        self.films: list[Film] = []
        self.submissions: list[Submission] = []
        self.drafts: list[Draft] = []
        self.campaigns: list[Campaign] = []

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self.next_id
            self.next_id += 1
        if isinstance(obj, Film) and obj not in self.films:
            self.films.append(obj)
        elif isinstance(obj, Submission) and obj not in self.submissions:
            self.submissions.append(obj)
        elif isinstance(obj, Draft) and obj not in self.drafts:
            self.drafts.append(obj)
        elif isinstance(obj, Campaign) and obj not in self.campaigns:
            self.campaigns.append(obj)

    async def flush(self) -> None:
        for draft in self.drafts:
            if getattr(draft, "submission", None) is None:
                draft.submission = next(s for s in self.submissions if s.id == draft.submission_id)
            if getattr(draft, "film", None) is None:
                draft.film = next(f for f in self.films if f.id == draft.film_id)
        for campaign in self.campaigns:
            if getattr(campaign, "draft", None) is None:
                campaign.draft = next(d for d in self.drafts if d.id == campaign.draft_id)

    async def scalar(self, statement):
        text = str(statement)
        if "FROM films" in text:
            return self.films[0] if self.films else None
        if "FROM drafts" in text:
            draft_id = statement.compile().params.get("id_1")
            return next((draft for draft in self.drafts if draft.id == draft_id), None)
        return None

    async def execute(self, statement):
        text = str(statement)
        if "max(campaigns.local_date)" in text:
            dates = [campaign.local_date for campaign in self.campaigns]
            return FakeResult(max(dates) if dates else None)
        if "FROM drafts" in text:
            return FakeResult(items=[draft for draft in self.drafts if draft.status == DraftStatus.pending])
        return FakeResult()


class FakeMovieProvider:
    async def search_best_match(self, title: str) -> MovieMetadata | None:
        return make_movie(title=title)

    async def fetch_movie(self, tmdb_id: int) -> MovieMetadata:
        return make_movie()


class FakeCopywriter:
    async def generate_campaign_texts(self, movie: MovieMetadata) -> tuple[str, str, str]:
        return (
            await self.generate_review(movie),
            await self.generate_fact(movie),
            await self.generate_recommendations(movie),
        )

    async def generate_review(self, movie: MovieMetadata) -> str:
        return f"{movie.title} звучит одиноко и светло."

    async def generate_fact(self, movie: MovieMetadata) -> str:
        return f"Факт о {movie.title}: снимали 6 месяцев."

    async def generate_recommendations(self, movie: MovieMetadata) -> str:
        return f"Если вам понравился {movie.title}, смотрите похожие."


async def test_submit_creates_draft_with_three_texts() -> None:
    session = FakeSession()
    service = ContentService(session, FakeMovieProvider(), FakeCopywriter())
    draft = await service.submit("video_file_id_123", "Interstellar", admin_user_id=7)

    assert draft.status == DraftStatus.pending
    assert "звучит одиноко" in draft.review_text
    assert "Факт о Interstellar" in draft.fact_text
    assert "смотрите похожие" in draft.recommendations_text
    assert draft.video_file_id == "video_file_id_123"


async def test_queue_draft_assigns_date_and_approves() -> None:
    session = FakeSession()
    service = ContentService(session, FakeMovieProvider(), FakeCopywriter())
    draft = await service.submit("vid_1", "Interstellar", admin_user_id=7)

    campaign = await service.queue_draft(draft.id)

    assert campaign.local_date is not None
    assert campaign.draft_id == draft.id


async def test_queue_two_drafts_sequential_dates() -> None:
    session = FakeSession()
    service = ContentService(session, FakeMovieProvider(), FakeCopywriter())
    d1 = await service.submit("vid_1", "Interstellar", admin_user_id=7)
    d2 = await service.submit("vid_2", "Her", admin_user_id=7)

    c1 = await service.queue_draft(d1.id)
    c1.local_date = date(2026, 6, 14)
    c2 = await service.queue_draft(d2.id)

    assert c2.local_date > c1.local_date


async def test_reject_draft() -> None:
    session = FakeSession()
    service = ContentService(session, FakeMovieProvider(), FakeCopywriter())
    draft = await service.submit("vid_1", "Interstellar", admin_user_id=7)

    rejected = await service.reject(draft.id)

    assert rejected.status == DraftStatus.rejected


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
