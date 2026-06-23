# Shopbot Standby Runbook

Updated: 2026-06-23

Shopbot production is expected to run from:

```text
/srv/shupremium-stack/current/shopbot
/srv/shupremium-stack/shared/shopbot
```

The systemd unit should use:

```ini
WorkingDirectory=/srv/shupremium-stack/current/shopbot
ExecStart=/srv/shupremium-stack/shared/shopbot/venv/bin/python -m bot.main
```

## Backup

Run on the primary Shopbot VPS:

```bash
cd /srv/shupremium-stack/current/shopbot
bash scripts/backup_shopbot.sh
```

Keep these together:

- SQLite DB snapshot from `shared/shopbot/data`
- `/srv/shupremium-stack/shared/shopbot/.env`
- current git commit/release timestamp

Do not commit backups to Git.

## Restore to standby

1. Prepare `/srv/shupremium-stack` layout on the standby host.
2. Set host role:

```bash
echo shopbot | sudo tee /etc/shupremium-host-role
```

3. Restore `.env` and DB snapshot into `/srv/shupremium-stack/shared/shopbot`.
4. Clone or update repo:

```bash
git clone https://github.com/shurikenji/fs.git /srv/shupremium-stack/repo
cd /srv/shupremium-stack/repo
bash ops/deploy/bootstrap-host.sh
bash ops/deploy/deploy-shopbot.sh main
```

If the repo is later moved to private GitHub, replace the clone URL with the new private remote.

5. Start or restart the unit:

```bash
sudo systemctl daemon-reload
sudo systemctl restart shopbot
```

## Verification

```bash
systemctl status shopbot --no-pager
journalctl -u shopbot -n 80 --no-pager
readlink -f /srv/shupremium-stack/current/shopbot
ls -la /srv/shupremium-stack/shared/shopbot
```

Functional checks:

- admin panel starts cleanly
- Telegram polling starts once
- SQLite DB opens without WAL recovery errors
- recent users/orders/wallet balances are visible
- payment poller starts and logs MBBank v3 scanner attempts without old query params
- VietQR renders using `MB_ACCOUNT_NO`, `MB_ACCOUNT_NAME`, and `MB_BANK_ID`

## MBBank v3 restore note

Scanner settings in `.env` should be:

```env
MB_API_URL=https://api.apicanhan.com/transactions/MB
MB_API_KEY=<provider-api-key>
```

Do not restore old scanner URLs containing `?key=`, `username`, `password`, or `accountNo`.

## Public GitHub note

Do not commit standby backups, restored `.env` files, SQLite snapshots, bot logs, or copied payment-provider responses. The repo must stay safe while GitHub is public.
