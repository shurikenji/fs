"""Preparation and rendering helpers for public pricing payloads."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from app.group_catalog import build_group_catalog_map, ensure_server_group_catalog
from app.sanitizer import sanitize_pricing
from app.schemas import NormalizedPricing
from app.visibility import excluded_model_names, filter_group_rows, hidden_group_names

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublicPricingPresentation:
    hidden_groups: set[str]
    excluded_models: set[str]
    group_catalog: dict[str, dict[str, Any]] | None = None


async def prepare_public_pricing_presentation(
    pricing: NormalizedPricing,
    server: dict,
) -> PublicPricingPresentation:
    hidden_groups = hidden_group_names(server)
    excluded_models = excluded_model_names(server)
    catalog_rows = await ensure_server_group_catalog(server)
    visible_rows = filter_group_rows(catalog_rows, hidden_groups=hidden_groups) if catalog_rows else []

    if visible_rows and not catalog_matches_pricing_groups(visible_rows, pricing):
        logger.warning(
            "Ignoring stale group catalog for %s because it does not match current pricing groups",
            server.get("id") or pricing.server_id,
        )
        visible_rows = []

    return PublicPricingPresentation(
        hidden_groups=hidden_groups,
        excluded_models=excluded_models,
        group_catalog=build_group_catalog_map(visible_rows) if visible_rows else None,
    )


def render_public_pricing(
    pricing: NormalizedPricing,
    presentation: PublicPricingPresentation,
) -> NormalizedPricing:
    return sanitize_pricing(
        pricing,
        group_catalog=presentation.group_catalog,
        hidden_groups=presentation.hidden_groups,
        excluded_models=presentation.excluded_models,
    )


def catalog_matches_pricing_groups(
    catalog_rows: list[dict[str, Any]],
    pricing: NormalizedPricing,
) -> bool:
    pricing_group_names = {str(group.name or "").strip() for group in pricing.groups if str(group.name or "").strip()}
    if not pricing_group_names:
        return True

    catalog_group_names = {
        str(row.get("name") or "").strip()
        for row in catalog_rows
        if str(row.get("name") or "").strip()
    }
    if not catalog_group_names:
        return False
    return bool(pricing_group_names & catalog_group_names)
