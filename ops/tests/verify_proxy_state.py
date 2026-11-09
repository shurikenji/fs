"""Exercise safe, non-overwriting migration of generated PM2 state."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "deploy" / "prepare-proxy-state.js"
NODE = shutil.which("node")


if __name__ == "__main__":
    if not NODE:
        raise SystemExit("node is required")
    with tempfile.TemporaryDirectory(prefix="shupremium-proxy-state-test-") as directory:
        root = Path(directory)
        shared = root / "shared" / "proxy-gateway" / "proxy-service"
        shared.mkdir(parents=True)
        source = root / "source.config.js"
        apps = [{"name": "proxy-one", "script": "./src/index.js", "env": {"PORT": 4001, "TARGET_HOST": "example.test"}}]
        original = "// fixture\nmodule.exports = { apps: " + json.dumps(apps) + " };\n"
        source.write_text(original, encoding="utf-8")
        subprocess.run([NODE, str(SCRIPT), str(source), str(root)], check=True)
        destination = shared / "ecosystem.config.js"
        output = destination.read_text(encoding="utf-8")
        payload = json.loads(output.split("module.exports = ", 1)[1].rsplit(";", 1)[0])
        expected = [{**apps[0], "env": {**apps[0]["env"], "PROXY_BIND_HOST": "127.0.0.1"}, "cwd": str(root / "current" / "proxy-gateway" / "proxy-service")}]
        assert payload["apps"] == expected
        assert source.read_text(encoding="utf-8") == original
        second = subprocess.run([NODE, str(SCRIPT), str(source), str(root)], capture_output=True, text=True)
        assert second.returncode != 0 and destination.read_text(encoding="utf-8") == output
        malicious_root = root / "other"
        (malicious_root / "shared" / "proxy-gateway" / "proxy-service").mkdir(parents=True)
        source.write_text("module.exports = (() => { throw Error('must not execute') })();", encoding="utf-8")
        failed = subprocess.run([NODE, str(SCRIPT), str(source), str(malicious_root)], capture_output=True, text=True)
        assert failed.returncode != 0 and "must not execute" not in failed.stderr
        assert not (malicious_root / "shared" / "proxy-gateway" / "proxy-service" / "ecosystem.config.js").exists()
    print("proxy state migration OK")
