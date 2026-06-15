from aiogram.exceptions import TelegramBadRequest

from telonyx_cinema_bot.bot.handlers import _replace_callback_message


class FakeMessage:
    def __init__(self, *, caption: str | None = None) -> None:
        self.caption = caption
        self.calls: list[tuple[str, str | None]] = []

    async def edit_text(self, text, **kwargs) -> None:
        self.calls.append(("edit_text", text))
        raise TelegramBadRequest(method=None, message="there is no text in the message to edit")

    async def edit_caption(self, caption, **kwargs) -> None:
        self.calls.append(("edit_caption", caption))

    async def edit_reply_markup(self, **kwargs) -> None:
        self.calls.append(("edit_reply_markup", None))

    async def answer(self, text, **kwargs) -> None:
        self.calls.append(("answer", text))


async def test_replace_callback_message_edits_caption_when_original_message_is_photo() -> None:
    message = FakeMessage(caption="old caption")

    await _replace_callback_message(message, "✅ Новость добавлена в очередь.")

    assert message.calls == [
        ("edit_text", "✅ Новость добавлена в очередь."),
        ("edit_caption", "✅ Новость добавлена в очередь."),
    ]


async def test_replace_callback_message_sends_new_message_when_editing_is_not_possible() -> None:
    message = FakeMessage()

    await _replace_callback_message(message, "Выберите действие:")

    assert message.calls == [
        ("edit_text", "Выберите действие:"),
        ("edit_reply_markup", None),
        ("answer", "Выберите действие:"),
    ]
