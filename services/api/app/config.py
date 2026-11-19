"""Application settings, read from environment variables (see .env.example).

Use get_settings() wherever a setting is needed. It is loaded on first use, not at
import time, so tests can set environment variables before anything reads them.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Reads the process environment; a local .env file is also picked up when present.
    # Variable names are case-insensitive: DATABASE_URL fills database_url.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Required: the API refuses to start without these ---
    database_url: str
    # min_length matters: an empty key would let requests with no X-API-Key header through.
    saathi_api_key: str = Field(min_length=16)
    gemini_api_key: str

    # --- Gemini ---
    gemini_chat_model: str = "gemini-flash-latest"
    gemini_embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768

    # --- Channels (optional until the phase that needs them) ---
    telegram_bot_token: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"

    # --- Tuning ---
    db_pool_max: int = Field(default=3, ge=1, le=10)
    max_upload_mb: int = Field(default=20, ge=1, le=100)
    # Fallback timezone. Per-user timezones come from the users table.
    tz: str = "Asia/Kolkata"


@lru_cache
def get_settings() -> Settings:
    return Settings()
