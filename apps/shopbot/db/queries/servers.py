"""
db/queries/servers.py — CRUD operations cho bảng api_servers.
"""
from __future__ import annotations

from typing import Optional

from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_one_dict


_SERVER_SELECT = "SELECT * FROM api_servers"
_SERVER_ORDER_BY = " ORDER BY sort_order ASC, id ASC"


async def _fetch_servers(where_clause: str = "", params: tuple[object, ...] = ()) -> list[dict]:
    query = _SERVER_SELECT
    if where_clause:
        query += f" WHERE {where_clause}"
    query += _SERVER_ORDER_BY
    return await fetch_all_dicts(query, params)


async def _fetch_server(where_clause: str, params: tuple[object, ...]) -> Optional[dict]:
    return await fetch_one_dict(f"{_SERVER_SELECT} WHERE {where_clause}", params)


async def get_active_servers() -> list[dict]:
    """Lấy danh sách server đang active, sắp xếp theo sort_order."""
    return await _fetch_servers("is_active = 1")


async def get_all_servers() -> list[dict]:
    """Lấy tất cả servers (admin)."""
    return await _fetch_servers()


async def get_server_by_id(server_id: int) -> Optional[dict]:
    """Lấy server theo ID."""
    return await _fetch_server("id = ?", (server_id,))


async def create_server(
    name: str,
    base_url: str,
    user_id_header: str,
    access_token: str,
    price_per_unit: int,
    quota_per_unit: int,
    dollar_per_unit: float = 10.0,
    quota_multiple: float = 1.0,
    default_group: str = "",
    sort_order: int = 0,
    # New fields
    api_type: str = "newapi",
    supports_multi_group: int = 0,
    manual_groups: str = "",
    auth_type: str = "header",
    auth_user_header: str = "",
    auth_user_value: str = "",
    auth_token: str = "",
    auth_cookie: str = "",
    custom_headers: str = "",
    groups_endpoint: str = "",
    import_spend_accrual_enabled: int = 0,
    discount_stack_mode: str = "exclusive",
    discount_allowed_stack_types: str = "cashback",
) -> int:
    """Tạo API server mới, trả về ID."""
    cursor = await execute_commit(
        """INSERT INTO api_servers
           (name, base_url, user_id_header, access_token,
           price_per_unit, dollar_per_unit, quota_multiple, quota_per_unit,
            default_group, sort_order, api_type, supports_multi_group,
            manual_groups, auth_type, auth_user_header, auth_user_value,
            auth_token, auth_cookie, custom_headers, groups_endpoint,
            import_spend_accrual_enabled, discount_stack_mode, discount_allowed_stack_types)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            name, base_url, user_id_header, access_token,
            price_per_unit, dollar_per_unit, quota_multiple, quota_per_unit,
            default_group, sort_order, api_type, supports_multi_group,
            manual_groups, auth_type, auth_user_header, auth_user_value,
            auth_token, auth_cookie, custom_headers, groups_endpoint,
            import_spend_accrual_enabled, discount_stack_mode, discount_allowed_stack_types,
        ),
    )
    return cursor.lastrowid  # type: ignore[return-value]


async def update_server(server_id: int, **kwargs) -> None:
    """Cập nhật server — chỉ update các field được truyền vào."""
    if not kwargs:
        return

    allowed_fields = {
        "name", "base_url", "user_id_header", "access_token",
        "price_per_unit", "dollar_per_unit", "quota_multiple", "quota_per_unit",
        "default_group", "is_active", "sort_order",
        # New fields
        "api_type", "supports_multi_group", "groups_cache", "groups_updated_at",
        "manual_groups", "auth_type", "auth_user_header", "auth_user_value",
        "auth_token", "auth_cookie", "custom_headers", "groups_endpoint",
        "import_spend_accrual_enabled", "discount_stack_mode", "discount_allowed_stack_types",
    }

    fields = []
    values = []
    for key, val in kwargs.items():
        if key in allowed_fields:
            fields.append(f"{key} = ?")
            values.append(val)

    if not fields:
        return

    fields.append("updated_at = datetime('now', '+7 hours')")
    values.append(server_id)

    query = f"UPDATE api_servers SET {', '.join(fields)} WHERE id = ?"
    await execute_commit(query, tuple(values))


async def delete_server(server_id: int) -> None:
    """Xóa server."""
    await execute_commit("DELETE FROM api_servers WHERE id = ?", (server_id,))
