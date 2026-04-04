# Shopbot Standby Runbook

## Backup
- Run `scripts/backup_shopbot.sh` on the primary node.
- Upload the created backup directory to object storage or the standby host.
- Keep `.env` and the database snapshot together.

## Restore
- Stop the running `shopbot` process on the standby host.
- Restore the last consistent snapshot with `scripts/restore_shopbot.sh <backup_dir>`.
- Ensure `.env` on the standby host matches production secrets and ports.
- Start the service and verify `/health`, admin login, and Telegram polling.

## Verification
- Check database opens without WAL recovery errors.
- Confirm a recent user, order count, and wallet balance through the internal portal API.
- Confirm payment poller and admin panel start cleanly.
