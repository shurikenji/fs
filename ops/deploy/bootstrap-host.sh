#!/usr/bin/env bash

set -euo pipefail

STACK_ROOT="${STACK_ROOT:-/srv/shupremium-stack}"

mkdir -p "$STACK_ROOT/repo"
mkdir -p "$STACK_ROOT/releases"
mkdir -p "$STACK_ROOT/current"
mkdir -p "$STACK_ROOT/shared/portal/data"
mkdir -p "$STACK_ROOT/shared/platform-control/data"
mkdir -p "$STACK_ROOT/shared/shopbot/data"
mkdir -p "$STACK_ROOT/shared/proxy-gateway/proxy-operator"
mkdir -p "$STACK_ROOT/shared/proxy-gateway/admin-panel/data"

echo "Bootstrap xong tại $STACK_ROOT"
echo "Tiếp theo:"
echo "1. Clone repo vào $STACK_ROOT/repo"
echo "2. Chép .env, data, venv vào $STACK_ROOT/shared/<app>"
echo "3. Tạo /etc/shupremium-host-role = arm hoặc shopbot"

