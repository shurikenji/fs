"""Application settings loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_title: str = "Shupremium Portal"
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    app_debug: bool = False
    seed_demo_server: bool = True

    admin_secret: str = "change-me-to-a-strong-secret"

    ai_provider: str = "openai"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_base_url: str = ""
    ai_enabled: bool = False

    db_path: str = "data/hub.db"
    control_plane_url: str = ""
    control_plane_token: str = ""
    control_plane_sync_enabled: bool = False
    pricing_admin_token: str = "change-me"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
