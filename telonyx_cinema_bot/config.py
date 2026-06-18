from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    telegram_channel_id: str = Field(alias="TELEGRAM_CHANNEL_ID")
    admin_user_ids: list[int] = Field(default_factory=list, alias="ADMIN_USER_IDS")
    database_url: str = Field(alias="DATABASE_URL")
    tmdb_api_key: str = Field(alias="TMDB_API_KEY")
    gemini_api_key: str = Field(alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    timezone: str = Field(default="Europe/Kiev", alias="TIMEZONE")
    auto_publish_enabled: bool = Field(default=True, alias="AUTO_PUBLISH_ENABLED")
    news_min_interval_minutes: int = Field(default=35, alias="NEWS_MIN_INTERVAL_MINUTES")
    daily_news_limit: int = Field(default=8, alias="DAILY_NEWS_LIMIT")
    channel_link: str | None = Field(default=None, alias="CHANNEL_LINK")
    fallback_min_interval_hours: int = Field(default=2, alias="FALLBACK_MIN_INTERVAL_HOURS")
    editorial_tone: str = Field(default="cinema_magazine", alias="EDITORIAL_TONE")
    yt_dlp_bin: str = Field(default="yt-dlp", alias="YT_DLP_BIN")
    ffmpeg_bin: str = Field(default="ffmpeg", alias="FFMPEG_BIN")
    ffprobe_bin: str = Field(default="ffprobe", alias="FFPROBE_BIN")
    storage_dir: str = Field(default="/data/storage", alias="STORAGE_DIR")
    shorts_interval_minutes: int = Field(default=60, alias="SHORTS_INTERVAL_MINUTES")
    tiktok_account_name: str | None = Field(default=None, alias="TIKTOK_ACCOUNT_NAME")
    yt_dlp_cookies_base64: str | None = Field(default=None, alias="YT_DLP_COOKIES_BASE64")
    yt_dlp_cookies_file: str | None = Field(default=None, alias="YT_DLP_COOKIES_FILE")
    omdb_api_key: str | None = Field(default=None, alias="OMDB_API_KEY")
    tiktok_draft_only: bool = Field(default=False, alias="TIKTOK_DRAFT_ONLY")
    public_domain: str | None = Field(default=None, alias="PUBLIC_DOMAIN")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @property
    def resolved_public_domain(self) -> str | None:
        """Return public domain for file serving (Railway auto-detects RAILWAY_PUBLIC_DOMAIN)."""
        if self.public_domain:
            return self.public_domain.rstrip("/")
        import os
        railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        if railway_domain:
            return f"https://{railway_domain}"
        return None

    @field_validator("database_url", mode="before")
    @classmethod
    def parse_database_url(cls, value: object) -> str:
        if isinstance(value, str):
            if value.startswith("postgres://"):
                value = value.replace("postgres://", "postgresql://", 1)
            if value.startswith("postgresql://"):
                value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, int):
            return [value]
        if isinstance(value, list):
            return [int(item) for item in value]
        if isinstance(value, str):
            normalized = value.strip().removeprefix("[").removesuffix("]")
            return [int(item.strip().strip("\"'")) for item in normalized.split(",") if item.strip()]
        raise ValueError("ADMIN_USER_IDS must be empty, a number, a comma-separated string, or a list")

    @property
    def zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
