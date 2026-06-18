from __future__ import annotations

import logging
import re

from openai import AsyncOpenAI, RateLimitError

from telonyx_cinema_bot.services.gemini import FallbackCopywriter, _parse_campaign_texts, _parse_key_value_block, _parse_tags, _parse_title_year
from telonyx_cinema_bot.services.tmdb import MovieMetadata

logger = logging.getLogger(__name__)


class GroqCopywriter:
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile") -> None:
        self.client = AsyncOpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        self.model = model
        self.fallback = FallbackCopywriter()

    async def _generate_text(self, prompt: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return (response.choices[0].message.content or "").strip()

    def _log_generation_error(self, task: str, exc: Exception) -> None:
        if isinstance(exc, RateLimitError):
            logger.warning("Groq rate limited while generating %s with model %s", task, self.model)
            return
        logger.exception("Groq failed to generate %s with model %s", task, self.model)

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

    async def identify_movie_from_title(self, raw_title: str) -> tuple[str, str]:
        prompt = (
            "Ты — эксперт по кино. По заголовку YouTube-видео определи "
            "название фильма/сериала и год выхода.\n"
            "Верни строго в формате: НАЗВАНИЕ | ГОД\n"
            "Пример: Бойцовский клуб | 1999\n\n"
            "Если год неопределим — поставь 0.\n"
            "Если название неясно — верни оригинальный заголовок.\n\n"
            f"Заголовок: {raw_title}"
        )
        try:
            text = await self._generate_text(prompt)
            return _parse_title_year(text, raw_title)
        except Exception as exc:
            self._log_generation_error("movie identification", exc)
            return raw_title, ""

    async def generate_shorts_description(
        self,
        raw_title: str,
        movie_title: str,
        movie_year: str,
        movie_genre: str,
    ) -> str:
        prompt = (
            "Напиши виральное описание для YouTube Shorts в Telegram.\n"
            "Формат:\n"
            f"{movie_title} | краткое описание момента 🔥\n\n"
            "Потом добавь 7-10 виральных хештегов через пробел — "
            "смесь русских и английских, популярных в рекомендациях.\n"
            "Обязательно включи: #кино #shorts #рек #рекомендации "
            "и хештеги по названию фильма, жанру, году.\n\n"
            f"Оригинальный заголовок: {raw_title}\n"
            f"Фильм: {movie_title} ({movie_year}), жанр: {movie_genre}\n"
            "Только текст, без лишних слов."
        )
        try:
            text = await self._generate_text(prompt)
            return text.strip()
        except Exception as exc:
            self._log_generation_error("shorts description", exc)
            tag = movie_title.replace('.', '').replace('#', '').replace(' ', '').lower()
            return (
                f"{movie_title} | {raw_title} 🔥\n"
                f"#кино #{tag} "
                f"#shorts #рек #telonyx_cinema"
            )

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
        if not news_items:
            return []

        items_str = ""
        for item in news_items:
            items_str += f"ID: {item['id']} | TITLE: {item['title']} | DESC: {item['description']}\n"

        prompt = (
            "You are a cinema news editor for a Telegram channel about movies and TV series.\n"
            "Select ONLY news that is directly about movies or TV shows: premieres, trailers, "
            "casting, studios, film festivals, box office, directors, actors in a film context.\n"
            "REJECT politics, music (unless film soundtrack), sports, celebrity gossip without "
            "film connection, and general news.\n"
            "Ignore cheap gossip, clickbait, and duplicates.\n"
            "Return ONLY a comma-separated list of IDs you selected. If nothing is relevant, return nothing.\n"
            f"Articles:\n{items_str}"
        )
        try:
            text = await self._generate_text(prompt)
            return [int(match.group()) for match in re.finditer(r'\d+', text)]
        except Exception as exc:
            self._log_generation_error("news filter", exc)
            return [item['id'] for item in news_items[:3]]

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
            "Ты главный редактор Telegram-канала о кино. Твоя задача — отобрать новости, "
            "которые напрямую касаются кино и сериалов: премьеры, трейлеры, кастинг, "
            "крупные студии (Disney, Warner, Netflix и т.д.), кинофестивали, сборы, "
            "заметные режиссёры и актёры в контексте их работы.\n"
            "КАТЕГОРИЧЕСКИ ОТСЕКАЙ: политику, музыку (если не про саундтреки к фильмам), "
            "спорт, общественные события, светские сплетни без связи с кино.\n"
            "Если новость не про кино или сериалы — не выбирай её.\n"
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
            "Верни только основной текст без заголовка.\n"
            "Используй Telegram HTML-разметку: <b>жирный</b>, <i>курсив</i>. Можно 1-2 эмодзи по теме.\n"
            "Стиль: живой, информативный, без клише ('Привет, киноманы').\n"
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
            "Ты автор кино-канала. Напиши пост на русском о свежей новости из мира кино.\n"
            "Пиши своим голосом — как будто рассказываешь друзьям в уютном баре.\n"
            "Добавь контекст, почему это важно/интересно, своё отношение. Без клише вроде 'рад сообщить'.\n"
            "Используй Telegram HTML-разметку: <b>жирный</b>, <i>курсив</i>. Можно эмодзи.\n"
            "Не выдумывай факты, но и не копируй оригинал — перескажи своими словами.\n"
            "Верни строго в формате:\n"
            "TITLE: короткий заголовок до 70 символов\n"
            "BODY: 2-4 предложения, до 650 символов\n"
            "TAGS: 3-5 хештегов через пробел, включая #новости\n\n"
            f"Контекст: {article.get('title')} — {article.get('description')}\n"
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

    async def generate_review_post(self, movie: MovieMetadata) -> dict[str, object]:
        prompt = (
            "Ты автор кино-канала. Напиши мини-рецензию на фильм на русском языке.\n"
            "Это не пересказ сюжета, а твоё мнение: чем фильм цепляет, кому зайдёт, "
            "стоит ли смотреть. Пиши живо, с эмодзи, используй <b>жирный</b> и <i>курсив</i>.\n"
            "Верни строго в формате:\n"
            "TITLE: короткий заголовок до 70 символов\n"
            "BODY: 2-4 предложения, до 500 символов\n"
            "TAGS: 3-4 хештега через пробел\n\n"
            f"Название: {movie.display_title}\n"
            f"Оригинал: {movie.original_title or '—'}\n"
            f"Год: {movie.release_year or '—'}\n"
            f"Описание: {movie.overview or 'нет данных'}\n"
            f"Жанры: {', '.join(movie.genres[:3]) if movie.genres else '—'}\n"
            f"Рейтинг: {movie.imdb_rating or '—'}"
        )
        try:
            text = await self._generate_text(prompt)
            parsed = _parse_key_value_block(text)
            return {
                "title": parsed.get("TITLE") or movie.display_title,
                "body": parsed.get("BODY") or (movie.overview or "")[:500],
                "hashtags": _parse_tags(parsed.get("TAGS") or "#кино #рецензия #telonyxcinema"),
            }
        except Exception as exc:
            self._log_generation_error("review post", exc)
            return await self.fallback.generate_review_post(movie)

    async def generate_selection_post(self, movies: list[MovieMetadata]) -> dict[str, object]:
        movie_lines = "\n".join(
            f"- {movie.display_title}: {movie.overview or 'нет описания'}" for movie in movies[:5]
        )
        prompt = (
            "Ты автор кино-канала. Собери вечернюю подборку фильмов на русском.\n"
            "Пиши своим голосом — как будто советуешь друзьям, что посмотреть сегодня вечером.\n"
            "Объясни, почему каждый фильм стоит внимания именно сегодня.\n"
            "Используй Telegram HTML-разметку: <b>жирный</b>, <i>курсив</i>. Можно эмодзи.\n"
            "До 750 символов.\n"
            "Верни строго:\n"
            "TITLE: короткий заголовок\n"
            "BODY: вступление и 3-4 фильма с короткой причиной посмотреть каждый\n"
            "TAGS: 3-5 хештегов, включая #подборка и #вечернеекино\n\n"
            f"Фильмы на выбор:\n{movie_lines}"
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
            else "Без конкретного фильма. Придумай общий кино-вопрос."
        )
        prompt = (
            "Ты автор кино-канала. Придумай интерактив для подписчиков: вопрос, голосование или обсуждение.\n"
            "Задай его так, чтобы хотелось ответить — провокационно, но без кринжа.\n"
            "Можно отталкиваться от конкретного фильма или общей темы.\n"
            "Используй эмодзи. Без ссылок.\n"
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
