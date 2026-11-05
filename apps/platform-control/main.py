"""platform-control entry point."""
from __future__ import annotations

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from app.config import get_settings  # noqa: E402


def validate_runtime_settings(settings) -> None:
    for name in ("admin_secret", "admin_password", "control_plane_token", "proxy_operator_token", "pricing_admin_token", "shopbot_launch_secret"):
        value = getattr(settings, name, "")
        if not value or not value.strip() or value.strip().lower().startswith("change-me"):
            raise RuntimeError(f"{name.upper()} must be configured with a non-default value")


def main() -> None:
    settings = get_settings()
    validate_runtime_settings(settings)
    uvicorn.run(
        "app.app:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
    )


if __name__ == "__main__":
    main()
