#!/usr/bin/env bash
# Prepare a committed release without linking production data or starting services.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

APP="${1:-}"
REF="${2:-main}"
[[ -n "$APP" ]] || fail "Usage: stage-app.sh <app> [git-ref]"
require_cmd git
require_cmd tar
require_cmd mktemp

load_app_config "$APP"

[[ -d "$REPO_DIR/.git" || -f "$REPO_DIR/.git" ]] || fail "Repository not found: $REPO_DIR"
COMMIT="$(git -C "$REPO_DIR" rev-parse --verify --end-of-options "${REF}^{commit}")" || fail "Git ref is not available locally"
[[ "$COMMIT" =~ ^[0-9a-f]{40,64}$ ]] || fail "Invalid commit identifier"

mkdir -p "$STACK_ROOT"
ROOT_PHYSICAL="$(cd "$STACK_ROOT" && pwd -P)"
[[ ! -L "$STACK_ROOT/staging" ]] || fail "Staging directory must not be a symlink"
mkdir -p "$STACK_ROOT/staging"
STAGING_ROOT="$(cd "$STACK_ROOT/staging" && pwd -P)"
[[ "$STAGING_ROOT" == "$ROOT_PHYSICAL/staging" ]] || fail "Invalid staging directory"
STAGE_DIR="$(mktemp -d "$STAGING_ROOT/${APP}.XXXXXXXX")"
RELEASE="$STAGE_DIR/release"
mkdir -p "$RELEASE" "$STAGE_DIR/home" "$STAGE_DIR/tmp"
log "Staging $APP from $COMMIT at $STAGE_DIR"

git -C "$REPO_DIR" archive "$COMMIT" "$SOURCE_PATH" | tar -x -C "$RELEASE" --strip-components "$SOURCE_STRIP_COMPONENTS"
[[ ! -e "$RELEASE/.env" && ! -L "$RELEASE/.env" ]] || fail "Committed .env is not allowed in staging"

if [[ "$RUNTIME_KIND" == "pm2-python" || "$RUNTIME_KIND" == "systemd-python" ]]; then
  require_cmd python3
  [[ ! -e "$RELEASE/.venv" && ! -L "$RELEASE/.venv" ]] || fail "Committed venv is not allowed in staging"
  [[ -f "$RELEASE/requirements.txt" && ! -L "$RELEASE/requirements.txt" ]] || fail "Missing or symlinked requirements.txt"
  env -i PATH="$PATH" HOME="$STAGE_DIR/home" TMPDIR="$STAGE_DIR/tmp" python3 -m venv "$RELEASE/.venv"
  env -i PATH="$PATH" HOME="$STAGE_DIR/home" TMPDIR="$STAGE_DIR/tmp" "$RELEASE/.venv/bin/pip" install -r "$RELEASE/requirements.txt"
  env -i PATH="$PATH" HOME="$STAGE_DIR/home" TMPDIR="$STAGE_DIR/tmp" "$RELEASE/.venv/bin/python" -m pip check
  if [[ "$APP" == "shopbot" ]]; then
    require_cmd node
    require_cmd npm
    node -e 'if (Number(process.versions.node.split(".")[0]) < 20) process.exit(1)' || fail "Shopbot VietQR requires Node.js >= 20"
    [[ -f "$RELEASE/package-lock.json" && ! -L "$RELEASE/package-lock.json" ]] || fail "Missing or symlinked Shopbot package-lock.json"
    (cd "$RELEASE" && env -i PATH="$PATH" HOME="$STAGE_DIR/home" TMPDIR="$STAGE_DIR/tmp" npm ci --omit=dev --ignore-scripts)
    env -i PATH="$PATH" HOME="$STAGE_DIR/home" TMPDIR="$STAGE_DIR/tmp" \
      node "$RELEASE/bot/services/vietqr_node.cjs" MB 0123456789 TEST 10000 TEST compact2 > "$STAGE_DIR/vietqr.png"
    "$RELEASE/.venv/bin/python" -c 'from pathlib import Path; assert Path(__import__("sys").argv[1]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")' "$STAGE_DIR/vietqr.png"
  fi
  case "$APP" in
    portal|platform-control) IMPORTS='from app.app import create_app' ;;
    shopbot) IMPORTS='import bot.main; from admin.app import create_admin_app' ;;
    key-vault-worker) IMPORTS='import main' ;;
    *) fail "Unsupported Python staging app" ;;
  esac
  (
    cd "$RELEASE"
    env -i PATH="$PATH" HOME="$STAGE_DIR/home" TMPDIR="$STAGE_DIR/tmp" \
      PYTHONPATH="$RELEASE" DB_PATH="$STAGE_DIR/staging.sqlite" SEED_DEMO_SERVER=false \
      KEY_VAULT_MASTER_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8= \
      "$RELEASE/.venv/bin/python" -c "$IMPORTS"
  )
elif [[ "$APP" == "proxy-gateway" ]]; then
  require_cmd npm
  require_cmd node
  for part in proxy-operator proxy-service; do
    [[ -d "$RELEASE/$part" && ! -L "$RELEASE/$part" ]] || fail "Invalid proxy package directory"
    [[ ! -e "$RELEASE/$part/.env" && ! -L "$RELEASE/$part/.env" ]] || fail "Committed .env is not allowed in staging"
    [[ ! -e "$RELEASE/$part/node_modules" && ! -L "$RELEASE/$part/node_modules" ]] || fail "Committed node_modules is not allowed in staging"
    [[ -f "$RELEASE/$part/package-lock.json" && ! -L "$RELEASE/$part/package-lock.json" ]] || fail "Missing or symlinked package-lock.json"
    (
      cd "$RELEASE/$part"
      env -i PATH="$PATH" HOME="$STAGE_DIR/home" TMPDIR="$STAGE_DIR/tmp" npm ci --ignore-scripts
      if [[ "$part" == proxy-operator ]]; then target=src/server.js; else target=src/index.js; fi
      env -i PATH="$PATH" HOME="$STAGE_DIR/home" TMPDIR="$STAGE_DIR/tmp" node --check "$target"
    )
  done
else
  fail "Unsupported staging runtime"
fi

log "Staging checks passed for $APP at $STAGE_DIR (services were not started)"
