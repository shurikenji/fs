#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
source "$SCRIPT_DIR/lib.sh"

REF="${1:-main}"
HOST_ROLE_VALUE="$(resolve_host_role "${2:-}")"

load_app_config platform-control
ensure_host_role "$HOST_ROLE_VALUE"
prepare_stack_dirs

RESOLVED_REF="$(fetch_ref "$REF")"
TS="$(date '+%Y%m%d-%H%M%S')"
RELEASE_DIR="$(create_release_dir "$TS")"
PREVIOUS_RELEASE="$(current_target || true)"

log "Deploy platform-control từ ref $RESOLVED_REF"
extract_release_subtree "$RESOLVED_REF" "$RELEASE_DIR"
prepare_python_release "$RELEASE_DIR"
switch_current_link "$RELEASE_DIR"

if ! restart_app_runtime || ! run_runtime_smoke_checks; then
  if [[ -n "$PREVIOUS_RELEASE" ]]; then
    log "Khôi phục release cũ: $PREVIOUS_RELEASE"
    switch_current_link "$PREVIOUS_RELEASE"
    restart_app_runtime || true
  fi
  fail "Deploy platform-control thất bại"
fi

log "Deploy platform-control thành công: $RELEASE_DIR"
cleanup_old_releases 5
