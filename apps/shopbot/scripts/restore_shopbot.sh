#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: restore_shopbot.sh <backup_dir>" >&2
  exit 1
fi

BACKUP_DIR="$1"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DB="${DB_PATH:-$ROOT_DIR/shopbot.db}"

if [ ! -f "$BACKUP_DIR/shopbot.db" ]; then
  echo "Backup database not found in $BACKUP_DIR" >&2
  exit 1
fi

cp "$BACKUP_DIR/shopbot.db" "$TARGET_DB"
echo "Restored database to $TARGET_DB"
