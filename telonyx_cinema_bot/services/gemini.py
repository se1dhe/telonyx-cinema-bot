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

    async def filter_editorial_news(self, news_items: list[dict[str, str]]) -> list[int]:
        if not news_items:
            return []

        items_str = ""
        for item in news_items:
            items_str += (
                f"ID: {item['id']} | TITLE: {item['title']} | "
                f"DESC: {item['description'][:500]}\n"
            )

        prompt = (
            "Ты главный редактор Telegram-канала о кино. Нужно выбрать только новости, "
            "которые реально интересны аудитории: премьеры, трейлеры, кастинг, крупные студии, "
            "фестивали, касса, заметные режиссеры и актеры. Отсекай проходняк, сплетни, "
            "слабый PR и дубли.\n"
            "Выбери максимум 2 новости из списка. Верни только ID через запятую.\n\n"
            f"{items_str}"
        )
        try:
            text = await self._generate_text(prompt)
            return [int(match.group()) for match in re.finditer(r"\d+", text)][:2]
        except Exception as exc:
            self._log_generation_error("editorial news filter", exc)
            return [item["id"] for item in news_items[:1]]

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

    async def generate_editorial_news_post(self, article: dict[str, str]) -> dict[str, object]:
        prompt = (
            "Сделай авторский Telegram-пост для кино-канала в стиле аккуратного киножурнала.\n"
            "Новость должна звучать как редакционный материал, а не как перевод RSS.\n"
            "Не добавляй внешние ссылки, markdown или HTML. Не выдумывай факты.\n"
            "Верни строго в формате:\n"
            "TITLE: короткий заголовок до 70 символов\n"
            "BODY: 2-4 предложения, до 650 символов\n"
            "TAGS: 3-5 хештегов через пробел, включая #новости\n\n"
            f"Оригинальный заголовок: {article.get('title')}\n"
            f"Описание: {article.get('description')}\n"
        )
        try:
            text = await self._generate_text(prompt)
            parsed = _parse_key_value_block(text)
            return {
                "title": parsed.get("TITLE") or article.get("title") or "Киноновость",
                "body": parsed.get("BODY") or article.get("description") or article.get("title") or "",
                "hashtags": _parse_tags(parsed.get("TAGS") or "#новости #кино #telonyxcinema"),
            }
        except Exception as exc:
            self._log_generation_error("editorial news post", exc)
            return await self.fallback.generate_editorial_news_post(article)

    async def generate_selection_post(self, movies: list[MovieMetadata]) -> dict[str, object]:
        movie_lines = "\n".join(
            f"- {movie.display_title}: {movie.overview or 'нет описания'}" for movie in movies[:5]
        )
        prompt = (
            "Собери вечернюю подборку для Telegram-канала о кино в стиле киножурнала.\n"
            "Без HTML, markdown и ссылок. До 750 символов.\n"
            "Верни строго:\n"
            "TITLE: короткий заголовок\n"
            "BODY: вступление и список фильмов с короткой причиной посмотреть\n"
            "TAGS: 3-5 хештегов, включая #подборка и #вечернеекино\n\n"
            f"Фильмы:\n{movie_lines}"
        )
        try:
            text = await self._generate_text(prompt)
            parsed = _parse_key_value_block(text)
            return {
                "title": parsed.get("TITLE") or "Что смотреть вечером",
                "body": parsed.get("BODY") or self.fallback._selection_body(movies),
                "hashtags": _parse_tags(parsed.get("TAGS") or "#подборка #вечернеекино #кино"),
            }
        except Exception as exc:
            self._log_generation_error("selection post", exc)
            return await self.fallback.generate_selection_post(movies)

    async def generate_discussion_post(self, movie: MovieMetadata | None = None) -> dict[str, object]:
        context = (
            f"Фильм для контекста: {movie.display_title}. Описание: {movie.overview or ''}"
            if movie
            else "Без конкретного фильма."
        )
        prompt = (
            "Придумай интересный интерактив для Telegram-канала о кино: вопрос или голосование, "
            "которое хочется обсудить. Стиль киножурнала, без кринжа. Без HTML и ссылок.\n"
            "Верни строго:\n"
            "TITLE: короткий заголовок\n"
            "BODY: вопрос/подводка до 400 символов\n"
            "OPTIONS: 2-4 варианта через точку с запятой\n"
            "TAGS: 3-5 хештегов, включая #опрос\n\n"
            f"{context}"
        )
        try:
            text = await self._generate_text(prompt)
            parsed = _parse_key_value_block(text)
            return {
                "title": parsed.get("TITLE") or "Кино-вопрос",
                "body": parsed.get("BODY") or "Какой фильм вы бы пересмотрели сегодня вечером?",
                "options": [
                    option.strip()[:100]
                    for option in (parsed.get("OPTIONS") or "Классика; Новинка; Что-то странное").split(";")
                    if option.strip()
                ][:4],
                "hashtags": _parse_tags(parsed.get("TAGS") or "#опрос #кино #telonyxcinema"),
            }
        except Exception as exc:
            self._log_generation_error("discussion post", exc)
            return await self.fallback.generate_discussion_post(movie)


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

    async def generate_editorial_news_post(self, article: dict[str, str]) -> dict[str, object]:
        body = (article.get("description") or article.get("title") or "").strip()
        return {
            "title": article.get("title") or "Киноновость",
            "body": body[:650],
            "hashtags": ["#новости", "#кино", "#telonyxcinema"],
        }

    def _selection_body(self, movies: list[MovieMetadata]) -> str:
        lines = ["Подборка для вечера, когда хочется не просто включить фон, а выбрать настроение."]
        for movie in movies[:5]:
            lines.append(f"{movie.display_title} — {movie.overview or 'сильный вариант для просмотра.'}")
        return "\n".join(lines)[:750]

    async def generate_selection_post(self, movies: list[MovieMetadata]) -> dict[str, object]:
        return {
            "title": "Что смотреть вечером",
            "body": self._selection_body(movies),
            "hashtags": ["#подборка", "#вечернеекино", "#смотретьсегодня"],
        }

    async def generate_discussion_post(self, movie: MovieMetadata | None = None) -> dict[str, object]:
        title = "Кино-вопрос"
        body = "Какой фильм вы бы выбрали на вечер: проверенную классику или премьеру, о которой все говорят?"
        return {
            "title": title,
            "body": body,
            "options": ["Классика", "Премьера", "Авторское кино"],
            "hashtags": ["#опрос", "#кино", "#telonyxcinema"],
        }


def _parse_campaign_texts(text: str) -> tuple[str, str, str] | None:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().upper() in {"REVIEW", "FACT", "RECS"}:
            values[key.strip().upper()] = value.strip()

    if {"REVIEW", "FACT", "RECS"} <= values.keys():
        return values["REVIEW"], values["FACT"], values["RECS"]
    return None


def _parse_key_value_block(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    current_key: str | None = None
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        clean_key = key.strip().upper()
        if separator and clean_key in {"TITLE", "BODY", "TAGS", "OPTIONS"}:
            current_key = clean_key
            values[current_key] = value.strip()
        elif current_key and line.strip():
            values[current_key] = f"{values[current_key]}\n{line.strip()}".strip()
    return values


def _parse_tags(text: str) -> list[str]:
    tags = []
    for token in re.split(r"[\s,]+", text):
        token = token.strip()
        if not token:
            continue
        if not token.startswith("#"):
            token = f"#{token}"
        tags.append(token.replace(" ", ""))
    return list(dict.fromkeys(tags))
