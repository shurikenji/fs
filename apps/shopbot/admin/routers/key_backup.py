"""Admin pages for upstream key backup snapshots."""
from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from admin.deps import get_templates, protected_router
from bot.services.key_backup_poller import backup_all_servers_now, backup_server_now
from db.queries.key_backup import (
    get_backup_history,
    get_latest_items_by_server,
    get_latest_snapshot_per_server,
    key_search_matches,
)
from db.queries.servers import get_all_servers, get_server_by_id

router = protected_router(prefix="/key-backup", tags=["key-backup"])


def _clean_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _flash_context(request: Request) -> dict[str, str]:
    trigger = _clean_text(request.query_params.get("trigger"))
    message = _clean_text(request.query_params.get("message"))
    if trigger == "success":
        return {
            "flash_message": message or "Key backup completed.",
            "flash_type": "success",
        }
    if trigger == "warning":
        return {
            "flash_message": message or "Key backup completed with warnings.",
            "flash_type": "warning",
        }
    if trigger == "error":
        return {
            "flash_message": message or "Key backup failed.",
            "flash_type": "danger",
        }
    return {}


def _redirect_with_flash(path: str, trigger: str, message: str) -> RedirectResponse:
    return RedirectResponse(
        f"{path}?trigger={trigger}&message={quote_plus(message)}",
        status_code=303,
    )


def _apply_item_search(items: list[dict], search: str) -> list[dict]:
    keyword = search.strip()
    if not keyword:
        return items

    def _matches(item: dict) -> bool:
        fields = (
            item.get("token_name"),
            item.get("key_masked"),
            item.get("key_value"),
            item.get("group_name"),
            item.get("token_id"),
        )
        return key_search_matches(keyword, *fields)

    return [item for item in items if _matches(item)]


async def _build_overview_rows() -> list[dict]:
    servers = await get_all_servers()
    latest_by_server = {
        int(snapshot["server_id"]): snapshot
        for snapshot in await get_latest_snapshot_per_server()
    }
    rows = []
    for server in servers:
        latest = latest_by_server.get(int(server["id"]))
        rows.append(
            {
                "server": server,
                "snapshot": latest,
                "status": latest.get("status") if latest else "missing",
                "total_keys": int(latest.get("total_keys") or 0) if latest else 0,
                "total_balance": float(latest.get("total_balance") or 0.0) if latest else 0.0,
            }
        )
    return rows


@router.get("", response_class=HTMLResponse)
async def key_backup_dashboard(request: Request) -> HTMLResponse:
    rows = await _build_overview_rows()
    total_keys = sum(row["total_keys"] for row in rows)
    total_balance = sum(row["total_balance"] for row in rows)
    templates = get_templates()
    return templates.TemplateResponse(
        "key_backup.html",
        {
            "request": request,
            "rows": rows,
            "summary": {
                "servers": len(rows),
                "snapshots": sum(1 for row in rows if row["snapshot"]),
                "total_keys": total_keys,
                "total_balance": total_balance,
            },
            **_flash_context(request),
        },
    )


@router.get("/history/{server_id}", response_class=HTMLResponse)
async def key_backup_history(request: Request, server_id: int) -> HTMLResponse:
    server = await get_server_by_id(server_id)
    if not server:
        return _redirect_with_flash("/key-backup", "error", "Server not found.")

    history = await get_backup_history(server_id, limit=50)
    templates = get_templates()
    return templates.TemplateResponse(
        "key_backup_detail.html",
        {
            "request": request,
            "server": server,
            "items": [],
            "history": history,
            "search": "",
            "snapshot": history[0] if history else None,
            "show_history": True,
            **_flash_context(request),
        },
    )


@router.get("/{server_id}", response_class=HTMLResponse)
async def key_backup_detail(request: Request, server_id: int) -> HTMLResponse:
    server = await get_server_by_id(server_id)
    if not server:
        return _redirect_with_flash("/key-backup", "error", "Server not found.")

    search = _clean_text(request.query_params.get("search"))
    items = _apply_item_search(await get_latest_items_by_server(server_id), search)
    history = await get_backup_history(server_id, limit=20)
    templates = get_templates()
    return templates.TemplateResponse(
        "key_backup_detail.html",
        {
            "request": request,
            "server": server,
            "items": items,
            "history": history,
            "search": search,
            "snapshot": history[0] if history else None,
            "show_history": False,
            **_flash_context(request),
        },
    )


@router.post("/trigger")
async def trigger_key_backup_all() -> RedirectResponse:
    results = await backup_all_servers_now()
    error_count = sum(1 for result in results if result.get("status") != "success")
    total_keys = sum(int(result.get("total_keys") or 0) for result in results)
    trigger = "warning" if error_count else "success"
    message = f"Backed up {total_keys} keys across {len(results)} servers."
    if error_count:
        message += f" {error_count} server(s) returned errors."
    return _redirect_with_flash("/key-backup", trigger, message)


@router.post("/trigger/{server_id}")
async def trigger_key_backup_server(server_id: int) -> RedirectResponse:
    result = await backup_server_now(server_id)
    if result is None:
        return _redirect_with_flash("/key-backup", "error", "Server not found.")

    path = f"/key-backup/{server_id}"
    if result.get("status") != "success":
        return _redirect_with_flash(
            path,
            "error",
            f"Backup failed: {result.get('error_message') or 'Unknown error'}",
        )

    return _redirect_with_flash(
        path,
        "success",
        f"Backed up {int(result.get('total_keys') or 0)} keys from this server.",
    )
