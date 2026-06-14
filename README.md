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
- `/digest_now`
- `/recommend_now`

Drafts are reviewed through inline `Publish` / `Reject` buttons. The legacy
`/approve <draft_id>` and `/reject <draft_id>` commands remain available as a
fallback for operators.

## Railway

Railway uses `railway.json` and starts the worker with:

```bash
python -m telonyx_cinema_bot
```
