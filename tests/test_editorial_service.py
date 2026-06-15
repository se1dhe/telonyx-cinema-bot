from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from telonyx_cinema_bot.models import EditorialControl, EditorialPost, EditorialPostStatus, EditorialPostType
from telonyx_cinema_bot.services.editorial import EditorialService


class FakeScalarResult:
    def __init__(self, items):
        self.items = items

    def first(self):
        return self.items[0] if self.items else None

    def __iter__(self):
        return iter(self.items)


class FakeResult:
    def __init__(self, items=None):
        self.items = items or []

    def scalars(self):
        return FakeScalarResult(self.items)


class FakeSession:
    def __init__(self, posts=None, control=None) -> None:
        self.posts = posts or []
        self.control = control
        self.flushed = False

    def add(self, obj) -> None:
        if isinstance(obj, EditorialControl):
            self.control = obj
        elif isinstance(obj, EditorialPost):
            if getattr(obj, "id", None) is None:
                obj.id = len(self.posts) + 1
            self.posts.append(obj)

    async def flush(self) -> None:
        self.flushed = True

    async def scalar(self, statement):
        text = str(statement)
        if "FROM editorial_control" in text:
            return self.control
        return None

    async def execute(self, statement):
        text = str(statement)
        if "FROM editorial_posts" in text:
            return FakeResult(
                [
                    post
                    for post in self.posts
                    if post.status == EditorialPostStatus.ready
                ]
            )
        return FakeResult()


class FakeCopywriter:
    async def generate_selection_post(self, movies):
        return {"title": "Что смотреть", "body": "Подборка", "hashtags": ["#подборка"]}

    async def generate_discussion_post(self, movie=None):
        return {
            "title": "Кино-вопрос",
            "body": "Что выбрать?",
            "options": ["Классика", "Премьера"],
            "hashtags": ["#опрос"],
        }


class FakePublisher:
    def __init__(self):
        self.cards = []

    async def publish_card(self, text, poster_url=None):
        self.cards.append((text, poster_url))
        return 777


def settings(**overrides):
    values = {
        "auto_publish_enabled": True,
        "news_min_interval_minutes": 35,
        "fallback_min_interval_hours": 4,
        "zoneinfo": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_news_interval_blocks_second_news_post() -> None:
    control = EditorialControl(
        id=1,
        autopublish_enabled=True,
        last_news_published_at=datetime(2026, 6, 15, 12, 0),
    )
    post = EditorialPost(
        id=1,
        post_type=EditorialPostType.news,
        status=EditorialPostStatus.ready,
        title="Trailer",
        text="Новый трейлер.",
        hashtags=["#новости"],
        image_url="https://example.com/poster.jpg",
    )
    service = EditorialService(FakeSession([post], control), settings(), FakeCopywriter())

    published = await service.maybe_publish_next(FakePublisher(), now=datetime(2026, 6, 15, 12, 20))

    assert published is None
    assert post.status == EditorialPostStatus.ready


async def test_news_interval_allows_publish_after_cadence() -> None:
    control = EditorialControl(
        id=1,
        autopublish_enabled=True,
        last_news_published_at=datetime(2026, 6, 15, 12, 0),
    )
    post = EditorialPost(
        id=1,
        post_type=EditorialPostType.news,
        status=EditorialPostStatus.ready,
        title="Trailer",
        text="Новый трейлер.",
        hashtags=["#новости"],
        image_url="https://example.com/poster.jpg",
    )
    publisher = FakePublisher()
    service = EditorialService(FakeSession([post], control), settings(), FakeCopywriter())

    published = await service.maybe_publish_next(publisher, now=datetime(2026, 6, 15, 12, 40))

    assert published is post
    assert post.status == EditorialPostStatus.published
    assert publisher.cards
