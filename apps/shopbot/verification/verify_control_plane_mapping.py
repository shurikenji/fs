"""Regression checks for safe legacy-server mapping candidates."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.map_control_plane_sources import propose_mappings


def main() -> None:
    sources = [
        {"id": "gpt1", "name": "GPT 1", "upstream_base_url": "https://upstream.example/v1"},
        {"id": "gemini", "name": "Gemini", "upstream_base_url": "https://gemini.example"},
    ]
    mappings, errors = propose_mappings(
        [{"id": 7, "name": "Old GPT", "base_url": "https://upstream.example/api"}], sources
    )
    assert mappings == {7: "gpt1"} and not errors
    mappings, errors = propose_mappings(
        [{"id": 8, "name": "Duplicate", "base_url": "https://upstream.example"}],
        [*sources, {"id": "gpt2", "name": "Duplicate", "upstream_base_url": "https://upstream.example"}],
    )
    assert not mappings and errors
    print("[OK] control-plane mapping only proposes unique matches")


if __name__ == "__main__":
    main()
