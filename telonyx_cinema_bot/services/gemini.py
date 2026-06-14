from __future__ import annotations

from google import genai

from telonyx_cinema_bot.services.tmdb import MovieMetadata


class GeminiCopywriter:
    def __init__(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-1.5-flash"

    async def generate_review(self, movie: MovieMetadata) -> str:
        prompt = (
            "Напиши одну короткую эмоциональную строку на русском для Telegram-канала о кино. "
            "Не выдумывай факты. До 24 слов. Без эмодзи. "
            f"Фильм: {movie.display_title}. Описание: {movie.overview or 'Нет описания'}."
        )
        response = await self.client.aio.models.generate_content(model=self.model, contents=prompt)
        return (response.text or "").strip()

    async def generate_fact(self, movie: MovieMetadata) -> str:
        prompt = (
            "Напиши один короткий, 100% реальный факт о фильме или точную цитату из него. "
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выдумывать информацию. Используй только общеизвестные факты. "
            f"Фильм: {movie.display_title}."
        )
        response = await self.client.aio.models.generate_content(model=self.model, contents=prompt)
        return (response.text or "").strip()


    async def generate_recommendations(self, movie: MovieMetadata) -> str:
        similar = ", ".join(m["title"] for m in movie.similar_movies[:3])
        prompt = (
            "Напиши короткий призыв посмотреть похожие фильмы на вечер. "
            f"Фильм: {movie.display_title}. Похожие: {similar}. "
            "Формат: пара предложений (до 30 слов). Без списков и буллитов."
        )
        response = await self.client.aio.models.generate_content(model=self.model, contents=prompt)
        return (response.text or "").strip()


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
