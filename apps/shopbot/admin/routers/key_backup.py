"""Admin pages for upstream key backup snapshots."""
from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from admin.deps import get_templates, protected_router
from bot.config import settings
from bot.services.key_backup_poller import backup_all_servers_now, backup_server_now
from db.queries.key_backup import (
    get_backup_history,
    get_latest_items_by_server,
    get_latest_snapshot_per_server,
    key_search_matches,
)
from db.queries.servers import get_all_servers, get_server_by_id

router = protected_router(prefix="/key-backup", tags=["key-backup"])


def _remote_vault_configured() -> bool:
    return bool(settings.key_vault_url or settings.key_vault_api_token or settings.key_vault_lookup_secret)


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


def _quota_to_dollar(value: object, server: dict) -> float:
    try:
        quota = int(value or 0)
    except (TypeError, ValueError):
        quota = 0
    try:
        multiple = float(server.get("quota_multiple") or 1.0)
    except (TypeError, ValueError):
        multiple = 1.0
    return quota / (500000 * (multiple if multiple > 0 else 1.0))


def _vault_history_rows(runs: list[dict] | None) -> list[dict]:
    return [
        {
            "fetched_at": row.get("created_at"),
            "status": row.get("status") or "error",
            "total_keys": int(row.get("item_count") or 0),
            "total_balance": None,
            "lookup_error_count": int(row.get("lookup_error_count") or 0),
            "error_message": row.get("error_message"),
        }
        for row in (runs or [])
    ]


async def _build_overview_rows(vault_summary: list[dict] | None = None) -> list[dict]:
    servers = await get_all_servers()
    latest_by_server = {
        int(snapshot["server_id"]): snapshot
        for snapshot in await get_latest_snapshot_per_server()
    }
    use_vault = vault_summary is not None
    vault_by_source = {
        str(row.get("source_id") or ""): row
        for row in (vault_summary or [])
        if row.get("source_id")
    }
    rows = []
    for server in servers:
        source_id = str(server.get("control_plane_source_id") or "").strip()
        vault = vault_by_source.get(source_id) if use_vault and source_id else None
        if use_vault:
            total_keys = int(vault.get("total_count") or 0) if vault else 0
            total_balance = _quota_to_dollar(vault.get("active_remain_quota"), server) if vault else 0.0
            snapshot = None
            if vault and vault.get("last_run_at"):
                snapshot = {
                    "fetched_at": vault.get("last_run_at"),
                    "error_message": vault.get("last_error"),
                    "total_keys": total_keys,
                    "total_balance": total_balance,
                }
            rows.append(
                {
                    "server": server,
                    "snapshot": snapshot,
                    "status": (vault.get("last_status") if vault else None) or "missing",
                    "total_keys": total_keys,
                    "total_balance": total_balance,
                    "active_count": int(vault.get("active_count") or 0) if vault else 0,
                    "removed_count": int(vault.get("removed_count") or 0) if vault else 0,
                    "unknown_count": int(vault.get("unknown_count") or 0) if vault else 0,
                    "stored_key_count": int(vault.get("stored_key_count") or 0) if vault else 0,
                    "lookup_error_count": int(vault.get("lookup_error_count") or 0) if vault else 0,
                }
            )
            continue
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
    from bot.services.key_vault_client import get_summary

    remote_vault = _remote_vault_configured()
    vault_summary = await get_summary() if remote_vault else None
    rows = await _build_overview_rows(vault_summary if remote_vault else None)
    total_keys = sum(row["total_keys"] for row in rows)
    total_balance = sum(row["total_balance"] for row in rows)
    templates = get_templates()
    return templates.TemplateResponse(
        "key_backup.html",
        {
            "request": request,
            "remote_vault": remote_vault,
            "vault_summary": vault_summary,
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

    remote_vault = _remote_vault_configured()
    vault_unavailable = False
    if remote_vault:
        from bot.services.key_vault_client import get_runs

        source_id = str(server.get("control_plane_source_id") or "").strip()
        runs = await get_runs(source_id) if source_id else None
        vault_unavailable = runs is None
        history = _vault_history_rows(runs)
    else:
        history = await get_backup_history(server_id, limit=50)
    templates = get_templates()
    return templates.TemplateResponse(
        "key_backup_detail.html",
        {
            "request": request,
            "remote_vault": remote_vault,
            "vault_unavailable": vault_unavailable,
            "server": server,
            "items": [],
            "history": history,
            "search": "",
            "snapshot": history[0] if history else None,
            "show_history": True,
            **_flash_context(request),
        },
    )


@router.get("/{server_id}/key", response_class=HTMLResponse)
async def key_backup_key_detail(request: Request, server_id: int) -> HTMLResponse:
    server = await get_server_by_id(server_id)
    if not server:
        return _redirect_with_flash("/key-backup", "error", "Server not found.")
    if not _remote_vault_configured():
        return _redirect_with_flash(f"/key-backup/{server_id}", "error", "Key details require the remote Vault.")

    source_id = str(server.get("control_plane_source_id") or "").strip()
    token_ref = _clean_text(request.query_params.get("token_ref"))
    if not source_id or not token_ref:
        return _redirect_with_flash(f"/key-backup/{server_id}", "error", "Key identity is missing.")

    from bot.services.key_vault_client import get_item_detail

    detail = await get_item_detail(source_id, token_ref)
    item = detail.get("item") if isinstance(detail, dict) else None
    if not isinstance(item, dict):
        return _redirect_with_flash(f"/key-backup/{server_id}", "error", "Key was not found in the Vault.")

    chronological = list(reversed(detail.get("history") or []))
    previous_balance: float | None = None
    for row in chronological:
        balance = _quota_to_dollar(row.get("remain_quota"), server)
        row["balance_dollar"] = balance
        row["balance_delta"] = None if previous_balance is None else balance - previous_balance
        previous_balance = balance
    history = list(reversed(chronological))
    item["balance_dollar"] = _quota_to_dollar(item.get("remain_quota"), server)

    templates = get_templates()
    return templates.TemplateResponse(
        "key_backup_key_detail.html",
        {
            "request": request,
            "server": server,
            "item": item,
            "history": history,
            "status_history": detail.get("status_history") or [],
            **_flash_context(request),
        },
    )


@router.get("/{server_id}", response_class=HTMLResponse)
async def key_backup_detail(request: Request, server_id: int) -> HTMLResponse:
    server = await get_server_by_id(server_id)
    if not server:
        return _redirect_with_flash("/key-backup", "error", "Server not found.")

    search = _clean_text(request.query_params.get("search"))
    remote_vault = _remote_vault_configured()
    vault_unavailable = False
    if remote_vault:
        from bot.services.key_vault_client import get_inventory, get_runs

        source_id = str(server.get("control_plane_source_id") or "").strip()
        inventory = await get_inventory(source_id) if source_id else None
        runs = await get_runs(source_id) if source_id else None
        vault_unavailable = inventory is None or runs is None
        all_items = inventory or []
        for item in all_items:
            item["balance_dollar"] = _quota_to_dollar(item.get("remain_quota"), server)
            item["detail_url"] = f"/key-backup/{server_id}/key?token_ref={quote_plus(str(item.get('token_ref') or ''))}"
        items = _apply_item_search(all_items, search)
        history = _vault_history_rows(runs)
        snapshot = {
            "total_keys": len(all_items),
            "total_balance": sum(
                float(item.get("balance_dollar") or 0.0)
                for item in all_items
                if item.get("source_status") == "active"
            ),
            "fetched_at": history[0].get("fetched_at") if history else None,
        }
    else:
        items = _apply_item_search(await get_latest_items_by_server(server_id), search)
        history = await get_backup_history(server_id, limit=20)
        snapshot = history[0] if history else None
    templates = get_templates()
    return templates.TemplateResponse(
        "key_backup_detail.html",
        {
            "request": request,
            "remote_vault": remote_vault,
            "vault_unavailable": vault_unavailable,
            "server": server,
            "items": items,
            "history": history,
            "search": search,
            "snapshot": snapshot,
            "show_history": False,
            **_flash_context(request),
        },
    )


@router.post("/trigger")
async def trigger_key_backup_all() -> RedirectResponse:
    if _remote_vault_configured():
        return _redirect_with_flash("/key-backup", "error", "Remote Vault backup is not available from this page yet.")
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
    if _remote_vault_configured():
        return _redirect_with_flash(f"/key-backup/{server_id}", "error", "Remote Vault backup is not available from this page yet.")
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
