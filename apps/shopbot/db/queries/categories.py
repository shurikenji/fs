"""
db/queries/categories.py — CRUD operations cho bảng categories.
"""
from __future__ import annotations

from typing import Optional

from db.queries._helpers import execute_commit, fetch_all_dicts, fetch_one_dict, fetch_scalar


async def get_active_categories() -> list[dict]:
    """Lấy danh mục đang active, sắp xếp theo sort_order."""
    return await fetch_all_dicts(
        """SELECT * FROM categories
           WHERE is_active = 1
           ORDER BY sort_order ASC, id ASC"""
    )


async def get_all_categories() -> list[dict]:
    """Lấy tất cả danh mục (admin)."""
    return await fetch_all_dicts("SELECT * FROM categories ORDER BY sort_order ASC, id ASC")


async def get_category_by_id(cat_id: int) -> Optional[dict]:
    """Lấy danh mục theo ID."""
    return await fetch_one_dict("SELECT * FROM categories WHERE id = ?", (cat_id,))


async def create_category(
    name: str,
    icon: str = "📦",
    description: Optional[str] = None,
    cat_type: str = "general",
    sort_order: int = 0,
) -> int:
    """Tạo danh mục mới, trả về ID."""
    cursor = await execute_commit(
        """INSERT INTO categories (name, icon, description, cat_type, sort_order)
           VALUES (?, ?, ?, ?, ?)""",
        (name, icon, description, cat_type, sort_order),
    )
    return cursor.lastrowid  # type: ignore[return-value]


async def update_category(
    cat_id: int,
    name: Optional[str] = None,
    icon: Optional[str] = None,
    description: Optional[str] = None,
    cat_type: Optional[str] = None,
    sort_order: Optional[int] = None,
    is_active: Optional[int] = None,
) -> None:
    """Cập nhật danh mục."""
    fields = []
    values = []

    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if icon is not None:
        fields.append("icon = ?")
        values.append(icon)
    if description is not None:
        fields.append("description = ?")
        values.append(description)
    if cat_type is not None:
        fields.append("cat_type = ?")
        values.append(cat_type)
    if sort_order is not None:
        fields.append("sort_order = ?")
        values.append(sort_order)
    if is_active is not None:
        fields.append("is_active = ?")
        values.append(is_active)

    if not fields:
        return

    fields.append("updated_at = datetime('now', '+7 hours')")
    values.append(cat_id)

    query = f"UPDATE categories SET {', '.join(fields)} WHERE id = ?"
    await execute_commit(query, tuple(values))


async def delete_category(cat_id: int) -> None:
    """Xóa danh mục (hard delete)."""
    await execute_commit("DELETE FROM categories WHERE id = ?", (cat_id,))


async def count_products_by_category(cat_id: int) -> int:
    """Đếm số sản phẩm đang thuộc danh mục."""
    return int(
        await fetch_scalar(
            "SELECT COUNT(*) FROM products WHERE category_id = ?",
            (cat_id,),
        )
        or 0
    )
