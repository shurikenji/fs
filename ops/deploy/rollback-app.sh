#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
source "$SCRIPT_DIR/lib.sh"

APP="${1:-}"
TARGET_RELEASE="${2:-}"
HOST_ROLE_VALUE="$(resolve_host_role "${3:-}")"

[[ -n "$APP" ]] || fail "Usage: rollback-app.sh <app> [release-dir] [host-role]"

load_app_config "$APP"
ensure_host_role "$HOST_ROLE_VALUE"
prepare_stack_dirs

PREVIOUS_RELEASE="$(current_target || true)"
[[ -n "$PREVIOUS_RELEASE" ]] || fail "App $APP does not have a current release"
PREVIOUS_RELEASE="$(validate_release_dir "$PREVIOUS_RELEASE")"

if [[ -z "$TARGET_RELEASE" ]]; then
  mapfile -t releases < <(find "$RELEASES_DIR" -mindepth 2 -maxdepth 2 -type d -name "$APP" | sort -r)
  for candidate in "${releases[@]}"; do
    candidate="$(validate_release_dir "$candidate")"
    if [[ "$candidate" != "$PREVIOUS_RELEASE" ]]; then
      TARGET_RELEASE="$candidate"
      break
    fi
  done
fi

[[ -n "$TARGET_RELEASE" ]] || fail "Could not find a rollback release for $APP"
TARGET_RELEASE="$(validate_release_dir "$TARGET_RELEASE")"
[[ "$TARGET_RELEASE" != "$PREVIOUS_RELEASE" ]] || fail "Target release is already current for $APP"

set_deploy_context "$HOST_ROLE_VALUE" "manual-rollback" "$TARGET_RELEASE" "$PREVIOUS_RELEASE"

log "Rollback $APP -> $TARGET_RELEASE"
if ! rollback_to_release "$TARGET_RELEASE" "Manual rollback requested"; then
  if [[ -n "$PREVIOUS_RELEASE" ]]; then
    log "Rollback target failed, restoring previous release: $PREVIOUS_RELEASE"
    rollback_to_release "$PREVIOUS_RELEASE" "Rollback target failed; restoring previous release" || true
  fi
  fail "Rollback failed for $APP"
fi

log "Rollback succeeded"
