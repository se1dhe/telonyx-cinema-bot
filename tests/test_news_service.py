from types import SimpleNamespace

from telonyx_cinema_bot.services.news import _entry_image_url


def test_entry_image_url_reads_media_content() -> None:
    entry = SimpleNamespace(
        media_content=[
            {
                "url": "https://example.com/poster.jpg",
                "medium": "image",
            }
        ]
    )

    assert _entry_image_url(entry) == "https://example.com/poster.jpg"

