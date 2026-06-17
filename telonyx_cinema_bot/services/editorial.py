from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from telonyx_cinema_bot.bot.publisher import AiogramPublisher
from telonyx_cinema_bot.config import Settings
from telonyx_cinema_bot.models import (
    EditorialControl,
    EditorialPost,
    EditorialPostStatus,
    EditorialPostType,
    Film,
)
from telonyx_cinema_bot.services.formatting import format_editorial_post, poster_url_from_path
from telonyx_cinema_bot.services.tmdb import MovieMetadata

logger = logging.getLogger(__name__)


class EditorialCopywriter(Protocol):
    async def generate_selection_post(self, movies: list[MovieMetadata]) -> dict[str, object]: ...
    async def generate_discussion_post(self, movie: MovieMetadata | None = None) -> dict[str, object]: ...


class EditorialService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        copywriter: EditorialCopywriter,
    ) -> None:
        self.session = session
        self.settings = settings
        self.copywriter = copywriter

    async def get_or_create_control(self) -> EditorialControl:
        control = await self.session.scalar(select(EditorialControl).where(EditorialControl.id == 1))
        if control is None:
            control = EditorialControl(
                id=1,
                autopublish_enabled=self.settings.auto_publish_enabled,
            )
            self.session.add(control)
            await self.session.flush()
        return control

    async def set_autopublish(self, enabled: bool) -> EditorialControl:
        control = await self.get_or_create_control()
        control.autopublish_enabled = enabled
        if enabled:
            control.paused_until = None
        await self.session.flush()
        return control

    async def pause_for_hours(self, hours: int, now: datetime | None = None) -> EditorialControl:
        now = now or datetime.now(self.settings.zoneinfo)
        control = await self.get_or_create_control()
        control.paused_until = now + timedelta(hours=hours)
        await self.session.flush()
        return control

    async def queue_status(self, limit: int = 10) -> list[EditorialPost]:
        result = await self.session.execute(
            select(EditorialPost)
            .where(EditorialPost.status == EditorialPostStatus.ready)
            .order_by(EditorialPost.scheduled_for.is_(None), EditorialPost.scheduled_for, EditorialPost.created_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def enqueue_review_post(self, movie: MovieMetadata) -> EditorialPost | None:
        data = await self.copywriter.generate_review_post(movie)
        return await self.enqueue_post(
            post_type=EditorialPostType.review,
            title=str(data.get("title") or movie.display_title),
            text=str(data.get("body") or ""),
            hashtags=list(data.get("hashtags") or ["#кино", "#рецензия"]),
            image_url=movie.poster_url,
            metadata={
                "tmdb_id": movie.tmdb_id,
                "poster_path": movie.poster_path,
            },
        )

    async def enqueue_post(
        self,
        *,
        post_type: EditorialPostType,
        title: str | None,
        text: str,
        hashtags: list[str],
        image_url: str | None = None,
        video_url: str | None = None,
        source_url: str | None = None,
        source_key: str | None = None,
        metadata: dict | None = None,
        scheduled_for: datetime | None = None,
    ) -> EditorialPost | None:
        if source_key:
            existing = await self.session.scalar(
                select(EditorialPost).where(EditorialPost.source_key == source_key)
            )
            if existing is not None:
                return None

        post = EditorialPost(
            post_type=post_type,
            status=EditorialPostStatus.ready,
            title=title,
            text=text,
            hashtags=hashtags,
            image_url=image_url,
            video_url=video_url,
            source_url=source_url,
            source_key=source_key,
            metadata_json=metadata or {},
            scheduled_for=scheduled_for,
        )
        self.session.add(post)
        await self.session.flush()
        return post

    async def maybe_publish_next(
        self,
        publisher: AiogramPublisher,
        now: datetime | None = None,
    ) -> EditorialPost | None:
        now = now or datetime.now(self.settings.zoneinfo)
        control = await self.get_or_create_control()
        if not self._can_publish(control, now):
            logger.info("Skipping publish: autopublish disabled or paused (control=%s, now=%s)", control.autopublish_enabled, now)
            return None

        post = await self._next_ready_post(now)
        if post is None:
            post = await self._ensure_fallback_post(now)
        if post is None:
            logger.info("No posts ready or eligible for fallback")
            return None

        if post.post_type == EditorialPostType.news and not self._news_interval_elapsed(control, now):
            logger.info("Skipping news post %s: news interval not elapsed", post.id)
            return None
        if post.image_url is None and post.post_type in {
            EditorialPostType.news,
            EditorialPostType.review,
            EditorialPostType.selection,
        }:
            logger.info("Skipping %s post %s: no image_url", post.post_type, post.id)
            post.status = EditorialPostStatus.skipped
            await self.session.flush()
            return None

        try:
            msg_id = await self._publish_post(publisher, post)
        except Exception:
            logger.exception("Failed to publish editorial post %s", post.id)
            post.status = EditorialPostStatus.failed
            await self.session.flush()
            return None

        post.status = EditorialPostStatus.published
        post.published_at = now
        post.published_msg_id = msg_id
        if post.post_type == EditorialPostType.news:
            control.last_news_published_at = now
        else:
            control.last_fallback_published_at = now
        await self.session.flush()
        logger.info("Published editorial post %s (type=%s, title=%s)", post.id, post.post_type, post.title)
        return post

    def _can_publish(self, control: EditorialControl, now: datetime) -> bool:
        if not self.settings.auto_publish_enabled or not control.autopublish_enabled:
            return False
        if control.paused_until and control.paused_until > now:
            return False
        return True

    def _news_interval_elapsed(self, control: EditorialControl, now: datetime) -> bool:
        if control.last_news_published_at is None:
            return True
        elapsed = now - control.last_news_published_at
        return elapsed >= timedelta(minutes=self.settings.news_min_interval_minutes)

    async def _next_ready_post(self, now: datetime) -> EditorialPost | None:
        result = await self.session.execute(
            select(EditorialPost)
            .where(EditorialPost.status == EditorialPostStatus.ready)
            .where((EditorialPost.scheduled_for.is_(None)) | (EditorialPost.scheduled_for <= now))
            .order_by(EditorialPost.scheduled_for.is_(None), EditorialPost.scheduled_for, EditorialPost.created_at)
            .limit(1)
        )
        return result.scalars().first()

    async def _ensure_fallback_post(self, now: datetime) -> EditorialPost | None:
        control = await self.get_or_create_control()
        if control.last_fallback_published_at:
            elapsed = now - control.last_fallback_published_at
            if elapsed < timedelta(hours=self.settings.fallback_min_interval_hours):
                return None

        movies = await self._fallback_movies()
        if not movies:
            data = await self.copywriter.generate_discussion_post(None)
            return await self.enqueue_post(
                post_type=EditorialPostType.poll,
                title=str(data.get("title") or "Кино-вопрос"),
                text=str(data.get("body") or "Какой фильм выбрать на вечер?"),
                hashtags=list(data.get("hashtags") or ["#опрос", "#кино"]),
                metadata={"options": list(data.get("options") or ["Классика", "Премьера"])},
            )

        poster_urls = [poster_url_from_path(m.poster_path) for m in movies[:3] if m.poster_path]
        data = await self.copywriter.generate_selection_post(movies)
        return await self.enqueue_post(
            post_type=EditorialPostType.selection,
            title=str(data.get("title") or "Что смотреть вечером"),
            text=str(data.get("body") or ""),
            hashtags=list(data.get("hashtags") or ["#подборка", "#вечернеекино"]),
            image_url=poster_urls[0] if poster_urls else None,
            metadata={
                "tmdb_ids": [movie.tmdb_id for movie in movies],
                "titles": [movie.display_title for movie in movies[:3]],
                "poster_urls": poster_urls,
            },
        )

    async def _fallback_movies(self) -> list[MovieMetadata]:
        result = await self.session.execute(
            select(Film)
            .where(Film.poster_path.is_not(None))
            .where(Film.poster_path != "")
            .order_by(func.random())
            .limit(5)
        )
        return [self._metadata_from_film(film) for film in result.scalars()]

    def _metadata_from_film(self, film: Film) -> MovieMetadata:
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

    async def _publish_post(self, publisher: AiogramPublisher, post: EditorialPost) -> int:
        text = format_editorial_post(post, channel_link=self.settings.channel_link)
        if post.post_type == EditorialPostType.poll:
            options = [str(option)[:100] for option in post.metadata_json.get("options", [])]
            if len(options) >= 2:
                msg_id, _poll_id = await publisher.publish_poll(text, options[:4])
                return msg_id

        if post.post_type == EditorialPostType.selection:
            poster_urls: list[str] = post.metadata_json.get("poster_urls", [])
            if len(poster_urls) >= 2:
                movie_titles: list[str] = post.metadata_json.get("titles", [])
                media_items = [(text, poster_urls[0])]
                for i, url in enumerate(poster_urls[1:], start=1):
                    title = movie_titles[i] if i < len(movie_titles) else ""
                    cap = f"<b>{title}</b>" if title else "🎬"
                    media_items.append((cap, url))
                return await publisher.publish_media_group(media_items, common_caption=text)

        image_url = post.image_url or poster_url_from_path(post.metadata_json.get("poster_path"))
        return await publisher.publish_card(text, image_url)
