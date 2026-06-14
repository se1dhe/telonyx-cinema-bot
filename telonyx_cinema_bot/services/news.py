import logging
from datetime import datetime, timezone
from typing import Any

import feedparser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telonyx_cinema_bot.models import NewsPost, NewsStatus, NewsUrl
from telonyx_cinema_bot.services.gemini import GeminiCopywriter

logger = logging.getLogger(__name__)

# Fallback parser if Gemini isn't available
class FallbackNewsCopywriter:
    async def filter_news(self, news_items: list[dict[str, str]]) -> list[int]:
        return [item["id"] for item in news_items[:3]]

    async def generate_news_post(self, article: dict[str, str]) -> str:
        return f"🎬 **Новость**\n\n{article.get('title')}\n\n{article.get('description')}\n\n🔗 Источник: {article.get('link')}"

class NewsService:
    def __init__(self, session: AsyncSession, copywriter: GeminiCopywriter | FallbackNewsCopywriter) -> None:
        self.session = session
        self.copywriter = copywriter
        self.rss_feeds = [
            "https://variety.com/feed/",
            "https://deadline.com/feed/",
            "https://www.hollywoodreporter.com/feed/"
        ]

    async def fetch_and_prepare_news(self) -> int:
        """Fetch RSS, filter unique, deduplicate with Gemini, and save as pending drafts."""
        all_news = []
        for url in self.rss_feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:10]:  # Top 10 from each source
                    all_news.append({
                        "title": getattr(entry, "title", ""),
                        "description": getattr(entry, "description", ""),
                        "link": getattr(entry, "link", "")
                    })
            except Exception as e:
                logger.error(f"Error fetching RSS {url}: {e}")

        if not all_news:
            return 0

        # 1. Filter out URLs we have already processed
        links = [n["link"] for n in all_news if n["link"]]
        if not links:
            return 0

        stmt = select(NewsUrl.url).where(NewsUrl.url.in_(links))
        result = await self.session.execute(stmt)
        existing_urls = set(result.scalars().all())

        new_news = [n for n in all_news if n["link"] not in existing_urls]
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
                # Create pending NewsPost
                post = NewsPost(text=post_text, status=NewsStatus.pending)
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

    async def get_pending_news(self) -> list[NewsPost]:
        stmt = select(NewsPost).where(NewsPost.status == NewsStatus.pending)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def approve_news(self, post_id: int) -> NewsPost:
        stmt = select(NewsPost).where(NewsPost.id == post_id)
        result = await self.session.execute(stmt)
        post = result.scalar_one_or_none()
        if not post:
            raise ValueError(f"NewsPost {post_id} not found")
        post.status = NewsStatus.approved
        await self.session.commit()
        return post

    async def reject_news(self, post_id: int) -> None:
        stmt = select(NewsPost).where(NewsPost.id == post_id)
        result = await self.session.execute(stmt)
        post = result.scalar_one_or_none()
        if post:
            post.status = NewsStatus.rejected
            await self.session.commit()

    async def get_next_approved_news(self) -> NewsPost | None:
        stmt = select(NewsPost).where(NewsPost.status == NewsStatus.approved).order_by(NewsPost.created_at)
        result = await self.session.execute(stmt)
        return result.scalars().first()
