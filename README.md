# TELONYX CINEMA Bot

Telegram MVP with three public formats:

- approved TikTok film card
- 22:00 Europe/Kiev daily digest with a poll
- 10:00 Europe/Kiev recommendation post based on the poll winner

## Setup

```bash
uv sync --extra dev
cp .env.example .env
uv run python -m telonyx_cinema_bot
```

Required environment variables are listed in `.env.example`.

## Admin Commands

- `/submit <tiktok_url> | <movie title>`
- `/pending`
- `/approve <draft_id>`
- `/reject <draft_id>`
- `/digest_now`
- `/recommend_now`

