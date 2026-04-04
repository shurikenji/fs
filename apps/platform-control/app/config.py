"""Application settings for platform-control."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_title: str = "Platform Control"
    app_host: str = "0.0.0.0"
    app_port: int = 8090
    app_debug: bool = False

    db_path: str = "data/platform_control.db"

    admin_secret: str = "change-me"
    admin_password: str = "change-me"
    control_plane_token: str = "change-me"

    proxy_operator_url: str = "http://127.0.0.1:8091"
    proxy_operator_token: str = "change-me"
    pricing_hub_url: str = "http://127.0.0.1:8080"
    pricing_admin_token: str = "change-me"
    public_base_url: str = "https://admin.shupremium.com"
    shopbot_admin_url: str = "http://127.0.0.1:8080"
    shopbot_launch_secret: str = "change-me"
    shopbot_launch_ttl_seconds: int = 90

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
