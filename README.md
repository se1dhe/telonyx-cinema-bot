# TELONYX CINEMA Bot

Telegram-бот для русскоязычного канала TELONYX CINEMA.

Публичные форматы:

- одобренная карточка фильма из TikTok
- ежедневный дайджест в 22:00 Europe/Kiev с опросом
- утренняя подборка в 10:00 Europe/Kiev по победителю опроса

Все ответы бота и публикации канала должны быть на русском.

## Setup

```bash
uv sync --extra dev
cp .env.example .env
uv run python -m telonyx_cinema_bot
```

Переменные окружения перечислены в `.env.example`.

`ADMIN_USER_IDS` можно оставить пустым для запуска без админов или указать
один/несколько Telegram user ID через запятую: `123456789,987654321`.

## Admin Commands

- `/submit <tiktok_url> | <movie title>`
- `/pending`
- `/digest_now`
- `/recommend_now`

Черновики проверяются через inline-кнопки `Опубликовать` / `Отклонить`.
Команды `/approve <draft_id>` и `/reject <draft_id>` остаются fallback-вариантом.

## Railway

Railway использует `railway.json` и запускает worker командой:

```bash
python -m telonyx_cinema_bot
```
