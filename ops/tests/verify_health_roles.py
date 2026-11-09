"""Ensure health checks cannot report success when required apps are absent."""
import os
import shutil
import subprocess
import tempfile


BASH = os.environ.get("GIT_BASH") or (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("bash"))
SCRIPT = r'''
root="$TEST_ROOT"
if command -v cygpath >/dev/null 2>&1; then root=$(cygpath "$root"); fi
STACK_ROOT="$root" bash ops/scripts/verify-all-health.sh "$TEST_ROLE"
'''


if __name__ == "__main__":
    if not BASH:
        raise SystemExit("bash is required")
    with tempfile.TemporaryDirectory(prefix="shupremium-health-test-") as directory:
        for role, expected in (("arm", 3), ("shopbot", 1), ("combined", 5)):
            env = {**os.environ, "TEST_ROOT": directory, "TEST_ROLE": role}
            result = subprocess.run([BASH, "-s"], input=SCRIPT, text=True, env=env, capture_output=True)
            assert result.returncode != 0, role
            assert f"Summary: 0 passed, {expected} failed" in result.stdout, result.stdout
        env = {**os.environ, "TEST_ROOT": directory, "TEST_ROLE": "invalid"}
        result = subprocess.run([BASH, "-s"], input=SCRIPT, text=True, env=env, capture_output=True)
        assert result.returncode != 0 and "Unsupported host role" in result.stderr
    print("health role guards OK")
