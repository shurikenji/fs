"""Safely link legacy Shopbot servers to stable control-plane source IDs.

Default mode is report-only. It only suggests a mapping when a source and a
local server match uniquely by upstream host; name is used only as a secondary
signal. Applying requires an explicit flag and refuses ambiguous snapshots.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.database import get_db
from db.queries.servers import get_all_servers


def _host(url: object) -> str:
    parsed = urlparse(str(url or "").strip())
    return (parsed.hostname or "").lower()


def propose_mappings(servers: list[dict[str, Any]], sources: list[dict[str, Any]]) -> tuple[dict[int, str], list[str]]:
    """Return unambiguous `api_servers.id -> source.id` candidates and errors."""
    unmanaged = [server for server in servers if not server.get("control_plane_source_id")]
    source_by_host: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            continue
        host = _host(source.get("upstream_base_url"))
        if host:
            source_by_host[host].append(source)
        name = str(source.get("name") or "").strip().casefold()
        if name:
            source_by_name[name].append(source)

    proposed: dict[int, str] = {}
    errors: list[str] = []
    claimed: dict[str, int] = {}
    for server in unmanaged:
        server_id = int(server["id"])
        host = _host(server.get("base_url"))
        candidates = source_by_host.get(host, [])
        if not candidates:
            candidates = source_by_name.get(str(server.get("name") or "").strip().casefold(), [])
        if len(candidates) != 1:
            errors.append(f"server {server_id} ({server.get('name')!r}) is unmatched or ambiguous")
            continue
        source_id = str(candidates[0]["id"])
        if source_id in claimed:
            errors.append(f"source {source_id!r} matches both server {claimed[source_id]} and {server_id}")
            continue
        proposed[server_id] = source_id
        claimed[source_id] = server_id
    return proposed, errors


async def _apply(mappings: dict[int, str]) -> None:
    db = await get_db()
    await db.execute("BEGIN")
    try:
        for server_id, source_id in mappings.items():
            cursor = await db.execute(
                "UPDATE api_servers SET control_plane_source_id = ?, updated_at = datetime('now', '+7 hours') "
                "WHERE id = ? AND control_plane_source_id IS NULL",
                (source_id, server_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"server {server_id} changed while mapping; nothing was written")
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="JSON response from /api/internal/config/shopbot")
    parser.add_argument("--apply", action="store_true", help="write the proposed, conflict-free mappings")
    args = parser.parse_args()
    payload = json.loads(args.snapshot.read_text(encoding="utf-8"))
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list):
        raise ValueError("snapshot must contain a sources array")
    mappings, errors = propose_mappings(await get_all_servers(), [item for item in sources if isinstance(item, dict)])
    print(json.dumps({"proposed_mappings": mappings, "errors": errors}, ensure_ascii=False, indent=2))
    if errors:
        return 2
    if args.apply:
        await _apply(mappings)
        print(f"Applied {len(mappings)} control-plane mapping(s).")
    else:
        print("Report only. Re-run with --apply after reviewing this exact output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
