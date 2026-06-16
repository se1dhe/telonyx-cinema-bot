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

    async def publish_media_group(
        self,
        media_items: list[tuple[str, str | None]],
        common_caption: str | None = None,
    ) -> int:
        from aiogram.types import InputMediaPhoto

        input_media = []
        for i, (item_text, image_url) in enumerate(media_items):
            if not image_url:
                continue
            caption = common_caption if i == 0 else item_text
            input_media.append(
                InputMediaPhoto(media=image_url, caption=caption, parse_mode=ParseMode.HTML)
            )

        if not input_media:
            message = await self.bot.send_message(
                self.channel_id, common_caption or "", parse_mode=ParseMode.HTML
            )
            return message.message_id

        messages = await self.bot.send_media_group(
            self.channel_id, media=input_media
        )
        return messages[0].message_id

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

    async def publish_cards(self, cards: list[tuple[str, str | None]]) -> list[int]:
        message_ids = []
        for text, poster_url in cards:
            message_ids.append(await self.publish_card(text, poster_url))
        return message_ids

    async def publish_news(self, text: str, image_url: str | None = None) -> int:
        if not image_url:
            raise ValueError("News posts require at least one image")
        message = await self.bot.send_photo(
            self.channel_id,
            image_url,
            caption=text,
            parse_mode=ParseMode.HTML,
        )
        return message.message_id

    async def publish_video(self, video_file_id: str, caption: str | None = None) -> int:
        # Check if video_file_id is an actual file id or a url
        if video_file_id.startswith("http"):
            message = await self.bot.send_message(
                self.channel_id,
                f"{caption or ''}\n\n<a href='{video_file_id}'>Смотреть видео</a>",
                parse_mode=ParseMode.HTML,
            )
        else:
            message = await self.bot.send_video(
                self.channel_id,
                video_file_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        return message.message_id
