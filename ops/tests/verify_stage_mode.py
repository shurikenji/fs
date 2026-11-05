"""Verify staging uses a commit and does not touch live runtime state."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASH = os.environ.get("GIT_BASH") or (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("bash"))
GIT = shutil.which("git")

FAKE_PYTHON = r'''#!/usr/bin/env bash
set -euo pipefail
[[ -z "${SHUPREMIUM_TEST_SECRET+x}" ]] || exit 91
[[ "$1" == -m && "$2" == venv ]]
mkdir -p "$3/bin"
cat > "$3/bin/python" <<'FAKE'
#!/usr/bin/env bash
[[ -z "${SHUPREMIUM_TEST_SECRET+x}" ]]
FAKE
cp "$3/bin/python" "$3/bin/pip"
chmod +x "$3/bin/python" "$3/bin/pip"
'''

RUN = r'''set -euo pipefail
root="$TEST_ROOT"
if command -v cygpath >/dev/null 2>&1; then root=$(cygpath "$root"); fi
export STACK_ROOT="$root/stack"
export REPO_DIR="$root/repo"
export PATH="$root/fakebin:$PATH"
export SHUPREMIUM_TEST_SECRET=must-not-reach-staged-build
bash ops/deploy/deploy-portal.sh --stage-only HEAD
bash ops/deploy/deploy-platform-control.sh --stage-only HEAD
bash ops/deploy/deploy-shopbot.sh --stage-only HEAD
bash ops/deploy/deploy-proxy-gateway.sh --stage-only HEAD
bash ops/deploy/deploy-key-vault-worker.sh --stage-only HEAD
'''


if __name__ == "__main__":
    if not BASH or not GIT:
        raise SystemExit("bash and git are required")
    with tempfile.TemporaryDirectory(prefix="shupremium-stage-test-") as directory:
        root = Path(directory)
        repo = root / "repo"
        repo.mkdir()
        subprocess.run([GIT, "init", "-q", str(repo)], check=True)
        subprocess.run([GIT, "-C", str(repo), "config", "user.name", "Stage Test"], check=True)
        subprocess.run([GIT, "-C", str(repo), "config", "user.email", "stage-test@example.invalid"], check=True)
        for app in ("portal", "platform-control", "shopbot", "key-vault-worker"):
            app_dir = repo / "apps" / app
            app_dir.mkdir(parents=True)
            (app_dir / "requirements.txt").write_text("", encoding="utf-8")
            (app_dir / "placeholder.py").write_text("pass\n", encoding="utf-8")
        for part, entry in (("proxy-operator", "server.js"), ("proxy-service", "index.js")):
            part_dir = repo / "services" / "proxy-gateway" / part
            (part_dir / "src").mkdir(parents=True)
            (part_dir / "package-lock.json").write_text("{}", encoding="utf-8")
            (part_dir / "src" / entry).write_text("", encoding="utf-8")
        subprocess.run([GIT, "-C", str(repo), "add", "apps", "services"], check=True)
        subprocess.run([GIT, "-C", str(repo), "commit", "-qm", "fixture"], check=True)
        (repo / "apps" / "portal" / "requirements.txt").write_text("uncommitted-change", encoding="utf-8")
        fakebin = root / "fakebin"
        fakebin.mkdir()
        fake_python = fakebin / "python3"
        fake_python.write_text(FAKE_PYTHON, encoding="utf-8", newline="\n")
        fake_python.chmod(0o755)
        for name in ("npm", "node"):
            command = fakebin / name
            command.write_text("#!/usr/bin/env bash\n[[ -z \"${SHUPREMIUM_TEST_SECRET+x}\" ]]\n", encoding="utf-8", newline="\n")
            command.chmod(0o755)
        for name in ("pm2", "systemctl", "sudo"):
            command = fakebin / name
            command.write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8", newline="\n")
            command.chmod(0o755)
        shared = root / "stack" / "shared" / "portal"
        shared.mkdir(parents=True)
        sentinel = shared / ".env"
        sentinel.write_text("unchanged", encoding="utf-8")
        current = root / "stack" / "current" / "portal"
        current.mkdir(parents=True)
        (current / "sentinel").write_text("running", encoding="utf-8")
        subprocess.run([BASH, "-s"], input=RUN, text=True, cwd=ROOT, env={**os.environ, "TEST_ROOT": directory}, check=True)
        assert sentinel.read_text(encoding="utf-8") == "unchanged"
        assert (current / "sentinel").read_text(encoding="utf-8") == "running"
        stages = list((root / "stack" / "staging").iterdir())
        assert len(stages) == 5
        python_stages = [stage for stage in stages if not stage.name.startswith("proxy-gateway.")]
        assert all((stage / "release" / ".venv" / "bin" / "python").exists() for stage in python_stages)
        assert all(not (stage / "release" / ".env").exists() for stage in stages)
        portal_stage = next(stage for stage in stages if stage.name.startswith("portal."))
        assert (portal_stage / "release" / "requirements.txt").read_text(encoding="utf-8") == ""
        (repo / "apps" / "portal" / ".env").write_text("TEST_ONLY=1\n", encoding="utf-8")
        subprocess.run([GIT, "-C", str(repo), "add", "-f", "apps/portal/.env"], check=True)
        subprocess.run([GIT, "-C", str(repo), "commit", "-qm", "fixture with env"], check=True)
        failed = subprocess.run([BASH, "-s"], input="\n".join(RUN.splitlines()[:8]), text=True, cwd=ROOT,
                                env={**os.environ, "TEST_ROOT": directory}, capture_output=True)
        assert failed.returncode != 0 and "Committed .env is not allowed" in failed.stdout
        assert sentinel.read_text(encoding="utf-8") == "unchanged"
        print("staging isolation OK")
