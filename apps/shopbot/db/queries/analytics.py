"""
Analytics queries for admin dashboard and reporting.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from bot.utils.time_utils import GMT_PLUS_7, get_now_vn, to_db_time_string
from db.database import get_db
from db.queries._helpers import fetch_all_dicts, fetch_scalar


@dataclass(frozen=True)
class AnalyticsRange:
    key: str
    label: str
    start: datetime
    end: datetime
    bucket: str


def _start_of_day(value: datetime) -> datetime:
    return value.astimezone(GMT_PLUS_7).replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month(value: datetime) -> datetime:
    return _start_of_day(value).replace(day=1)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = (value.month - 1) + months
    year = value.year + month_index // 12
    month = (month_index % 12) + 1
    return value.replace(year=year, month=month, day=1)


def _coerce_custom_date(raw_value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    text = str(raw_value or "").strip()
    if not text:
        return None

    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None

    value = parsed.replace(tzinfo=GMT_PLUS_7)
    if end_of_day:
        return value + timedelta(days=1)
    return value


def _resolve_range(
    range_key: str,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    bucket: Optional[str] = None,
) -> AnalyticsRange:
    now = get_now_vn()
    today_start = _start_of_day(now)

    normalized_key = (range_key or "this_month").strip().lower()
    if normalized_key == "today":
        start = today_start
        end = start + timedelta(days=1)
        label = "Hôm nay"
    elif normalized_key == "yesterday":
        end = today_start
        start = end - timedelta(days=1)
        label = "Hôm qua"
    elif normalized_key == "last_7d":
        start = today_start - timedelta(days=6)
        end = today_start + timedelta(days=1)
        label = "7 ngày gần đây"
    elif normalized_key == "last_30d":
        start = today_start - timedelta(days=29)
        end = today_start + timedelta(days=1)
        label = "30 ngày gần đây"
    elif normalized_key == "last_month":
        end = _start_of_month(now)
        start = _add_months(end, -1)
        label = "Tháng trước"
    elif normalized_key == "custom":
        start = _coerce_custom_date(date_from) or today_start
        end = _coerce_custom_date(date_to, end_of_day=True) or (start + timedelta(days=1))
        if end <= start:
            end = start + timedelta(days=1)
        label = "Tùy chọn"
    else:
        normalized_key = "this_month"
        start = _start_of_month(now)
        end = _add_months(start, 1)
        label = "Tháng này"

    total_days = max(1, (end - start).days)
    resolved_bucket = bucket if bucket in {"day", "month"} else ("day" if total_days <= 31 else "month")
    return AnalyticsRange(
        key=normalized_key,
        label=label,
        start=start,
        end=end,
        bucket=resolved_bucket,
    )


async def _status_counts_all_time() -> dict[str, int]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT status, COUNT(*) AS cnt
           FROM orders
           GROUP BY status"""
    )
    return {row[0]: row[1] for row in await cursor.fetchall()}


async def get_dashboard_overview() -> dict[str, object]:
    today_range = _resolve_range("today")
    month_range = _resolve_range("this_month")

    today_orders = int(
        await fetch_scalar(
            """SELECT COUNT(*)
               FROM orders
               WHERE created_at >= ? AND created_at < ?""",
            (to_db_time_string(today_range.start), to_db_time_string(today_range.end)),
        )
        or 0
    )
    month_orders = int(
        await fetch_scalar(
            """SELECT COUNT(*)
               FROM orders
               WHERE created_at >= ? AND created_at < ?""",
            (to_db_time_string(month_range.start), to_db_time_string(month_range.end)),
        )
        or 0
    )
    today_revenue = int(
        await fetch_scalar(
            """SELECT COALESCE(SUM(amount), 0)
               FROM orders
               WHERE status = 'completed'
                 AND completed_at >= ?
                 AND completed_at < ?""",
            (to_db_time_string(today_range.start), to_db_time_string(today_range.end)),
        )
        or 0
    )
    month_revenue = int(
        await fetch_scalar(
            """SELECT COALESCE(SUM(amount), 0)
               FROM orders
               WHERE status = 'completed'
                 AND completed_at >= ?
                 AND completed_at < ?""",
            (to_db_time_string(month_range.start), to_db_time_string(month_range.end)),
        )
        or 0
    )

    return {
        "today_orders": today_orders,
        "month_orders": month_orders,
        "today_revenue": today_revenue,
        "month_revenue": month_revenue,
        "status_counts": await _status_counts_all_time(),
    }


async def get_analytics_summary(
    range_key: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict[str, object]:
    resolved = _resolve_range(range_key, date_from=date_from, date_to=date_to)
    start = to_db_time_string(resolved.start)
    end = to_db_time_string(resolved.end)

    created_orders = int(
        await fetch_scalar(
            """SELECT COUNT(*)
               FROM orders
               WHERE created_at >= ? AND created_at < ?""",
            (start, end),
        )
        or 0
    )
    completed_orders = int(
        await fetch_scalar(
            """SELECT COUNT(*)
               FROM orders
               WHERE status = 'completed'
                 AND completed_at >= ?
                 AND completed_at < ?""",
            (start, end),
        )
        or 0
    )
    gross_revenue = int(
        await fetch_scalar(
            """SELECT COALESCE(SUM(amount), 0)
               FROM orders
               WHERE status = 'completed'
                 AND completed_at >= ?
                 AND completed_at < ?""",
            (start, end),
        )
        or 0
    )
    refunded_amount = int(
        await fetch_scalar(
            """SELECT COALESCE(SUM(amount), 0)
               FROM orders
               WHERE is_refunded = 1
                 AND refunded_at >= ?
                 AND refunded_at < ?""",
            (start, end),
        )
        or 0
    )
    refunded_orders = int(
        await fetch_scalar(
            """SELECT COUNT(*)
               FROM orders
               WHERE is_refunded = 1
                 AND refunded_at >= ?
                 AND refunded_at < ?""",
            (start, end),
        )
        or 0
    )

    completion_rate = round((completed_orders / created_orders) * 100, 1) if created_orders else 0.0
    return {
        "range": {
            "key": resolved.key,
            "label": resolved.label,
            "start": to_db_time_string(resolved.start),
            "end_exclusive": to_db_time_string(resolved.end),
            "date_from": resolved.start.strftime("%Y-%m-%d"),
            "date_to": (resolved.end - timedelta(days=1)).strftime("%Y-%m-%d"),
            "bucket": resolved.bucket,
        },
        "created_orders": created_orders,
        "completed_orders": completed_orders,
        "gross_revenue": gross_revenue,
        "refunded_amount": refunded_amount,
        "refunded_orders": refunded_orders,
        "net_revenue": gross_revenue - refunded_amount,
        "completion_rate": completion_rate,
    }


async def get_analytics_series(
    range_key: str,
    bucket: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict[str, object]]:
    resolved = _resolve_range(range_key, date_from=date_from, date_to=date_to, bucket=bucket)
    start = resolved.start
    end = resolved.end

    if resolved.bucket == "month":
        step = "month"
        label_format = "%m/%Y"
        created_sql = "substr(created_at, 1, 7)"
        completed_sql = "substr(completed_at, 1, 7)"
        refunded_sql = "substr(refunded_at, 1, 7)"
    else:
        step = "day"
        label_format = "%d/%m"
        created_sql = "date(created_at)"
        completed_sql = "date(completed_at)"
        refunded_sql = "date(refunded_at)"

    if step == "month":
        points: list[dict[str, object]] = []
        cursor = _start_of_month(start)
        while cursor < end:
            points.append(
                {
                    "bucket": cursor.strftime("%Y-%m"),
                    "label": cursor.strftime(label_format),
                    "created_orders": 0,
                    "completed_orders": 0,
                    "gross_revenue": 0,
                    "refunded_amount": 0,
                }
            )
            cursor = _add_months(cursor, 1)
    else:
        points = []
        cursor = _start_of_day(start)
        while cursor < end:
            points.append(
                {
                    "bucket": cursor.strftime("%Y-%m-%d"),
                    "label": cursor.strftime(label_format),
                    "created_orders": 0,
                    "completed_orders": 0,
                    "gross_revenue": 0,
                    "refunded_amount": 0,
                }
            )
            cursor += timedelta(days=1)

    points_by_bucket = {point["bucket"]: point for point in points}
    start_text = to_db_time_string(start)
    end_text = to_db_time_string(end)

    created_rows = await fetch_all_dicts(
        f"""SELECT {created_sql} AS bucket, COUNT(*) AS count
            FROM orders
            WHERE created_at >= ? AND created_at < ?
            GROUP BY bucket
            ORDER BY bucket ASC""",
        (start_text, end_text),
    )
    for row in created_rows:
        bucket_key = row.get("bucket")
        if bucket_key in points_by_bucket:
            points_by_bucket[bucket_key]["created_orders"] = int(row.get("count") or 0)

    completed_rows = await fetch_all_dicts(
        f"""SELECT {completed_sql} AS bucket,
                   COUNT(*) AS completed_orders,
                   COALESCE(SUM(amount), 0) AS gross_revenue
            FROM orders
            WHERE status = 'completed'
              AND completed_at >= ?
              AND completed_at < ?
            GROUP BY bucket
            ORDER BY bucket ASC""",
        (start_text, end_text),
    )
    for row in completed_rows:
        bucket_key = row.get("bucket")
        if bucket_key in points_by_bucket:
            points_by_bucket[bucket_key]["completed_orders"] = int(row.get("completed_orders") or 0)
            points_by_bucket[bucket_key]["gross_revenue"] = int(row.get("gross_revenue") or 0)

    refunded_rows = await fetch_all_dicts(
        f"""SELECT {refunded_sql} AS bucket,
                   COALESCE(SUM(amount), 0) AS refunded_amount
            FROM orders
            WHERE is_refunded = 1
              AND refunded_at >= ?
              AND refunded_at < ?
            GROUP BY bucket
            ORDER BY bucket ASC""",
        (start_text, end_text),
    )
    for row in refunded_rows:
        bucket_key = row.get("bucket")
        if bucket_key in points_by_bucket:
            points_by_bucket[bucket_key]["refunded_amount"] = int(row.get("refunded_amount") or 0)

    return points


async def get_analytics_breakdowns(
    range_key: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict[str, object]:
    resolved = _resolve_range(range_key, date_from=date_from, date_to=date_to)
    start_text = to_db_time_string(resolved.start)
    end_text = to_db_time_string(resolved.end)

    status_rows = await fetch_all_dicts(
        """SELECT status, COUNT(*) AS count
           FROM orders
           WHERE created_at >= ? AND created_at < ?
           GROUP BY status
           ORDER BY count DESC, status ASC""",
        (start_text, end_text),
    )
    product_rows = await fetch_all_dicts(
        """SELECT COALESCE(NULLIF(product_name, ''), 'Không rõ sản phẩm') AS label,
                  COUNT(*) AS order_count,
                  COALESCE(SUM(amount), 0) AS revenue
           FROM orders
           WHERE status = 'completed'
             AND completed_at >= ?
             AND completed_at < ?
           GROUP BY label
           ORDER BY revenue DESC, order_count DESC, label ASC
           LIMIT 5""",
        (start_text, end_text),
    )
    server_rows = await fetch_all_dicts(
        """SELECT COALESCE(NULLIF(api_servers.name, ''), 'Không rõ server') AS label,
                  COUNT(*) AS order_count,
                  COALESCE(SUM(orders.amount), 0) AS revenue
           FROM orders
           LEFT JOIN api_servers ON api_servers.id = orders.server_id
           WHERE orders.status = 'completed'
             AND orders.completed_at >= ?
             AND orders.completed_at < ?
           GROUP BY label
           ORDER BY revenue DESC, order_count DESC, label ASC
           LIMIT 5""",
        (start_text, end_text),
    )

    return {
        "status_counts": [
            {"label": row.get("status") or "unknown", "count": int(row.get("count") or 0)}
            for row in status_rows
        ],
        "top_products": [
            {
                "label": row.get("label") or "Không rõ sản phẩm",
                "order_count": int(row.get("order_count") or 0),
                "revenue": int(row.get("revenue") or 0),
            }
            for row in product_rows
        ],
        "top_servers": [
            {
                "label": row.get("label") or "Không rõ server",
                "order_count": int(row.get("order_count") or 0),
                "revenue": int(row.get("revenue") or 0),
            }
            for row in server_rows
        ],
    }
