from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from telonyx_cinema_bot.models import Campaign, Draft, Film
from telonyx_cinema_bot.bot.publisher import AiogramPublisher
from telonyx_cinema_bot.services.formatting import (
    format_fact,
    format_poll_options,
    format_recommended_movie,
    format_recommendations,
    format_review,
    format_video_caption,
    poster_url_from_path,
)
from telonyx_cinema_bot.services.tmdb import MovieMetadata

class CampaignPublisherService:
    def __init__(self, session, publisher: AiogramPublisher):
        self.session = session
        self.publisher = publisher

    async def _get_campaign_for_date(self, local_date: date) -> Campaign | None:
        return await self.session.scalar(
            select(Campaign)
            .where(Campaign.local_date == local_date)
            .options(
                selectinload(Campaign.draft).selectinload(Draft.film),
            )
        )

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

    async def publish_teaser(self, local_date: date) -> None:
        campaign = await self._get_campaign_for_date(local_date)
        await self.publish_campaign_teaser(campaign)

    async def publish_campaign_teaser(self, campaign: Campaign | None) -> None:
        if not campaign or campaign.teaser_msg_id:
            return
        
        movie = self._metadata_from_film(campaign.draft.film)
        msg_id = await self.publisher.publish_video(
            campaign.draft.video_file_id, 
            caption=format_video_caption(movie, campaign.draft.review_text),
        )
        campaign.teaser_msg_id = msg_id
        await self.session.flush()

    async def publish_review(self, local_date: date) -> None:
        campaign = await self._get_campaign_for_date(local_date)
        if not campaign or campaign.review_msg_id:
            return

        movie = self._metadata_from_film(campaign.draft.film)
        text = format_review(movie, campaign.draft.review_text)
        
        msg_id = await self.publisher.publish_card(text, movie.poster_url)
        campaign.review_msg_id = msg_id
        await self.session.flush()

    async def publish_fact(self, local_date: date) -> None:
        campaign = await self._get_campaign_for_date(local_date)
        if not campaign or campaign.fact_msg_id:
            return

        movie = self._metadata_from_film(campaign.draft.film)
        text = format_fact(movie, campaign.draft.fact_text)
        
        msg_id = await self.publisher.publish_card(text, movie.poster_url)
        campaign.fact_msg_id = msg_id
        await self.session.flush()

    async def publish_recommendations(self, local_date: date) -> None:
        campaign = await self._get_campaign_for_date(local_date)
        if not campaign or campaign.recommendation_msg_id:
            return

        movie = self._metadata_from_film(campaign.draft.film)
        text = format_recommendations(movie, campaign.draft.recommendations_text)

        cards = [(text, movie.poster_url)]
        for item in movie.similar_movies[:3]:
            poster_url = poster_url_from_path(item.get("poster_path"))
            if poster_url:
                cards.append((format_recommended_movie(item), poster_url))

        message_ids = await self.publisher.publish_cards(cards)
        msg_id = message_ids[0]
        campaign.recommendation_msg_id = msg_id
        await self.session.flush()

    async def publish_poll(self, local_date: date) -> None:
        # Poll is published for the previous day's campaign
        campaign = await self._get_campaign_for_date(local_date)
        if not campaign or campaign.poll_msg_id:
            return

        movie = self._metadata_from_film(campaign.draft.film)
        options = format_poll_options(movie)
        
        text = f"Опрос по фильму <b>{movie.display_title}</b>"
        msg_id, poll_id = await self.publisher.publish_poll(text, options)
        
        campaign.poll_msg_id = msg_id
        campaign.poll_id = poll_id
        await self.session.flush()
