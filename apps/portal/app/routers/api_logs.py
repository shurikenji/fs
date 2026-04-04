"""JSON API: /api/logs - proxy log queries to upstream servers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.adapters import get_adapter
from app.cache import fetch_pricing
from app.log_pricing import enrich_logs_payload
from app.rate_limit import enforce_rate_limit
from app.translation_service import build_public_pricing
from app.visibility import excluded_model_names, filter_logs_payload, hidden_group_names
from db.queries.servers import get_public_server

router = APIRouter(prefix="/api", tags=["api"])


class LogRequest(BaseModel):
    server_id: str
    api_key: str | None = None
    userId: str | None = None
    accessToken: str | None = None
    page: int = 1
    pageSize: int = 50
    token_name: str | None = None
    model_name: str | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    group: str | None = None


@router.post("/logs")
async def api_logs(body: LogRequest, request: Request):
    await enforce_rate_limit(
        request,
        bucket="public-logs",
        limit=10,
        window_seconds=60,
        detail="Too many log searches. Please wait a moment and try again.",
    )
    server = await get_public_server(body.server_id, "logs")
    if not server:
        return JSONResponse({"error": "Server not found"}, status_code=404)

    adapter = get_adapter(server)
    params = body.model_dump(exclude={"server_id", "api_key", "token_name", "accessToken", "userId"}, exclude_none=True)
    hidden_groups = hidden_group_names(server)
    excluded_models = excluded_model_names(server)

    resolved_by_key = False
    resolved_token = None

    if body.start_timestamp is None:
        params["start_timestamp"] = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    if body.end_timestamp is None:
        params["end_timestamp"] = int(datetime.now(timezone.utc).timestamp())

    requested_model_name = str(body.model_name or "").strip()
    if requested_model_name and requested_model_name in excluded_models:
        return {
            "items": [],
            "total": 0,
            "available_groups": [],
            "resolved_by_key": resolved_by_key,
            "resolved_token": resolved_token,
        }

    requested_group_name = str(body.group or "").strip()
    if requested_group_name and requested_group_name in hidden_groups:
        return {
            "items": [],
            "total": 0,
            "available_groups": [],
            "resolved_by_key": resolved_by_key,
            "resolved_token": resolved_token,
        }

    if not body.api_key:
        return JSONResponse({"error": "API key is required to search logs."}, status_code=400)
    if not server.get("auth_token"):
        return JSONResponse({"error": "This source does not support public log search."}, status_code=400)

    try:
        token = await adapter.search_token(server, body.api_key)
    except Exception:
        return JSONResponse({"error": "Could not resolve the provided API key."}, status_code=502)
    if not token or not token.get("name"):
        return JSONResponse({"error": "Could not resolve token from API key."}, status_code=404)

    params["token_name"] = token["name"]
    params["accessToken"] = server["auth_token"]
    if server.get("auth_user_value"):
        params["userId"] = server["auth_user_value"]
    resolved_by_key = True
    resolved_token = token["name"]

    try:
        data = await adapter.fetch_logs(server, params)
        pricing = await fetch_pricing(server["id"], allow_upstream=False)
        public_pricing = await build_public_pricing(pricing, server) if pricing else None
        enriched = enrich_logs_payload(data, public_pricing, server)
        if isinstance(enriched, list):
            enriched = {
                "items": enriched,
                "available_groups": [],
            }
        enriched = filter_logs_payload(
            enriched,
            hidden_groups=hidden_groups,
            excluded_models=excluded_models,
        )
        enriched["resolved_by_key"] = resolved_by_key
        enriched["resolved_token"] = resolved_token
        return enriched
    except Exception:
        return JSONResponse({"error": "Log fetch failed. Please try again later."}, status_code=502)
