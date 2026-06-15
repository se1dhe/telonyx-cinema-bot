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
    timezone: str = Field(default="Europe/Kiev", alias="TIMEZONE")
    auto_publish_enabled: bool = Field(default=True, alias="AUTO_PUBLISH_ENABLED")
    news_min_interval_minutes: int = Field(default=35, alias="NEWS_MIN_INTERVAL_MINUTES")
    daily_news_limit: int = Field(default=6, alias="DAILY_NEWS_LIMIT")
    fallback_min_interval_hours: int = Field(default=4, alias="FALLBACK_MIN_INTERVAL_HOURS")
    editorial_tone: str = Field(default="cinema_magazine", alias="EDITORIAL_TONE")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

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
