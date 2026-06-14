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
    timezone: str = Field(default="Europe/Kiev", alias="TIMEZONE")
    digest_time: str = Field(default="22:00", alias="DIGEST_TIME")
    recommendation_time: str = Field(default="10:00", alias="RECOMMENDATION_TIME")

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
