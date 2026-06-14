from __future__ import annotations

import google.generativeai as genai

from telonyx_cinema_bot.services.tmdb import MovieMetadata


class GeminiCopywriter:
    def __init__(self, api_key: str) -> None:
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    async def emotional_description(self, movie: MovieMetadata) -> str:
        prompt = (
            "Write one short emotional Telegram line for a cinema channel. "
            "Do not invent facts. Keep it under 24 words. "
            f"Movie: {movie.display_title}. Overview: {movie.overview or 'No overview'}."
        )
        response = await self.model.generate_content_async(prompt)
        return (response.text or "").strip()


class FallbackCopywriter:
    async def emotional_description(self, movie: MovieMetadata) -> str:
        if movie.overview:
            first_sentence = movie.overview.split(".")[0].strip()
            if first_sentence:
                return first_sentence[:180]
        return "A cinematic mood worth saving for the right night."

