#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
source "$SCRIPT_DIR/lib.sh"

REF="${1:-main}"
HOST_ROLE_VALUE="$(resolve_host_role "${2:-}")"

load_app_config shopbot
ensure_host_role "$HOST_ROLE_VALUE"
prepare_stack_dirs

RESOLVED_REF="$(fetch_ref "$REF")"
TS="$(date '+%Y%m%d-%H%M%S')"
RELEASE_DIR="$(create_release_dir "$TS")"
PREVIOUS_RELEASE="$(current_target || true)"
set_deploy_context "$HOST_ROLE_VALUE" "$RESOLVED_REF" "$RELEASE_DIR" "$PREVIOUS_RELEASE"

log "Deploy shopbot from ref $RESOLVED_REF"
deploy_release "$RELEASE_DIR" "$PREVIOUS_RELEASE" prepare_python_release
log "Deploy shopbot succeeded: $RELEASE_DIR"
cleanup_old_releases 5
