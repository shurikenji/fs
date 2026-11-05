"""Check deploy lock wrapper; exercise real contention when flock is available."""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASH = os.environ.get("GIT_BASH") or (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("bash"))
ENTRY = r'''#!/usr/bin/env bash
set -euo pipefail
root="$TEST_ROOT"
if command -v cygpath >/dev/null 2>&1; then root=$(cygpath "$root"); fi
export STACK_ROOT="$root/stack"
export LOCK_TRACE="$root/trace"
if [[ "${USE_FAKE:-}" == 1 ]]; then export PATH="$root/fakebin:$PATH"; fi
source ops/deploy/lib.sh
reexec_with_deploy_lock "$0" "$@"
[[ -z "${SHUPREMIUM_DEPLOY_LOCK_HELD+x}" ]]
printf '%s' "$1" > "$root/result.$TEST_INSTANCE"
if [[ "${HOLD_LOCK:-}" == 1 ]]; then sleep 3; fi
'''
FAKE_FLOCK = r'''#!/usr/bin/env bash
printf '%s\n' "$@" > "$LOCK_TRACE"
shift 5
exec "$@"
'''


if __name__ == "__main__":
    if not BASH:
        raise SystemExit("bash is required")
    with tempfile.TemporaryDirectory(prefix="shupremium-lock-test-") as directory:
        root = Path(directory)
        fakebin = root / "fakebin"
        fakebin.mkdir()
        fake = fakebin / "flock"
        fake.write_text(FAKE_FLOCK, encoding="utf-8", newline="\n")
        fake.chmod(0o755)
        entry = root / "entry.sh"
        entry.write_text(ENTRY, encoding="utf-8", newline="\n")
        env = {**os.environ, "TEST_ROOT": directory, "TEST_INSTANCE": "fake", "USE_FAKE": "1"}
        subprocess.run([BASH, str(entry), "argument with spaces"], cwd=ROOT, env=env, check=True)
        trace = (root / "trace").read_text(encoding="utf-8").splitlines()
        assert trace[:4] == ["--nonblocking", "--conflict-exit-code", "75", "--close"]
        assert (root / "result.fake").read_text(encoding="utf-8") == "argument with spaces"
        guard = root / "stack" / "shared" / "_ops" / "runtime.lock"
        assert not guard.exists()
        guard.mkdir()
        (guard / "owner").write_text("other-operation\n", encoding="utf-8")
        busy_env = {**env, "TEST_INSTANCE": "busy"}
        busy = subprocess.run([BASH, str(entry), "busy"], cwd=ROOT, env=busy_env, capture_output=True, text=True)
        assert busy.returncode != 0 and not (root / "result.busy").exists()
        assert (guard / "owner").read_text(encoding="utf-8") == "other-operation\n"
        (guard / "owner").unlink()
        guard.rmdir()

        node = shutil.which("node")
        if node:
            module = ROOT / "services" / "proxy-gateway" / "proxy-operator" / "src" / "server.js"
            code = "const m=require(process.argv[1]);const g=m.acquireRuntimeGuard('operator',process.argv[2]);console.log('READY');setTimeout(()=>m.releaseRuntimeGuard(g),1500)"
            operator = subprocess.Popen([node, "-e", code, str(module), str(guard)], cwd=ROOT, stdout=subprocess.PIPE, text=True)
            try:
                assert operator.stdout.readline().strip() == "READY"
                cross_env = {**env, "TEST_INSTANCE": "operator_busy"}
                blocked = subprocess.run([BASH, str(entry), "blocked"], cwd=ROOT, env=cross_env, capture_output=True, text=True)
                assert blocked.returncode != 0 and not (root / "result.operator_busy").exists()
                assert operator.wait(timeout=5) == 0
                assert not guard.exists()
            finally:
                if operator.poll() is None:
                    operator.terminate()
                    operator.wait(timeout=5)
                operator.stdout.close()
            held_env = {**env, "TEST_INSTANCE": "deploy_busy", "HOLD_LOCK": "1"}
            deployment = subprocess.Popen([BASH, str(entry), "held"], cwd=ROOT, env=held_env, stdout=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not (root / "result.deploy_busy").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert (root / "result.deploy_busy").exists()
                probe = "const m=require(process.argv[1]);try{m.acquireRuntimeGuard('operator',process.argv[2]);process.exit(0)}catch(e){process.exit(e.step==='busy'?3:4)}"
                operator_try = subprocess.run([node, "-e", probe, str(module), str(guard)], cwd=ROOT, capture_output=True, text=True)
                assert operator_try.returncode == 3
                assert deployment.wait(timeout=6) == 0
                assert not guard.exists()
            finally:
                if deployment.poll() is None:
                    deployment.terminate()
                    deployment.wait(timeout=5)

        if shutil.which("flock"):
            base = {**os.environ, "TEST_ROOT": directory}
            first_env = {**base, "TEST_INSTANCE": "first", "HOLD_LOCK": "1"}
            first = subprocess.Popen([BASH, str(entry), "first"], cwd=ROOT, env=first_env)
            try:
                deadline = time.monotonic() + 5
                while not (root / "result.first").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert (root / "result.first").exists(), "first deployment did not acquire lock"
                second_env = {**base, "TEST_INSTANCE": "second"}
                second = subprocess.run([BASH, str(entry), "second"], cwd=ROOT, env=second_env)
                assert second.returncode == 75
                assert not (root / "result.second").exists()
                assert first.wait(timeout=6) == 0
                assert subprocess.run([BASH, str(entry), "second"], cwd=ROOT, env=second_env).returncode == 0
            finally:
                if first.poll() is None:
                    first.terminate()
                    first.wait(timeout=5)
            print("real flock contention OK")
        else:
            print("real flock unavailable; contention test skipped")
        print("deploy lock wrapper OK")
