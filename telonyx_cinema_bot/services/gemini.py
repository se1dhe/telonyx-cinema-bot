from __future__ import annotations

import logging
import re

from google import genai

from telonyx_cinema_bot.services.tmdb import MovieMetadata

logger = logging.getLogger(__name__)


class GeminiCopywriter:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.fallback = FallbackCopywriter()

    async def _generate_text(self, prompt: str) -> str:
        response = await self.client.aio.models.generate_content(model=self.model, contents=prompt)
        return (response.text or "").strip()

    async def generate_review(self, movie: MovieMetadata) -> str:
        prompt = (
            "Напиши одну короткую эмоциональную строку на русском для Telegram-канала о кино. "
            "Не выдумывай факты. До 24 слов. Без эмодзи. "
            f"Фильм: {movie.display_title}. Описание: {movie.overview or 'Нет описания'}."
        )
        try:
            return await self._generate_text(prompt)
        except Exception:
            logger.exception("Gemini failed to generate review with model %s", self.model)
            return await self.fallback.generate_review(movie)

    async def generate_fact(self, movie: MovieMetadata) -> str:
        prompt = (
            "Напиши один короткий, 100% реальный факт о фильме или точную цитату из него. "
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выдумывать информацию. Используй только общеизвестные факты. "
            f"Фильм: {movie.display_title}."
        )
        try:
            return await self._generate_text(prompt)
        except Exception:
            logger.exception("Gemini failed to generate fact with model %s", self.model)
            return await self.fallback.generate_fact(movie)


    async def generate_recommendations(self, movie: MovieMetadata) -> str:
        similar = ", ".join(m["title"] for m in movie.similar_movies[:3])
        prompt = (
            "Напиши короткий призыв посмотреть похожие фильмы на вечер. "
            f"Фильм: {movie.display_title}. Похожие: {similar}. "
            "Формат: пара предложений (до 30 слов). Без списков и буллитов."
        )
        try:
            return await self._generate_text(prompt)
        except Exception:
            logger.exception("Gemini failed to generate recommendations with model %s", self.model)
            return await self.fallback.generate_recommendations(movie)

    async def filter_news(self, news_items: list[dict[str, str]]) -> list[int]:
        """Returns a list of IDs of news items that are worth publishing."""
        if not news_items:
            return []
        
        # Prepare list for prompt
        items_str = ""
        for item in news_items:
            items_str += f"ID: {item['id']} | TITLE: {item['title']} | DESC: {item['description']}\n"
            
        prompt = (
            "You are a professional cinema news editor. Here is a list of recent news articles.\n"
            "Task: Select the most important, unique, and interesting news. Ignore cheap gossip, clickbait, and duplicates (if two articles are about the exact same thing, pick one).\n"
            "Return ONLY a comma-separated list of IDs you selected. Do not write anything else.\n"
            f"Articles:\n{items_str}"
        )
        try:
            text = await self._generate_text(prompt)
            selected_ids = []
            for match in re.finditer(r'\d+', text):
                selected_ids.append(int(match.group()))
            return selected_ids
        except Exception:
            logger.exception("Gemini failed to filter news with model %s", self.model)
            return [item['id'] for item in news_items[:3]]  # Fallback to first 3

    async def generate_news_post(self, article: dict[str, str]) -> str:
        prompt = (
            "Напиши новостной пост для Telegram-канала о кино на русском языке.\n"
            "Стиль: серьезный, информативный, без дешевых заигрываний ('Привет, киноманы'). Можно использовать пару тематических эмодзи.\n"
            f"Оригинальный заголовок: {article.get('title')}\n"
            f"Описание: {article.get('description')}\n"
            "Сделай пост кратким (до 100 слов), с привлекательным заголовком."
        )
        try:
            return await self._generate_text(prompt)
        except Exception:
            logger.exception("Gemini failed to generate news post with model %s", self.model)
            title = article.get("title") or "Киноновость"
            description = article.get("description") or ""
            return f"<b>{title}</b>\n\n{description}".strip()


class FallbackCopywriter:
    async def generate_review(self, movie: MovieMetadata) -> str:
        if movie.overview:
            first_sentence = movie.overview.split(".")[0].strip()
            if first_sentence:
                return first_sentence[:180]
        return "Кинонастроение, которое стоит сохранить для правильного вечера."

    async def generate_fact(self, movie: MovieMetadata) -> str:
        return f"Погрузитесь в атмосферу фильма {movie.title}."

    async def generate_recommendations(self, movie: MovieMetadata) -> str:
        return "Если вам понравился этот фильм, обратите внимание на похожие картины."
