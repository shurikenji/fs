"""Explicitly initialize a new Vault database; never overwrite an existing file."""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


async def initialize(data_root: str) -> None:
    if len(main.LOOKUP_SECRET) < 32 or main.LOOKUP_SECRET != main.LOOKUP_SECRET.strip() or main.LOOKUP_SECRET.lower().startswith("change-me"):
        raise ValueError("KEY_VAULT_LOOKUP_SECRET must be a non-default secret of at least 32 characters")
    database = main.DB_PATH
    if not database.is_absolute() or not database.name:
        raise ValueError("KEY_VAULT_DB_PATH must be an absolute file path")
    root = Path(data_root).resolve(strict=True)
    parent = database.parent.resolve(strict=True)
    if not root.is_dir() or not parent.is_relative_to(root):
        raise ValueError("Vault database must be inside the shared data directory")
    target = parent / database.name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags, 0o600)
    os.close(fd)
    await main.init_db()
    await main.require_vault_schema()
    print("New Vault database initialized")


def main_cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    args = parser.parse_args()
    asyncio.run(initialize(args.data_root))


if __name__ == "__main__":
    main_cli()
