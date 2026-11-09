#!/usr/bin/env bash
# Host-role-aware health verification for active apps.
# Usage: bash ops/scripts/verify-all-health.sh [host-role]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/../deploy" && pwd)"

# shellcheck source=../deploy/lib.sh
source "$DEPLOY_DIR/lib.sh"
# shellcheck source=../deploy/app-manifest.sh
source "$MANIFEST_FILE"

HOST_ROLE_VALUE="$(resolve_host_role "${1:-}")"
case "$HOST_ROLE_VALUE" in
  arm) EXPECTED_COUNT=3 ;;
  shopbot) EXPECTED_COUNT=1 ;;
  combined) EXPECTED_COUNT=5 ;;
  *) echo "Unsupported host role: $HOST_ROLE_VALUE" >&2; exit 1 ;;
esac
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0

print_result() {
  local status="$1"
  local label="$2"
  local message="$3"

  case "$status" in
    ok)
      PASS_COUNT=$((PASS_COUNT + 1))
      printf "${GREEN}[OK]${NC} %s - %s\n" "$label" "$message"
      ;;
    fail)
      FAIL_COUNT=$((FAIL_COUNT + 1))
      printf "${RED}[FAIL]${NC} %s - %s\n" "$label" "$message"
      ;;
    skip)
      printf "${YELLOW}[SKIP]${NC} %s - %s\n" "$label" "$message"
      ;;
  esac
}

run_app_health_check() {
  local app="$1"
  local output

  load_app_config "$app"
  if [[ "$HOST_ROLE_VALUE" != "combined" && "$HOST_ROLE" != "$HOST_ROLE_VALUE" ]]; then
    return 0
  fi

  if [[ ! -L "$CURRENT_DIR/$APP_ID" ]]; then
    print_result fail "$APP_ID" "Missing current release symlink at $CURRENT_DIR/$APP_ID"
    return 1
  fi

  if output="$(
    run_runtime_smoke_checks
    if [[ "$HOST_ROLE_VALUE" == "combined" && "$APP_ID" == "shopbot" ]]; then
      SMOKE_URLS='http://127.0.0.1:8092/health|200' run_http_smoke_checks
    fi
  )" 2>&1; then
    print_result ok "$APP_ID" "Healthy"
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output"
    fi
    return 0
  fi

  print_result fail "$APP_ID" "Health verification failed"
  if [[ -n "$output" ]]; then
    printf '%s\n' "$output"
  fi
  return 1
}

echo "Host role: $HOST_ROLE_VALUE"
echo ""

while IFS= read -r app; do
  [[ -n "$app" ]] || continue
  run_app_health_check "$app" || true
  echo ""
done < <(list_manifest_apps)

if [[ $((PASS_COUNT + FAIL_COUNT)) -ne "$EXPECTED_COUNT" ]]; then
  print_result fail "health-verifier" "Expected $EXPECTED_COUNT app checks; manifest may be incomplete"
fi

echo "Summary: $PASS_COUNT passed, $FAIL_COUNT failed"

if [[ "$FAIL_COUNT" -gt 0 || "$PASS_COUNT" -eq 0 ]]; then
  exit 1
fi
