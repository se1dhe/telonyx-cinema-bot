from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ParseMode


class AiogramPublisher:
    def __init__(self, bot: Bot, channel_id: str) -> None:
        self.bot = bot
        self.channel_id = channel_id

    async def publish_card(self, text: str, poster_url: str | None = None) -> int:
        if poster_url:
            message = await self.bot.send_photo(
                self.channel_id,
                poster_url,
                caption=text,
                parse_mode=ParseMode.HTML,
            )
        else:
            message = await self.bot.send_message(
                self.channel_id,
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
            )
        return message.message_id

    async def publish_poll(self, text: str, options: list[str]) -> tuple[int, str | None]:
        await self.bot.send_message(self.channel_id, text, parse_mode=ParseMode.HTML)
        poll_message = await self.bot.send_poll(
            self.channel_id,
            question="Какой фильм станет выбором дня?",
            options=options,
            is_anonymous=True,
        )
        poll_id = poll_message.poll.id if poll_message.poll else None
        return poll_message.message_id, poll_id

    async def publish_text(self, text: str) -> int:
        message = await self.bot.send_message(self.channel_id, text, parse_mode=ParseMode.HTML)
        return message.message_id


