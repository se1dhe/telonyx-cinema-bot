from __future__ import annotations

import logging
import re

from google import genai
from google.genai import errors

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

    def _log_generation_error(self, task: str, exc: Exception) -> None:
        status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if isinstance(exc, errors.ClientError) and status_code == 429:
            logger.warning("Gemini quota exhausted while generating %s with model %s", task, self.model)
            return
        logger.exception("Gemini failed to generate %s with model %s", task, self.model)

    async def generate_campaign_texts(self, movie: MovieMetadata) -> tuple[str, str, str]:
        similar = ", ".join(m["title"] for m in movie.similar_movies[:3]) or "нет данных"
        prompt = (
            "Сгенерируй тексты для Telegram-кампании о фильме на русском языке.\n"
            "Верни строго 3 строки в формате:\n"
            "REVIEW: одна короткая эмоциональная строка до 24 слов, без эмодзи\n"
            "FACT: один осторожный факт или нейтральная фраза без выдуманных деталей\n"
            "RECS: короткий призыв посмотреть похожие фильмы до 30 слов\n"
            "Без markdown, HTML и списков.\n"
            f"Фильм: {movie.display_title}. Описание: {movie.overview or 'Нет описания'}. "
            f"Похожие: {similar}."
        )
        try:
            text = await self._generate_text(prompt)
            parsed = _parse_campaign_texts(text)
            if parsed:
                return parsed
        except Exception as exc:
            self._log_generation_error("campaign texts", exc)

        return (
            await self.fallback.generate_review(movie),
            await self.fallback.generate_fact(movie),
            await self.fallback.generate_recommendations(movie),
        )

    async def generate_review(self, movie: MovieMetadata) -> str:
        prompt = (
            "Напиши одну короткую эмоциональную строку на русском для Telegram-канала о кино. "
            "Не выдумывай факты. До 24 слов. Без эмодзи. "
            f"Фильм: {movie.display_title}. Описание: {movie.overview or 'Нет описания'}."
        )
        try:
            return await self._generate_text(prompt)
        except Exception as exc:
            self._log_generation_error("review", exc)
            return await self.fallback.generate_review(movie)

    async def generate_fact(self, movie: MovieMetadata) -> str:
        prompt = (
            "Напиши один короткий, 100% реальный факт о фильме или точную цитату из него. "
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выдумывать информацию. Используй только общеизвестные факты. "
            f"Фильм: {movie.display_title}."
        )
        try:
            return await self._generate_text(prompt)
        except Exception as exc:
            self._log_generation_error("fact", exc)
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
        except Exception as exc:
            self._log_generation_error("recommendations", exc)
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
        except Exception as exc:
            self._log_generation_error("news filter", exc)
            return [item['id'] for item in news_items[:3]]  # Fallback to first 3

    async def generate_news_post(self, article: dict[str, str]) -> str:
        prompt = (
            "Напиши краткий текст новости для Telegram-канала о кино на русском языке.\n"
            "Верни только основной текст без заголовка, markdown, HTML, списков и ссылок.\n"
            "Стиль: серьезный, информативный, без дешевых заигрываний ('Привет, киноманы').\n"
            f"Оригинальный заголовок: {article.get('title')}\n"
            f"Описание: {article.get('description')}\n"
            "До 70 слов. Не выдумывай факты и цифры."
        )
        try:
            return await self._generate_text(prompt)
        except Exception as exc:
            self._log_generation_error("news post", exc)
            return (article.get("description") or article.get("title") or "").strip()


class FallbackCopywriter:
    async def generate_campaign_texts(self, movie: MovieMetadata) -> tuple[str, str, str]:
        return (
            await self.generate_review(movie),
            await self.generate_fact(movie),
            await self.generate_recommendations(movie),
        )

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


def _parse_campaign_texts(text: str) -> tuple[str, str, str] | None:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().upper() in {"REVIEW", "FACT", "RECS"}:
            values[key.strip().upper()] = value.strip()

    if {"REVIEW", "FACT", "RECS"} <= values.keys():
        return values["REVIEW"], values["FACT"], values["RECS"]
    return None
