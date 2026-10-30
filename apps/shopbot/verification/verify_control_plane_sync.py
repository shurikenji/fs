"""Small verification for the central shopbot snapshot mapper."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.services.control_plane_sync import _server_values, _validate_snapshot_sources


def main() -> None:
    values = _server_values(
        {
            "id": "gemini",
            "name": "Gemini",
            "upstream_base_url": "https://upstream.example",
            "source_type": "other",
            "auth_user_value": "42",
            "auth_token": "secret",
            "quota_multiple": 1.5,
            "price_per_unit": 12000,
            "quota_per_unit": 500000,
            "profile_sort_order": 2,
        },
        None,
    )
    assert values["control_plane_source_id"] == "gemini"
    assert values["base_url"] == "https://upstream.example"
    assert values["access_token"] == "secret"
    assert values["price_per_unit"] == 12000
    try:
        _validate_snapshot_sources([{"id": "bad", "name": "Bad", "upstream_base_url": "not-a-url"}])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid upstream URL was accepted")
    print("[OK] control-plane snapshot mapping")


if __name__ == "__main__":
    main()
