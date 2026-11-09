"""Verify the Python bridge to the offline vietqr-node renderer."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.services import vietqr


SETTINGS = {
    "mb_bank_id": "MB",
    "mb_account_no": "0123456789",
    "mb_account_name": "TEST",
    "vietqr_template": "compact2",
}


async def verify() -> None:
    with patch.object(vietqr, "get_setting", AsyncMock(side_effect=lambda key: SETTINGS.get(key))):
        photo = await vietqr.build_qr_photo(10000, "TEST123")
    assert photo.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(photo.data) <= 5 * 1024 * 1024


def main() -> int:
    asyncio.run(verify())
    print("[OK] vietqr-node rendered PNG offline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
