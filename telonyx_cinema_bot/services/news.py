import logging
from datetime import datetime

import feedparser
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from telonyx_cinema_bot.models import NewsPost, NewsStatus, NewsUrl
from telonyx_cinema_bot.models import EditorialPostType
from telonyx_cinema_bot.services.editorial import EditorialService
from telonyx_cinema_bot.services.gemini import GeminiCopywriter

logger = logging.getLogger(__name__)


def _entry_image_urls(entry) -> list[str]:
    urls: list[str] = []

    media_content = getattr(entry, "media_content", None) or []
    for media in media_content:
        url = media.get("url") if isinstance(media, dict) else None
        medium = media.get("medium") if isinstance(media, dict) else None
        if url and (medium in (None, "image") or _looks_like_image(url)):
            urls.append(url)

    media_thumbnail = getattr(entry, "media_thumbnail", None) or []
    for media in media_thumbnail:
        url = media.get("url") if isinstance(media, dict) else None
        if url:
            urls.append(url)

    links = getattr(entry, "links", None) or []
    for link in links:
        href = link.get("href") if isinstance(link, dict) else None
        link_type = link.get("type") if isinstance(link, dict) else None
        if href and (str(link_type).startswith("image/") or _looks_like_image(href)):
            urls.append(href)

    return list(dict.fromkeys(urls))


def _looks_like_image(url: str) -> bool:
    return url.lower().split("?", 1)[0].endswith((".jpg", ".jpeg", ".png", ".webp"))


# Fallback parser if Gemini isn't available
class FallbackNewsCopywriter:
    async def filter_news(self, news_items: list[dict[str, str]]) -> list[int]:
        return [item["id"] for item in news_items[:3]]

    async def generate_news_post(self, article: dict[str, str]) -> str:
        return article.get("description") or article.get("title") or ""

class NewsService:
    def __init__(self, session: AsyncSession, copywriter: GeminiCopywriter | FallbackNewsCopywriter) -> None:
        self.session = session
        self.copywriter = copywriter
        self.rss_feeds = [
            "https://variety.com/feed/",
            "https://deadline.com/feed/",
            "https://www.hollywoodreporter.com/feed/"
        ]

    async def fetch_and_enqueue_editorial_news(self, editorial: EditorialService) -> int:
        """Fetch RSS and add selected poster-backed news to the editorial queue."""
        all_news = await self._fetch_rss_news()
        if not all_news:
            return 0

        links = [item["link"] for item in all_news if item["link"]]
        if not links:
            return 0

        existing_news = await self.session.execute(select(NewsUrl.url).where(NewsUrl.url.in_(links)))
        processed_urls = set(existing_news.scalars().all())
        existing_posts = await self.session.execute(
            select(editorial_post_source_key())
            .where(editorial_post_source_key().in_(links))
        )
        processed_urls.update(url for url in existing_posts.scalars().all() if url)

        new_news = [
            item
            for item in all_news
            if item["link"] not in processed_urls and item["images"]
        ]
        if not new_news:
            return 0

        for i, item in enumerate(new_news):
            item["id"] = i

        if hasattr(self.copywriter, "filter_editorial_news"):
            selected_ids = await self.copywriter.filter_editorial_news(new_news)
        else:
            selected_ids = await self.copywriter.filter_news(new_news)
        selected_news = [item for item in new_news if item["id"] in selected_ids]

        generated = 0
        for item in selected_news:
            if hasattr(self.copywriter, "generate_editorial_news_post"):
                data = await self.copywriter.generate_editorial_news_post(item)
            else:
                data = {
                    "title": item.get("title") or "Киноновость",
                    "body": await self.copywriter.generate_news_post(item),
                    "hashtags": ["#новости", "#кино", "#telonyxcinema"],
                }
            post = await editorial.enqueue_post(
                post_type=EditorialPostType.news,
                title=str(data.get("title") or item.get("title") or "Киноновость"),
                text=str(data.get("body") or item.get("description") or ""),
                hashtags=list(data.get("hashtags") or ["#новости", "#кино"]),
                image_url=item["images"][0],
                source_url=item.get("link"),
                source_key=item.get("link"),
                metadata={
                    "source_title": item.get("title"),
                    "source_description": item.get("description"),
                    "image_urls": item.get("images", []),
                },
            )
            if post is not None:
                generated += 1

        for item in new_news:
            if item["link"]:
                self.session.add(NewsUrl(url=item["link"]))
        await self.session.commit()
        return generated

    async def has_news_for_date(self, day) -> bool:
        stmt = (
            select(func.count(NewsPost.id))
            .where(NewsPost.status.in_([NewsStatus.approved, NewsStatus.published]))
            .where(func.date(NewsPost.scheduled_for) == day)
        )
        result = await self.session.execute(stmt)
        return bool(result.scalar())

    async def has_pending_news(self) -> bool:
        stmt = select(func.count(NewsPost.id)).where(NewsPost.status == NewsStatus.pending)
        result = await self.session.execute(stmt)
        return bool(result.scalar())

    async def fetch_and_prepare_news(self) -> int:
        """Fetch RSS, filter unique, deduplicate with Gemini, and save as pending drafts."""
        all_news = await self._fetch_rss_news()

        if not all_news:
            return 0

        # 1. Filter out URLs we have already processed
        links = [n["link"] for n in all_news if n["link"]]
        if not links:
            return 0

        stmt = select(NewsUrl.url).where(NewsUrl.url.in_(links))
        result = await self.session.execute(stmt)
        existing_urls = set(result.scalars().all())

        new_news = [n for n in all_news if n["link"] not in existing_urls and n["images"]]
        if not new_news:
            return 0

        # Assign temp IDs for Gemini
        for i, item in enumerate(new_news):
            item["id"] = i

        # 2. Ask Gemini to filter and deduplicate
        selected_ids = await self.copywriter.filter_news(new_news)
        selected_news = [n for n in new_news if n["id"] in selected_ids]

        # 3. For selected news, generate posts and save to DB
        generated_count = 0
        for item in selected_news:
            try:
                post_text = await self.copywriter.generate_news_post(item)
                post = NewsPost(
                    title=item.get("title"),
                    text=post_text,
                    source_url=item.get("link"),
                    image_url=item["images"][0],
                    image_urls=item["images"],
                    status=NewsStatus.pending,
                )
                self.session.add(post)
                
                # Mark URL as processed
                news_url = NewsUrl(url=item["link"])
                self.session.add(news_url)
                
                generated_count += 1
            except Exception as e:
                logger.error(f"Failed to generate news post for {item['link']}: {e}")

        # Mark non-selected URLs as processed as well to avoid asking Gemini again
        non_selected = [n for n in new_news if n["id"] not in selected_ids]
        for item in non_selected:
            self.session.add(NewsUrl(url=item["link"]))

        await self.session.commit()
        return generated_count

    async def _fetch_rss_news(self) -> list[dict]:
        all_news = []
        for url in self.rss_feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:10]:
                    all_news.append({
                        "title": getattr(entry, "title", ""),
                        "description": getattr(entry, "description", ""),
                        "link": getattr(entry, "link", ""),
                        "images": _entry_image_urls(entry),
                    })
            except Exception as e:
                logger.error(f"Error fetching RSS {url}: {e}")
        return all_news

    async def clear_news_queue(self) -> int:
        post_result = await self.session.execute(delete(NewsPost))
        url_result = await self.session.execute(delete(NewsUrl))
        await self.session.commit()
        return max(post_result.rowcount or 0, 0) + max(url_result.rowcount or 0, 0)

    async def get_pending_news(self) -> list[NewsPost]:
        stmt = select(NewsPost).where(NewsPost.status == NewsStatus.pending)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def approve_news(self, post_id: int, now: datetime | None = None) -> NewsPost:
        stmt = select(NewsPost).where(NewsPost.id == post_id)
        result = await self.session.execute(stmt)
        post = result.scalar_one_or_none()
        if not post:
            raise ValueError(f"NewsPost {post_id} not found")
        post.status = NewsStatus.approved
        post.scheduled_for = now or datetime.now()
        await self.session.commit()
        return post

    async def reject_news(self, post_id: int) -> None:
        stmt = select(NewsPost).where(NewsPost.id == post_id)
        result = await self.session.execute(stmt)
        post = result.scalar_one_or_none()
        if post:
            post.status = NewsStatus.rejected
            await self.session.commit()

    async def get_next_approved_news(self, day=None) -> NewsPost | None:
        stmt = (
            select(NewsPost)
            .where(NewsPost.status == NewsStatus.approved)
            .where(NewsPost.image_url.is_not(None))
            .where(NewsPost.image_url != "")
            .order_by(NewsPost.scheduled_for, NewsPost.created_at)
        )
        if day is not None:
            stmt = stmt.where(func.date(NewsPost.scheduled_for) == day)
        result = await self.session.execute(stmt)
        return result.scalars().first()


def editorial_post_source_key():
    from telonyx_cinema_bot.models import EditorialPost

    return EditorialPost.source_key
