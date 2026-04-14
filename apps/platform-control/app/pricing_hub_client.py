"""Internal client for pricing-hub admin bridge."""
from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


def _base_url() -> str:
    return get_settings().pricing_hub_url.rstrip("/")


def _headers() -> dict[str, str]:
    return {"X-Pricing-Admin-Token": get_settings().pricing_admin_token}


async def pricing_import_control_plane() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_base_url()}/api/internal/admin/pricing/import-control-plane",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


async def pricing_sync_source(source_id: str, *, trigger: str = "manual") -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{_base_url()}/api/internal/admin/pricing/sources/{source_id}/sync",
            headers=_headers(),
            params={"trigger": trigger},
        )
        response.raise_for_status()
        return response.json()


async def pricing_get_groups(source_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_base_url()}/api/internal/admin/pricing/sources/{source_id}/groups",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


async def pricing_refresh_groups(source_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{_base_url()}/api/internal/admin/pricing/sources/{source_id}/groups/refresh",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


async def pricing_save_groups(source_id: str, visible_groups: list[str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_base_url()}/api/internal/admin/pricing/sources/{source_id}/groups/save",
            headers=_headers(),
            json={"visible_groups": visible_groups},
        )
        response.raise_for_status()
        return response.json()


async def pricing_get_models(source_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_base_url()}/api/internal/admin/pricing/sources/{source_id}/models",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


async def pricing_save_models(source_id: str, visible_models: list[str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_base_url()}/api/internal/admin/pricing/sources/{source_id}/models/save",
            headers=_headers(),
            json={"visible_models": visible_models},
        )
        response.raise_for_status()
        return response.json()


async def pricing_get_settings() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_base_url()}/api/internal/admin/pricing/settings",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


async def pricing_get_sync_runs(
    *,
    source_id: str | None = None,
    status: str | None = None,
    trigger: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if source_id:
        params["source_id"] = source_id
    if status:
        params["status"] = status
    if trigger:
        params["trigger"] = trigger
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_base_url()}/api/internal/admin/pricing/sync-runs",
            headers=_headers(),
            params=params,
        )
        response.raise_for_status()
        return response.json()


async def pricing_get_latest_sync_runs() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_base_url()}/api/internal/admin/pricing/sync-runs/latest",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


async def pricing_save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_base_url()}/api/internal/admin/pricing/settings/save",
            headers=_headers(),
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def pricing_test_ai(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_base_url()}/api/internal/admin/pricing/settings/ai/test",
            headers=_headers(),
            json=payload,
        )
        response.raise_for_status()
        return response.json()
