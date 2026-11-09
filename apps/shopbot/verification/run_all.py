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
    ROOT_DIR / "verification" / "verify_purchase_hardening.py",
    ROOT_DIR / "verification" / "verify_order_admin_actions.py",
    ROOT_DIR / "verification" / "verify_payment_poller.py",
    ROOT_DIR / "verification" / "verify_vietqr.py",
    ROOT_DIR / "verification" / "verify_mbbank.py",
    ROOT_DIR / "verification" / "verify_server_groups.py",
    ROOT_DIR / "verification" / "verify_server_queries.py",
    ROOT_DIR / "verification" / "verify_ai_translator.py",
    ROOT_DIR / "verification" / "verify_admin_entity_states.py",
    ROOT_DIR / "verification" / "verify_token_identity.py",
    ROOT_DIR / "verification" / "verify_control_sync_guard.py",
    ROOT_DIR / "verification" / "verify_control_plane_sync.py",
    ROOT_DIR / "verification" / "verify_vault_guard.py",
    ROOT_DIR / "verification" / "verify_release_preflight.py",
    ROOT_DIR / "verification" / "verify_transaction_ownership.py",
    ROOT_DIR / "verification" / "verify_wallet_isolation.py",
    ROOT_DIR / "verification" / "verify_uncertain_fulfillment.py",
    ROOT_DIR / "verification" / "verify_stock_counts.py",
    ROOT_DIR / "verification" / "verify_stock_reservations.py",
    ROOT_DIR / "verification" / "verify_bank_feed_errors.py",
    ROOT_DIR / "verification" / "verify_financial_migration.py",
    ROOT_DIR / "verification" / "verify_payment_receipts.py",
    ROOT_DIR / "verification" / "verify_fulfillment_queue.py",
    ROOT_DIR / "verification" / "verify_notification_worker.py",
    ROOT_DIR / "verification" / "verify_fulfillment_end_to_end.py",
    ROOT_DIR / "verification" / "verify_manual_topup.py",
    ROOT_DIR / "verification" / "verify_worker_lifecycle.py",
    ROOT_DIR / "verification" / "verify_reconciliation_page.py",
    ROOT_DIR / "verification" / "verify_admin_passwords.py",
    ROOT_DIR / "verification" / "verify_admin_csrf.py",
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
