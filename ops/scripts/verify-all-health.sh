#!/usr/bin/env bash
# Quick health check for all services on ARM VPS
# Usage: bash ops/scripts/verify-all-health.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

check() {
  local name="$1" url="$2"
  local status
  status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo "FAIL")"
  if [[ "$status" == "200" ]]; then
    printf "${GREEN}✓${NC} %-25s %s -> %s\n" "$name" "$url" "$status"
  else
    printf "${RED}✗${NC} %-25s %s -> %s\n" "$name" "$url" "$status"
  fi
}

echo "=== App Health ==="
check "portal"            "http://127.0.0.1:8080/health"
check "platform-control"  "http://127.0.0.1:8090/"

echo ""
echo "=== Proxy Operator ==="
check "proxy-operator"    "http://127.0.0.1:8091/health"

echo ""
echo "=== Proxy Services ==="
for port in 3001 3002 3003 3004 3005 4001 4002; do
  check "proxy :$port" "http://127.0.0.1:${port}/_internal/health"
done

echo ""
echo "=== PM2 Summary ==="
pm2 ls 2>/dev/null | grep -E "online|stopped|errored" || echo "(pm2 not available)"
