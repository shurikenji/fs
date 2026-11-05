"""Check release venv isolation and systemd preflight without starting services."""
import os
import importlib.util
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASH = os.environ.get("GIT_BASH") or (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("bash"))

SCRIPT = r'''
set -euo pipefail
source ops/deploy/lib.sh
root="$TEST_ROOT"
if command -v cygpath >/dev/null 2>&1; then root=$(cygpath "$root"); fi
SHARED_DIR="$root/shared"
CURRENT_DIR=/srv/shupremium-stack/current
APP_ID=shopbot
SHARED_NAME=shopbot
SYSTEMD_UNIT=shopbot
PYTHON_REQUIREMENTS=requirements.txt
mkdir -p "$SHARED_DIR/shopbot/venv" "$root/release"
printf untouched > "$SHARED_DIR/shopbot/venv/sentinel"
printf env > "$SHARED_DIR/shopbot/.env"
printf test > "$root/release/requirements.txt"
link_shared_file() { :; }
link_shared_dir() { :; }
curl() { :; }
python3() {
  [[ "$1" == -m && "$2" == venv ]]
  mkdir -p "$3/bin"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$3/bin/pip"
  chmod +x "$3/bin/pip"
}
prepare_python_release "$root/release"
[[ -x "$root/release/.venv/bin/pip" && ! -L "$root/release/.venv" ]]
[[ "$(cat "$SHARED_DIR/shopbot/venv/sentinel")" == untouched ]]
APP_ID=proxy-gateway
SHARED_NAME=proxy-gateway
mkdir -p "$root/proxy-release/proxy-operator" "$root/proxy-release/proxy-service"
link_shared_file() { printf 'file:%s\n' "$1" >> "$root/links"; }
link_shared_dir() { printf 'dir:%s\n' "$1" >> "$root/links"; }
npm() { :; }
prepare_proxy_gateway_release "$root/proxy-release"
links="$(cat "$root/links")"
[[ "$links" == *"file:$SHARED_DIR/proxy-gateway/proxy-service/ecosystem.config.js"* ]]
[[ "$links" == *"dir:$SHARED_DIR/proxy-gateway/proxy-service/logs"* ]]
APP_ID=shopbot
SHARED_NAME=shopbot
systemctl() {
  case "$3" in
    --property=ExecStart) printf '%s\n' "{ path=$CURRENT_DIR/$APP_ID/.venv/bin/python ; argv[]=python -m bot.main ; }" ;;
    --property=WorkingDirectory) printf '%s\n' "$CURRENT_DIR/$APP_ID" ;;
    *) return 1 ;;
  esac
}
verify_shopbot_unit
systemctl() { printf '%s\n' '{ path=/old/shared/venv/bin/python ; }'; }
if (verify_shopbot_unit >/dev/null 2>&1); then exit 1; fi
load_app_config key-vault-worker
ensure_host_role combined
if (ensure_host_role arm >/dev/null 2>&1); then exit 1; fi
systemctl() {
  case "$3" in
    --property=ExecStart) printf '%s\n' "{ path=$CURRENT_DIR/$APP_ID/.venv/bin/uvicorn ; argv[]=uvicorn main:app --host 127.0.0.1 --port 8093 ; }" ;;
    --property=WorkingDirectory) printf '%s\n' "$CURRENT_DIR/$APP_ID" ;;
    *) return 1 ;;
  esac
}
verify_vault_unit
systemctl() {
  case "$3" in
    --property=ExecStart) printf '%s\n' "{ path=$CURRENT_DIR/$APP_ID/.venv/bin/uvicorn ; argv[]=uvicorn main:app --host 0.0.0.0 --port 8093 ; }" ;;
    --property=WorkingDirectory) printf '%s\n' "$CURRENT_DIR/$APP_ID" ;;
  esac
}
if (verify_vault_unit >/dev/null 2>&1); then exit 1; fi
systemctl() { printf '%s\n' '{ path=/old/shared/venv/bin/uvicorn ; }'; }
if (verify_vault_unit >/dev/null 2>&1); then exit 1; fi
for app in portal platform-control proxy-gateway; do
  load_app_config "$app"
  ensure_host_role arm
  ensure_host_role combined
  if (ensure_host_role shopbot >/dev/null 2>&1); then exit 1; fi
done
load_app_config shopbot
ensure_host_role shopbot
ensure_host_role combined
if (ensure_host_role arm >/dev/null 2>&1); then exit 1; fi
APP_ID=portal
PM2_ENTRY=main.py
PROCESS_NAME=portal
pm2_process_exists() { return 1; }
pm2() { printf '%s\n' "$@"; }
output="$(restart_pm2_python_app)"
[[ "$output" == *"/srv/shupremium-stack/current/portal/.venv/bin/python"* ]]
printf 'release isolation and unit guards OK\n'
'''


if __name__ == "__main__":
    if not BASH:
        raise SystemExit("bash is required")
    with tempfile.TemporaryDirectory(prefix="shupremium-release-test-") as directory:
        env = {**os.environ, "TEST_ROOT": directory}
        subprocess.run([BASH, "-s"], input=SCRIPT, text=True, cwd=ROOT, env=env, check=True)
        module_path = ROOT / "ops" / "deploy" / "check_service_database.py"
        spec = importlib.util.spec_from_file_location("check_service_database", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.check_combined_bind("portal", "127.0.0.1", 8080, "combined")
        module.check_combined_bind("platform-control", "127.0.0.1", 8090, "combined")
        for app, host, port in (("portal", "0.0.0.0", 8080), ("platform-control", "127.0.0.1", 8080)):
            try:
                module.check_combined_bind(app, host, port, "combined")
                raise AssertionError("invalid combined bind accepted")
            except ValueError:
                pass
        data_root = Path(directory) / "data"
        data_root.mkdir()
        db_path = data_root / "portal.db"
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute("CREATE TABLE servers (id TEXT)")
        try:
            module.check_database("portal", str(db_path), str(data_root))
            raise AssertionError("incomplete schema accepted")
        except ValueError:
            pass
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute("CREATE TABLE app_settings (key TEXT)")
        before = db_path.read_bytes()
        module.check_database("portal", str(db_path), str(data_root))
        assert db_path.read_bytes() == before
        try:
            module.check_database("portal", "relative.db", str(data_root))
            raise AssertionError("relative path accepted")
        except ValueError:
            pass
        print("shared database preflight OK")
