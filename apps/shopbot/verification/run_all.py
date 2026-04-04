"""Run all tracked verification scripts in a fixed order."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = [
    ROOT_DIR / "verification" / "verify_phase3_active_handlers.py",
    ROOT_DIR / "verification" / "verify_phase4_admin.py",
    ROOT_DIR / "verification" / "verify_phase5_orders_payments.py",
    ROOT_DIR / "verification" / "verify_order_admin_actions.py",
    ROOT_DIR / "verification" / "verify_payment_poller.py",
    ROOT_DIR / "verification" / "verify_server_groups.py",
    ROOT_DIR / "verification" / "verify_server_queries.py",
    ROOT_DIR / "verification" / "verify_ai_translator.py",
    ROOT_DIR / "verification" / "verify_admin_entity_states.py",
]


def main() -> int:
    for script in SCRIPTS:
        print(f"\n=== RUNNING {script.name} ===")
        result = subprocess.run([sys.executable, str(script)], cwd=ROOT_DIR)
        if result.returncode != 0:
            print(f"\n[FAIL] {script.name} exited with code {result.returncode}")
            return result.returncode

    print("\n=== ALL TRACKED VERIFICATION PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
