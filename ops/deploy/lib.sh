#!/usr/bin/env bash

set -euo pipefail

STACK_ROOT="${STACK_ROOT:-/srv/shupremium-stack}"
REPO_DIR="${REPO_DIR:-$STACK_ROOT/repo}"
RELEASES_DIR="${RELEASES_DIR:-$STACK_ROOT/releases}"
CURRENT_DIR="${CURRENT_DIR:-$STACK_ROOT/current}"
SHARED_DIR="${SHARED_DIR:-$STACK_ROOT/shared}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_FILE="$SCRIPT_DIR/app-manifest.sh"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

now_ms() {
  local value
  value="$(date +%s%3N 2>/dev/null || true)"
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "$value"
    return 0
  fi

  require_cmd python3
  python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

duration_since() {
  local started_at="${1:-0}"
  local current_ms
  current_ms="$(now_ms)"
  echo $((current_ms - started_at))
}

prepare_audit_log() {
  mkdir -p "$SHARED_DIR/_ops"
  DEPLOY_AUDIT_LOG="$SHARED_DIR/_ops/deploy-audit.jsonl"
  touch "$DEPLOY_AUDIT_LOG"
}

set_deploy_context() {
  local host_role="$1"
  local git_ref="${2:-}"
  local release_dir="${3:-}"
  local previous_release="${4:-}"

  prepare_audit_log

  DEPLOY_HOST_ROLE="$host_role"
  DEPLOY_GIT_REF="$git_ref"
  DEPLOY_RELEASE_DIR="$release_dir"
  DEPLOY_PREVIOUS_RELEASE="$previous_release"
}

append_deploy_audit_record() {
  local phase="$1"
  local status="$2"
  local duration_ms="${3:-0}"
  local message="${4:-}"

  require_cmd python3
  DEPLOY_RECORD_PHASE="$phase" \
  DEPLOY_RECORD_STATUS="$status" \
  DEPLOY_RECORD_DURATION_MS="$duration_ms" \
  DEPLOY_RECORD_MESSAGE="$message" \
  DEPLOY_RECORD_APP="$APP_ID" \
  DEPLOY_RECORD_HOST_ROLE="${DEPLOY_HOST_ROLE:-$HOST_ROLE}" \
  DEPLOY_RECORD_RUNTIME_KIND="$RUNTIME_KIND" \
  DEPLOY_RECORD_GIT_REF="${DEPLOY_GIT_REF:-}" \
  DEPLOY_RECORD_RELEASE_DIR="${DEPLOY_RELEASE_DIR:-}" \
  DEPLOY_RECORD_PREVIOUS_RELEASE="${DEPLOY_PREVIOUS_RELEASE:-}" \
  python3 - <<'PY' >>"$DEPLOY_AUDIT_LOG"
import datetime
import json
import os
import sys

record = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    "app": os.environ.get("DEPLOY_RECORD_APP", ""),
    "host_role": os.environ.get("DEPLOY_RECORD_HOST_ROLE", ""),
    "runtime_kind": os.environ.get("DEPLOY_RECORD_RUNTIME_KIND", ""),
    "git_ref": os.environ.get("DEPLOY_RECORD_GIT_REF", ""),
    "release_dir": os.environ.get("DEPLOY_RECORD_RELEASE_DIR", ""),
    "previous_release": os.environ.get("DEPLOY_RECORD_PREVIOUS_RELEASE", ""),
    "phase": os.environ.get("DEPLOY_RECORD_PHASE", ""),
    "status": os.environ.get("DEPLOY_RECORD_STATUS", ""),
    "duration_ms": int(os.environ.get("DEPLOY_RECORD_DURATION_MS", "0") or "0"),
    "message": os.environ.get("DEPLOY_RECORD_MESSAGE", ""),
}

json.dump(record, sys.stdout, ensure_ascii=True)
sys.stdout.write("\n")
PY
}

canonical_dir() {
  local dir="$1"
  [[ -d "$dir" ]] || fail "Directory does not exist: $dir"
  (
    cd "$dir" >/dev/null 2>&1
    pwd -P
  )
}

load_app_config() {
  local app="$1"
  # shellcheck disable=SC1090
  source "$MANIFEST_FILE"
  app_manifest "$app" || fail "App manifest not found for: $app"
}

resolve_host_role() {
  local provided="${1:-}"

  if [[ -n "$provided" ]]; then
    echo "$provided"
    return 0
  fi

  if [[ -f /etc/shupremium-host-role ]]; then
    tr -d ' \t\r\n' </etc/shupremium-host-role
    return 0
  fi

  fail "Missing host role. Pass arm/shopbot or create /etc/shupremium-host-role"
}

ensure_host_role() {
  local actual="$1"
  [[ "$actual" == "$HOST_ROLE" ]] || fail "App $APP_ID requires host role '$HOST_ROLE' but current host is '$actual'"
}

prepare_stack_dirs() {
  mkdir -p "$REPO_DIR" "$RELEASES_DIR" "$CURRENT_DIR" "$SHARED_DIR"
  mkdir -p "$SHARED_DIR/$SHARED_NAME"
  mkdir -p "$SHARED_DIR/_ops"
}

ensure_repo() {
  [[ -d "$REPO_DIR/.git" ]] || fail "Git repo not found at $REPO_DIR"
}

fetch_ref() {
  local requested_ref="$1"
  ensure_repo
  git -C "$REPO_DIR" fetch --prune --tags origin

  if git -C "$REPO_DIR" rev-parse --verify "${requested_ref}^{commit}" >/dev/null 2>&1; then
    echo "$requested_ref"
    return 0
  fi

  if git -C "$REPO_DIR" rev-parse --verify "origin/${requested_ref}^{commit}" >/dev/null 2>&1; then
    echo "origin/$requested_ref"
    return 0
  fi

  fail "Could not resolve git ref: $requested_ref"
}

current_target() {
  local link="$CURRENT_DIR/$APP_ID"
  if [[ -L "$link" ]]; then
    readlink -f "$link"
  fi
}

validate_release_dir() {
  local release_dir="$1"
  local resolved_release
  local resolved_releases_root

  resolved_release="$(canonical_dir "$release_dir")"
  mkdir -p "$RELEASES_DIR"
  resolved_releases_root="$(canonical_dir "$RELEASES_DIR")"

  if [[ "$resolved_release" != "$resolved_releases_root"/*/"$APP_ID" ]]; then
    fail "Invalid release path for $APP_ID: $resolved_release"
  fi

  echo "$resolved_release"
}

create_release_dir() {
  local ts="$1"
  local release_dir="$RELEASES_DIR/$ts/$APP_ID"
  mkdir -p "$release_dir"
  echo "$release_dir"
}

extract_release_subtree() {
  local ref="$1"
  local release_dir="$2"

  mkdir -p "$release_dir"
  git -C "$REPO_DIR" archive "$ref" "$SOURCE_PATH" | tar -x -C "$release_dir" --strip-components "$SOURCE_STRIP_COMPONENTS"
}

switch_current_link() {
  local release_dir="$1"
  local validated_release
  validated_release="$(validate_release_dir "$release_dir")"
  ln -sfn "$validated_release" "$CURRENT_DIR/$APP_ID"
}

cleanup_old_releases() {
  local keep="${1:-5}"
  local current_release
  current_release="$(current_target || true)"
  local app_releases
  mapfile -t app_releases < <(
    find "$RELEASES_DIR" -mindepth 2 -maxdepth 2 -type d -name "$APP_ID" | sort -r
  )
  local count=0
  for dir in "${app_releases[@]}"; do
    local resolved
    resolved="$(cd "$dir" && pwd -P)"
    count=$((count + 1))
    if [[ $count -gt $keep && "$resolved" != "$current_release" ]]; then
      local parent
      parent="$(dirname "$dir")"
      # Only remove the timestamp dir if it has no other app folders left
      local sibling_count
      sibling_count="$(find "$parent" -mindepth 1 -maxdepth 1 -type d | wc -l)"
      if [[ "$sibling_count" -le 1 ]]; then
        log "Xoá release cũ: $parent"
        rm -rf "$parent"
      else
        log "Xoá app release cũ: $dir"
        rm -rf "$dir"
      fi
    fi
  done
}

link_shared_file() {
  local shared_file="$1"
  local release_file="$2"
  local required="${3:-true}"

  if [[ ! -f "$shared_file" ]]; then
    if [[ "$required" == "true" ]]; then
      fail "Missing required runtime file: $shared_file"
    fi
    return 0
  fi

  rm -f "$release_file"
  ln -s "$shared_file" "$release_file"
}

link_shared_dir() {
  local shared_dir="$1"
  local release_dir="$2"
  mkdir -p "$shared_dir"
  rm -rf "$release_dir"
  ln -s "$shared_dir" "$release_dir"
}

prepare_python_release() {
  local release_dir="$1"
  local shared_root="$SHARED_DIR/$SHARED_NAME"
  local venv_dir="$shared_root/venv"

  require_cmd python3
  require_cmd curl

  [[ -f "$shared_root/.env" ]] || fail "Missing .env at $shared_root/.env"

  mkdir -p "$shared_root/data"
  link_shared_file "$shared_root/.env" "$release_dir/.env" true
  link_shared_dir "$shared_root/data" "$release_dir/data"

  if [[ ! -d "$venv_dir" ]]; then
    log "Creating shared venv for $APP_ID at $venv_dir"
    python3 -m venv "$venv_dir"
  fi

  "$venv_dir/bin/pip" install --upgrade pip setuptools wheel
  if [[ -n "$PYTHON_REQUIREMENTS" && -f "$release_dir/$PYTHON_REQUIREMENTS" ]]; then
    "$venv_dir/bin/pip" install -r "$release_dir/$PYTHON_REQUIREMENTS"
  fi

  link_shared_dir "$venv_dir" "$release_dir/.venv"
}

prepare_proxy_gateway_release() {
  local release_dir="$1"
  local shared_root="$SHARED_DIR/$SHARED_NAME"

  require_cmd npm

  mkdir -p "$shared_root/proxy-operator"

  link_shared_file "$shared_root/proxy-operator/.env" "$release_dir/proxy-operator/.env" true

  # Install Node.js dependencies for proxy-operator
  if [[ -f "$release_dir/proxy-operator/package.json" ]]; then
    log "Installing proxy-operator dependencies"
    ( cd "$release_dir/proxy-operator" && npm ci --omit=dev )
  fi

  # Install Node.js dependencies for proxy-service
  if [[ -f "$release_dir/proxy-service/package.json" ]]; then
    log "Installing proxy-service dependencies"
    ( cd "$release_dir/proxy-service" && npm ci --omit=dev )
  fi

  # Ensure logs directory exists for proxy-service
  mkdir -p "$release_dir/proxy-service/logs"
}

validate_python_release() {
  local release_dir="$1"
  local python_bin="$release_dir/.venv/bin/python"

  require_cmd python3
  [[ -x "$python_bin" ]] || fail "Missing Python runtime for validation: $python_bin"

  "$python_bin" -m pip check

  case "$APP_ID" in
    portal|platform-control)
      (
        cd "$release_dir"
        PYTHONPATH="$release_dir" "$python_bin" - <<'PY'
from dotenv import load_dotenv

load_dotenv(".env")

from app.app import create_app

application = create_app()
assert application is not None
PY
      )
      ;;
    shopbot)
      (
        cd "$release_dir"
        PYTHONPATH="$release_dir" "$python_bin" - <<'PY'
from dotenv import load_dotenv

load_dotenv(".env")

import bot.main  # noqa: F401
from admin.app import create_admin_app

application = create_admin_app()
assert application is not None
PY
      )
      ;;
    *)
      fail "Unsupported Python app validation for: $APP_ID"
      ;;
  esac
}

validate_node_package_dir() {
  local package_dir="$1"
  local syntax_target="$2"
  shift 2
  local packages=("$@")

  require_cmd node
  require_cmd npm

  [[ -f "$package_dir/package.json" ]] || fail "Missing package.json for validation: $package_dir"

  (
    cd "$package_dir"
    npm ls --omit=dev --depth=0
    node --check "$syntax_target"
    node - "${packages[@]}" <<'NODE'
const packages = process.argv.slice(2);
for (const pkg of packages) {
  require.resolve(pkg);
}
NODE
  )
}

validate_proxy_gateway_release() {
  local release_dir="$1"

  validate_node_package_dir \
    "$release_dir/proxy-operator" \
    "src/server.js" \
    dotenv \
    express

  validate_node_package_dir \
    "$release_dir/proxy-service" \
    "src/index.js" \
    fastify \
    @fastify/http-proxy \
    undici \
    pino \
    pino-pretty
}

validate_release() {
  local release_dir="$1"

  case "$RUNTIME_KIND" in
    pm2-python|systemd-python)
      validate_python_release "$release_dir"
      ;;
    pm2-node-multi)
      validate_proxy_gateway_release "$release_dir"
      ;;
    *)
      fail "Unsupported runtime kind for validation: $RUNTIME_KIND"
      ;;
  esac
}

pm2_process_exists() {
  local name="$1"
  pm2 describe "$name" >/dev/null 2>&1
}

pm2_process_is_online() {
  local name="$1"
  require_cmd node

  pm2 jlist | node -e '
const name = process.argv[1];
let data = "";
process.stdin.on("data", (chunk) => data += chunk);
process.stdin.on("end", () => {
  const apps = JSON.parse(data || "[]");
  const app = apps.find((item) => item && item.name === name);
  if (!app) {
    process.exit(2);
  }
  const status = String((app.pm2_env && app.pm2_env.status) || "");
  if (status === "online") {
    process.exit(0);
  }
  process.stderr.write(status || "unknown");
  process.exit(1);
});
' "$name"
}

ensure_pm2_process_online() {
  local name="$1"
  if ! pm2_process_is_online "$name"; then
    fail "PM2 process not online: $name"
  fi
}

restart_pm2_python_app() {
  local cwd="$CURRENT_DIR/$APP_ID"
  local python_bin="$SHARED_DIR/$SHARED_NAME/venv/bin/python"
  local entry_path="$cwd/$PM2_ENTRY"

  require_cmd pm2

  if pm2_process_exists "$PROCESS_NAME"; then
    pm2 delete "$PROCESS_NAME"
  fi

  pm2 start "$python_bin" \
    --name "$PROCESS_NAME" \
    --cwd "$cwd" \
    --interpreter none \
    -- "$entry_path"
}

restart_shopbot_systemd() {
  require_cmd systemctl
  sudo systemctl restart "$SYSTEMD_UNIT"
  sudo systemctl is-active --quiet "$SYSTEMD_UNIT" || fail "systemd unit $SYSTEMD_UNIT is not active"
}

restart_proxy_gateway_pm2() {
  local cwd="$CURRENT_DIR/$APP_ID"

  require_cmd pm2

  (
    cd "$cwd/proxy-operator"
    if pm2_process_exists "proxy-operator"; then
      pm2 restart proxy-operator --update-env
    else
      pm2 start src/server.js --name proxy-operator --cwd "$cwd/proxy-operator"
    fi
  )

  (
    cd "$cwd/proxy-service"
    if ! pm2 reload ecosystem.config.js --update-env >/dev/null 2>&1; then
      pm2 start ecosystem.config.js
    fi
  )

}

run_http_smoke_checks() {
  local url
  local accepted
  local status
  local attempt

  require_cmd curl
  [[ -n "${SMOKE_URLS:-}" ]] || return 0

  while IFS='|' read -r url accepted; do
    [[ -n "$url" ]] || continue
    status=""
    for attempt in {1..15}; do
      status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$url" || true)"
      case ",$accepted," in
        *",$status,"*) break ;;
      esac
      sleep 1
    done
    case ",$accepted," in
      *",$status,"*) log "Smoke OK: $url -> $status" ;;
      *) fail "Smoke FAIL: $url -> $status (expected $accepted)" ;;
    esac
  done <<<"$SMOKE_URLS"
}

run_proxy_gateway_smoke_checks() {
  local cwd="$CURRENT_DIR/$APP_ID"
  local service_cfg="$cwd/proxy-service/ecosystem.config.js"
  local entry
  local name
  local port
  local status
  local attempt

  require_cmd curl
  require_cmd pm2
  require_cmd node

  ensure_pm2_process_online "proxy-operator"
  [[ -f "$service_cfg" ]] || fail "Missing proxy-service ecosystem config: $service_cfg"

  mapfile -t proxy_apps < <(
      node -e '
const cfg = require(process.argv[1]);
for (const app of (cfg.apps || [])) {
  if (!app || !app.name) continue;
  const port = app.env && (app.env.PORT ?? app.env.port ?? "");
  process.stdout.write(`${app.name}|${port}\n`);
}
' "$service_cfg"
    )

  for entry in "${proxy_apps[@]}"; do
    IFS='|' read -r name port <<<"$entry"
    [[ -n "$name" ]] || continue
    ensure_pm2_process_online "$name"
    [[ -n "$port" ]] || fail "Missing PORT for proxy service app: $name"
    status=""
    for attempt in {1..15}; do
      status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:${port}/_internal/health" || true)"
      case ",200," in
        *",$status,"*) break ;;
      esac
      sleep 1
    done
    case ",200," in
      *",$status,"*) log "Smoke OK: proxy $name -> $status" ;;
      *) fail "Smoke FAIL: proxy $name -> $status (expected 200)" ;;
    esac
  done

}

run_runtime_smoke_checks() {
  case "$RUNTIME_KIND" in
    pm2-python)
      run_http_smoke_checks
      ;;
    systemd-python)
      sudo systemctl is-active --quiet "$SYSTEMD_UNIT" || fail "Unit $SYSTEMD_UNIT is not active after deploy"
      ;;
    pm2-node-multi)
      run_proxy_gateway_smoke_checks
      ;;
    *)
      ;;
  esac
}

restart_app_runtime() {
  case "$RUNTIME_KIND" in
    pm2-python)
      restart_pm2_python_app
      ;;
    systemd-python)
      restart_shopbot_systemd
      ;;
    pm2-node-multi)
      restart_proxy_gateway_pm2
      ;;
    *)
      fail "Unsupported runtime kind: $RUNTIME_KIND"
      ;;
  esac
}

rollback_to_release() {
  local target_release="$1"
  local reason="${2:-rollback requested}"
  local rollback_started
  local rollback_duration

  [[ -n "$target_release" ]] || return 1
  rollback_started="$(now_ms)"
  append_deploy_audit_record "rollback" "start" 0 "$reason"

  if switch_current_link "$target_release" && restart_app_runtime && run_runtime_smoke_checks; then
    rollback_duration="$(duration_since "$rollback_started")"
    append_deploy_audit_record "rollback" "success" "$rollback_duration" "Rollback completed: $target_release"
    return 0
  fi

  rollback_duration="$(duration_since "$rollback_started")"
  append_deploy_audit_record "rollback" "failure" "$rollback_duration" "Rollback failed: $target_release"
  return 1
}

deploy_release() {
  local release_dir="$1"
  local previous_release="${2:-}"
  local prepare_function="$3"
  local phase_started
  local phase_duration

  append_deploy_audit_record "deploy" "start" 0 "Deploy started"

  if ! extract_release_subtree "$DEPLOY_GIT_REF" "$release_dir"; then
    append_deploy_audit_record "deploy" "failure" 0 "Release extraction failed"
    fail "Deploy $APP_ID failed during extract"
  fi

  phase_started="$(now_ms)"
  if ! "$prepare_function" "$release_dir"; then
    phase_duration="$(duration_since "$phase_started")"
    append_deploy_audit_record "prepare" "failure" "$phase_duration" "Release preparation failed"
    append_deploy_audit_record "deploy" "failure" "$phase_duration" "Deploy failed during prepare"
    fail "Deploy $APP_ID failed during prepare"
  fi
  phase_duration="$(duration_since "$phase_started")"
  append_deploy_audit_record "prepare" "success" "$phase_duration" "Release prepared"

  phase_started="$(now_ms)"
  if ! validate_release "$release_dir"; then
    phase_duration="$(duration_since "$phase_started")"
    append_deploy_audit_record "validate" "failure" "$phase_duration" "Release validation failed"
    append_deploy_audit_record "deploy" "failure" "$phase_duration" "Deploy failed during validate"
    fail "Deploy $APP_ID failed during validate"
  fi
  phase_duration="$(duration_since "$phase_started")"
  append_deploy_audit_record "validate" "success" "$phase_duration" "Release validation passed"

  phase_started="$(now_ms)"
  if ! switch_current_link "$release_dir"; then
    phase_duration="$(duration_since "$phase_started")"
    append_deploy_audit_record "switch" "failure" "$phase_duration" "Failed to switch current release"
    append_deploy_audit_record "deploy" "failure" "$phase_duration" "Deploy failed during switch"
    fail "Deploy $APP_ID failed during release switch"
  fi
  phase_duration="$(duration_since "$phase_started")"
  append_deploy_audit_record "switch" "success" "$phase_duration" "Current release updated"

  phase_started="$(now_ms)"
  if ! restart_app_runtime; then
    phase_duration="$(duration_since "$phase_started")"
    append_deploy_audit_record "restart" "failure" "$phase_duration" "Runtime restart failed"
    if [[ -n "$previous_release" ]] && ! rollback_to_release "$previous_release" "Restart failed after switching release"; then
      append_deploy_audit_record "deploy" "failure" "$phase_duration" "Restart failed and rollback did not recover"
      fail "Deploy $APP_ID failed: restart and rollback both failed"
    fi
    append_deploy_audit_record "deploy" "failure" "$phase_duration" "Deploy failed during restart"
    fail "Deploy $APP_ID failed during restart"
  fi
  phase_duration="$(duration_since "$phase_started")"
  append_deploy_audit_record "restart" "success" "$phase_duration" "Runtime restarted"

  phase_started="$(now_ms)"
  if ! run_runtime_smoke_checks; then
    phase_duration="$(duration_since "$phase_started")"
    append_deploy_audit_record "smoke" "failure" "$phase_duration" "Smoke checks failed"
    if [[ -n "$previous_release" ]] && ! rollback_to_release "$previous_release" "Smoke checks failed after switching release"; then
      append_deploy_audit_record "deploy" "failure" "$phase_duration" "Smoke checks failed and rollback did not recover"
      fail "Deploy $APP_ID failed: smoke checks and rollback both failed"
    fi
    append_deploy_audit_record "deploy" "failure" "$phase_duration" "Deploy failed during smoke checks"
    fail "Deploy $APP_ID failed during smoke checks"
  fi
  phase_duration="$(duration_since "$phase_started")"
  append_deploy_audit_record "smoke" "success" "$phase_duration" "Smoke checks passed"

  append_deploy_audit_record "deploy" "success" 0 "Deploy completed"
}
