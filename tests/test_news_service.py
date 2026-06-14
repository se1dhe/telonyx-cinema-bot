from types import SimpleNamespace

import pytest

from telonyx_cinema_bot.db import create_engine, create_schema, create_session_factory
from telonyx_cinema_bot.models import NewsPost, NewsStatus
from telonyx_cinema_bot.services.news import NewsService, _entry_image_urls


class FakeCopywriter:
    async def filter_news(self, news_items: list[dict[str, str]]) -> list[int]:
        return [item["id"] for item in news_items]

    async def generate_news_post(self, article: dict[str, str]) -> str:
        return article["description"]


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


@pytest.fixture
async def session_factory():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    await create_schema(engine)
    factory = create_session_factory(engine)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_get_next_approved_news_skips_posts_without_images(session_factory) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                NewsPost(
                    title="No image",
                    text="Body",
                    source_url="https://example.com/no-image",
                    status=NewsStatus.approved,
                )
            )
            session.add(
                NewsPost(
                    title="With image",
                    text="Body",
                    source_url="https://example.com/with-image",
                    image_url="https://example.com/poster.jpg",
                    image_urls=["https://example.com/poster.jpg"],
                    status=NewsStatus.approved,
                )
            )

    async with session_factory() as session:
        service = NewsService(session, FakeCopywriter())
        post = await service.get_next_approved_news()

    assert post is not None
    assert post.title == "With image"
