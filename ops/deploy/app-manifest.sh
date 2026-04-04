#!/usr/bin/env bash

app_manifest() {
  local app="${1:-}"

  APP_ID=""
  HOST_ROLE=""
  SOURCE_PATH=""
  SOURCE_STRIP_COMPONENTS=""
  SHARED_NAME=""
  RUNTIME_KIND=""
  PROCESS_NAME=""
  SYSTEMD_UNIT=""
  PM2_ENTRY=""
  PM2_INTERPRETER=""
  PYTHON_REQUIREMENTS=""
  SMOKE_URLS=""
  OPTIONAL_PM2_APPS=""

  case "$app" in
    portal)
      APP_ID="portal"
      HOST_ROLE="arm"
      SOURCE_PATH="apps/portal"
      SOURCE_STRIP_COMPONENTS="2"
      SHARED_NAME="portal"
      RUNTIME_KIND="pm2-python"
      PROCESS_NAME="portal"
      PM2_ENTRY="main.py"
      PM2_INTERPRETER="python"
      PYTHON_REQUIREMENTS="requirements.txt"
      SMOKE_URLS=$'http://127.0.0.1:8080/health|200\nhttp://127.0.0.1:8080/|200\nhttp://127.0.0.1:8080/pricing|200'
      ;;
    platform-control)
      APP_ID="platform-control"
      HOST_ROLE="arm"
      SOURCE_PATH="apps/platform-control"
      SOURCE_STRIP_COMPONENTS="2"
      SHARED_NAME="platform-control"
      RUNTIME_KIND="pm2-python"
      PROCESS_NAME="platform-control"
      PM2_ENTRY="main.py"
      PM2_INTERPRETER="python"
      PYTHON_REQUIREMENTS="requirements.txt"
      SMOKE_URLS=$'http://127.0.0.1:8090/|200,302'
      ;;
    shopbot)
      APP_ID="shopbot"
      HOST_ROLE="shopbot"
      SOURCE_PATH="apps/shopbot"
      SOURCE_STRIP_COMPONENTS="2"
      SHARED_NAME="shopbot"
      RUNTIME_KIND="systemd-python"
      SYSTEMD_UNIT="shopbot"
      PYTHON_REQUIREMENTS="requirements.txt"
      ;;
    proxy-gateway)
      APP_ID="proxy-gateway"
      HOST_ROLE="arm"
      SOURCE_PATH="services/proxy-gateway"
      SOURCE_STRIP_COMPONENTS="2"
      SHARED_NAME="proxy-gateway"
      RUNTIME_KIND="pm2-node-multi"
      PROCESS_NAME="proxy-operator"
      OPTIONAL_PM2_APPS="admin-panel"
      ;;
    balance-checker)
      APP_ID="balance-checker"
      HOST_ROLE="arm"
      SOURCE_PATH="services/balance-checker"
      SOURCE_STRIP_COMPONENTS="2"
      SHARED_NAME="balance-checker"
      RUNTIME_KIND="manual"
      ;;
    *)
      return 1
      ;;
  esac

  export APP_ID HOST_ROLE SOURCE_PATH SOURCE_STRIP_COMPONENTS SHARED_NAME
  export RUNTIME_KIND PROCESS_NAME SYSTEMD_UNIT PM2_ENTRY PM2_INTERPRETER
  export PYTHON_REQUIREMENTS SMOKE_URLS OPTIONAL_PM2_APPS
}

