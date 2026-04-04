#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${DB_PATH:-$ROOT_DIR/shopbot.db}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="$BACKUP_DIR/$STAMP"

mkdir -p "$RUN_DIR"

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required for consistent backups" >&2
  exit 1
fi

sqlite3 "$DB_PATH" ".backup '$RUN_DIR/shopbot.db'"
cp "$ROOT_DIR/.env" "$RUN_DIR/.env" 2>/dev/null || true

cat > "$RUN_DIR/manifest.txt" <<EOF
created_at=$(date -Is)
db_path=$DB_PATH
backup_file=$RUN_DIR/shopbot.db
EOF

echo "Backup created at $RUN_DIR"
