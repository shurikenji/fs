"""
admin/routers/analytics.py - Admin analytics page.
"""
from __future__ import annotations

from fastapi import Query, Request
from fastapi.responses import HTMLResponse

from admin.deps import get_templates, protected_router
from db.queries.analytics import (
    get_analytics_breakdowns,
    get_analytics_series,
    get_analytics_summary,
)

router = protected_router(prefix="/analytics", tags=["analytics"])

_RANGE_OPTIONS = [
    {"key": "today", "label": "Hôm nay"},
    {"key": "yesterday", "label": "Hôm qua"},
    {"key": "last_7d", "label": "7 ngày"},
    {"key": "last_30d", "label": "30 ngày"},
    {"key": "this_month", "label": "Tháng này"},
    {"key": "last_month", "label": "Tháng trước"},
    {"key": "custom", "label": "Tùy chọn"},
]


def _decorate_series(points: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, int]]:
    max_created = max((int(point.get("created_orders") or 0) for point in points), default=0)
    max_completed = max((int(point.get("gross_revenue") or 0) for point in points), default=0)
    max_refunded = max((int(point.get("refunded_amount") or 0) for point in points), default=0)

    decorated: list[dict[str, object]] = []
    for point in points:
        created_orders = int(point.get("created_orders") or 0)
        gross_revenue = int(point.get("gross_revenue") or 0)
        refunded_amount = int(point.get("refunded_amount") or 0)
        decorated.append(
            {
                **point,
                "created_width": (created_orders / max_created * 100) if max_created else 0,
                "revenue_width": (gross_revenue / max_completed * 100) if max_completed else 0,
                "refund_width": (refunded_amount / max_refunded * 100) if max_refunded else 0,
            }
        )

    return decorated, {
        "created_orders": max_created,
        "gross_revenue": max_completed,
        "refunded_amount": max_refunded,
    }


@router.get("", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    range_key: str = Query("this_month"),
    bucket: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> HTMLResponse:
    summary = await get_analytics_summary(range_key, date_from=date_from, date_to=date_to)
    series = await get_analytics_series(
        range_key,
        bucket=bucket or str(summary["range"]["bucket"]),
        date_from=date_from,
        date_to=date_to,
    )
    breakdowns = await get_analytics_breakdowns(range_key, date_from=date_from, date_to=date_to)
    decorated_series, series_max = _decorate_series(series)

    templates = get_templates()
    return templates.TemplateResponse(
        "analytics.html",
        {
            "request": request,
            "range_options": _RANGE_OPTIONS,
            "summary": summary,
            "series": decorated_series,
            "series_max": series_max,
            "breakdowns": breakdowns,
        },
    )
