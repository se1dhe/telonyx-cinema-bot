from types import SimpleNamespace
from datetime import datetime

from telonyx_cinema_bot.models import NewsPost, NewsStatus
from telonyx_cinema_bot.services.news import NewsService, _entry_image_urls


class FakeCopywriter:
    async def filter_news(self, news_items: list[dict[str, str]]) -> list[int]:
        return [item["id"] for item in news_items]

    async def generate_news_post(self, article: dict[str, str]) -> str:
        return article["description"]


class FakeScalarResult:
    def __init__(self, items):
        self.items = items

    def first(self):
        return self.items[0] if self.items else None


class FakeResult:
    def __init__(self, items):
        self.items = items

    def scalars(self):
        return FakeScalarResult(self.items)


class FakeSession:
    def __init__(self, posts: list[NewsPost]) -> None:
        self.posts = posts

    async def execute(self, statement):
        text = str(statement)
        params = statement.compile().params
        day = params.get("date_1") if "date(news_posts.scheduled_for)" in text else None
        return FakeResult(
            [
                post
                for post in self.posts
                if post.status == NewsStatus.approved and post.image_url
                and (day is None or post.scheduled_for.date() == day)
            ]
        )


def test_entry_image_urls_reads_media_content() -> None:
    entry = SimpleNamespace(
        media_content=[
            {
                "url": "https://example.com/poster.jpg",
                "medium": "image",
            }
        ]
    )

    assert _entry_image_urls(entry) == ["https://example.com/poster.jpg"]


def test_entry_image_urls_reads_html_summary_images() -> None:
    entry = SimpleNamespace(
        summary='<p><img src="https://example.com/trailer-poster.webp?width=1200"></p>'
    )

    assert _entry_image_urls(entry) == ["https://example.com/trailer-poster.webp?width=1200"]


async def test_get_next_approved_news_skips_posts_without_images() -> None:
    service = NewsService(
        FakeSession(
            [
                NewsPost(
                    title="No image",
                    text="Body",
                    source_url="https://example.com/no-image",
                    status=NewsStatus.approved,
                ),
                NewsPost(
                    title="With image",
                    text="Body",
                    source_url="https://example.com/with-image",
                    image_url="https://example.com/poster.jpg",
                    image_urls=["https://example.com/poster.jpg"],
                    status=NewsStatus.approved,
                    scheduled_for=datetime(2026, 6, 14, 12, 0),
                ),
            ]
        ),
        FakeCopywriter(),
    )
    post = await service.get_next_approved_news()

    assert post is not None
    assert post.title == "With image"


async def test_get_next_approved_news_filters_by_day() -> None:
    service = NewsService(
        FakeSession(
            [
                NewsPost(
                    title="Yesterday",
                    text="Body",
                    image_url="https://example.com/yesterday.jpg",
                    status=NewsStatus.approved,
                    scheduled_for=datetime(2026, 6, 13, 12, 0),
                ),
                NewsPost(
                    title="Today",
                    text="Body",
                    image_url="https://example.com/today.jpg",
                    status=NewsStatus.approved,
                    scheduled_for=datetime(2026, 6, 14, 12, 0),
                ),
            ]
        ),
        FakeCopywriter(),
    )

    post = await service.get_next_approved_news(datetime(2026, 6, 14).date())

    assert post is not None
    assert post.title == "Today"
