"""Runtime AI translation settings loader."""
from __future__ import annotations

from app.config import get_settings
from db.queries.settings import get_settings_dict


async def get_runtime_ai_settings() -> dict[str, str | bool]:
    env_settings = get_settings()
    defaults = {
        "ai_provider": env_settings.ai_provider,
        "ai_api_key": env_settings.ai_api_key,
        "ai_model": env_settings.ai_model,
        "ai_base_url": env_settings.ai_base_url,
        "ai_enabled": "true" if env_settings.ai_enabled else "false",
    }
    stored = await get_settings_dict(defaults)
    return {
        "provider": str(stored.get("ai_provider") or "openai").strip().lower(),
        "api_key": str(stored.get("ai_api_key") or "").strip(),
        "model": str(stored.get("ai_model") or env_settings.ai_model).strip(),
        "base_url": str(stored.get("ai_base_url") or "").strip(),
        "enabled": str(stored.get("ai_enabled") or "").strip().lower() == "true",
    }
