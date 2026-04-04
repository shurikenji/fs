"""Adapter factory — returns the right adapter for a server type."""
from __future__ import annotations

from app.adapters.base import BaseAdapter
from app.adapters.custom import CustomAdapter
from app.adapters.newapi import NewApiAdapter
from app.adapters.rixapi import RixApiAdapter
from app.server_profiles import describe_server_profile


_ADAPTERS: dict[str, type[BaseAdapter]] = {
    "custom": CustomAdapter,
    "newapi": NewApiAdapter,
    "rixapi": RixApiAdapter,
}


def get_adapter(server: dict) -> BaseAdapter:
    profile = describe_server_profile(server)
    parser_id = str(profile.get("parser_id") or "").strip().lower()
    if parser_id == "custom_manual":
        cls = CustomAdapter
    elif parser_id == "rixapi_inline":
        cls = RixApiAdapter
    else:
        server_type = (server.get("type") or "newapi").lower()
        cls = _ADAPTERS.get(server_type, NewApiAdapter)
    return cls()
