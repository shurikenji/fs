"""
bot/config.py — Load .env settings vào dataclass.
Ưu tiên: DB settings > .env > default values.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env từ thư mục gốc project
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


def _env(key: str, default: str = "") -> str:
    """Read environment variable with default."""
    return os.getenv(key, default)


@dataclass(frozen=True)
class Settings:
    """Application settings — loaded once at startup."""

    # Telegram Bot
    bot_token: str = field(default_factory=lambda: _env("BOT_TOKEN"))

    # Database
    db_path: str = field(default_factory=lambda: _env("DB_PATH", "shopbot.db"))

    # Admin panel
    admin_secret_key: str = field(
        default_factory=lambda: _env("ADMIN_SECRET_KEY", secrets.token_hex(32))
    )
    admin_port: int = field(
        default_factory=lambda: int(_env("ADMIN_PORT", "8080"))
    )
    admin_login_path: str = field(
        default_factory=lambda: _env("ADMIN_LOGIN_PATH", "/login-shopbot-admin")
    )

    # MBBank defaults (DB settings override these)
    mb_api_url: str = field(
        default_factory=lambda: _env("MB_API_URL", "https://apicanhan.com/api/mbbankv3")
    )
    mb_api_key: str = field(default_factory=lambda: _env("MB_API_KEY"))
    mb_username: str = field(default_factory=lambda: _env("MB_USERNAME"))
    mb_password: str = field(default_factory=lambda: _env("MB_PASSWORD"))
    mb_account_no: str = field(default_factory=lambda: _env("MB_ACCOUNT_NO"))
    mb_account_name: str = field(default_factory=lambda: _env("MB_ACCOUNT_NAME"))
    mb_bank_id: str = field(default_factory=lambda: _env("MB_BANK_ID", "MB"))

    # Poller
    poll_interval: int = field(
        default_factory=lambda: int(_env("POLL_INTERVAL", "12"))
    )
    order_expire_minutes: int = field(
        default_factory=lambda: int(_env("ORDER_EXPIRE_MINUTES", "30"))
    )

    # Admin Telegram IDs (comma-separated)
    admin_telegram_ids: str = field(
        default_factory=lambda: _env("ADMIN_TELEGRAM_IDS")
    )
    platform_admin_url: str = field(
        default_factory=lambda: _env("PLATFORM_ADMIN_URL", "https://admin.shupremium.com")
    )
    portal_internal_token: str = field(
        default_factory=lambda: _env("PORTAL_INTERNAL_TOKEN")
    )
    portal_session_secret: str = field(
        default_factory=lambda: _env("PORTAL_SESSION_SECRET", _env("ADMIN_SECRET_KEY", secrets.token_hex(32)))
    )
    admin_launch_secret: str = field(
        default_factory=lambda: _env("ADMIN_LAUNCH_SECRET")
    )
    admin_launch_ttl_seconds: int = field(
        default_factory=lambda: int(_env("ADMIN_LAUNCH_TTL_SECONDS", "90"))
    )

    @property
    def admin_ids_list(self) -> list[int]:
        """Parse admin telegram IDs thành list int."""
        raw = self.admin_telegram_ids.strip()
        if not raw:
            return []
        return [int(tid.strip()) for tid in raw.split(",") if tid.strip().isdigit()]


# Singleton instance
settings = Settings()
