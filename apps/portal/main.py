"""pricing-hub entry point."""
from __future__ import annotations

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from app.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.app:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
    )


if __name__ == "__main__":
    main()
