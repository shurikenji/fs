# Deployment Guide

Updated: 2026-11-11

This is the current deploy guide for `shupremium-stack`. The production contract is:

- Git is source of truth.
- Deploy is per app and per host role.
- Runtime state stays outside releases.
- Rollback is symlink-based.
- Manual folder copy/scp deploy is not the normal path.
- Repository content must always be safe to expose; never commit runtime secrets or copied production data.

## Current production host and roles

Production is consolidated onto **one VPS**, confirmed by the operator on 2026-11-11. All five apps run on that host with separate processes, releases, environments and databases.

| Production host | Expected role file | Apps |
| --- | --- | --- |
| Single shared VPS | `/etc/shupremium-host-role = combined` | `portal`, `platform-control`, `shopbot`, `proxy-gateway`, `key-vault-worker` |

The manifest keeps `arm` and `shopbot` as per-app compatibility roles. `ensure_host_role` accepts those apps on `combined`; `verify-all-health.sh combined` checks all five apps. These names are not evidence of separate production machines.

Check the role file on the VPS:

```bash
cat /etc/shupremium-host-role
```

The expected value is `combined`. For a newly bootstrapped single-VPS host, initialize it once:

```bash
echo combined | sudo tee /etc/shupremium-host-role
```

This documentation correction uses operator-confirmed placement and the repository scripts; it does not claim that the live role file, processes, DNS or ports were inspected. Do not change a live role file merely to suppress an unexplained deploy error.

## Shared VPS baseline

Recommended baseline for the single VPS:

- Ubuntu with `python3`, `python3-venv`, git, curl, tar, nginx, and systemd; use packages matching the VPS architecture.
- Node.js 20+, npm, and PM2 for `proxy-gateway`.
- Provider firewall/security groups and the OS firewall should expose only the public ingress that is actually required, normally SSH plus HTTP/HTTPS.

Do not expose internal app ports publicly:

| Port | Owner | Exposure |
| --- | --- | --- |
| `8080` | `portal` | localhost/nginx only |
| `8090` | `platform-control` | localhost/nginx only |
| `8091` | `proxy-operator` | localhost/internal admin only |
| `8092` | Shopbot admin | localhost/nginx only |
| `8093` | `key-vault-worker` | localhost/internal API only |
| proxy service ports | generated `proxy-service` processes | localhost/nginx only |

Example UFW sequence when UFW is the host firewall:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

PM2 persistence after processes are healthy:

```bash
pm2 startup systemd -u ubuntu --hp /home/ubuntu
# Run the sudo command printed by PM2, then:
pm2 save
sudo systemctl enable pm2-ubuntu
```

Static PM2 ecosystem files are not part of the deploy contract. The deploy scripts restart the active PM2 apps directly, and `proxy-operator` generates proxy-service PM2 runtime configuration when needed.

Cloud/provider firewall rules are separate from the host firewall. Check both layers before diagnosing an ingress failure.

## Canonical layout

```text
/srv/shupremium-stack/
  repo/
    .git/
    apps/
    services/
    ops/
  releases/
    <timestamp>/
      portal/
      platform-control/
      proxy-gateway/
      shopbot/
      key-vault-worker/
  current/
    portal -> /srv/shupremium-stack/releases/<timestamp>/portal
    platform-control -> /srv/shupremium-stack/releases/<timestamp>/platform-control
    proxy-gateway -> /srv/shupremium-stack/releases/<timestamp>/proxy-gateway
    shopbot -> /srv/shupremium-stack/releases/<timestamp>/shopbot
    key-vault-worker -> /srv/shupremium-stack/releases/<timestamp>/key-vault-worker
  shared/
    portal/
      .env
      data/
    platform-control/
      .env
      data/
    shopbot/
      .env
      data/
    key-vault-worker/
      .env
      data/
    proxy-gateway/
      proxy-operator/
        .env
    _ops/
      deploy-audit.jsonl
```

Do not store `.env`, DB files, runtime data, virtualenvs, or `node_modules` in `repo/` or in Git.

## Bootstrap a VPS

```bash
sudo mkdir -p /srv/shupremium-stack
sudo chown -R "$USER:$USER" /srv/shupremium-stack
git clone https://github.com/shurikenji/fs.git /srv/shupremium-stack/repo
cd /srv/shupremium-stack/repo
bash ops/deploy/bootstrap-host.sh
```

Bootstrap creates the top-level deploy directories. It does not invent production secrets.
If the Git remote changes, use the current canonical remote rather than copying an old URL from this document.

For a replacement single-VPS host, set the role before first deploy:

```bash
echo combined | sudo tee /etc/shupremium-host-role
```

Keep the current production host serving traffic until the replacement passes local and DNS-resolved checks.

## Shared runtime preparation

Prepare the matching shared directory before the first deploy.

### Portal

```bash
mkdir -p /srv/shupremium-stack/shared/portal/data
cp /path/to/known-good-portal.env /srv/shupremium-stack/shared/portal/.env
cp -a /path/to/known-good-portal-data/. /srv/shupremium-stack/shared/portal/data/
```

### Platform Control

```bash
mkdir -p /srv/shupremium-stack/shared/platform-control/data
cp /path/to/known-good-platform-control.env /srv/shupremium-stack/shared/platform-control/.env
cp -a /path/to/known-good-platform-control-data/. /srv/shupremium-stack/shared/platform-control/data/
```

### Shopbot

Shopbot release preparation requires Node.js 20+ and npm for the VietQR helper in addition to Python dependencies.

```bash
sudo apt-get update
sudo apt-get install -y libcairo2 python3-dev libffi-dev
mkdir -p /srv/shupremium-stack/shared/shopbot/data
cp /path/to/known-good-shopbot.env /srv/shupremium-stack/shared/shopbot/.env
cp -a /path/to/known-good-shopbot-data/. /srv/shupremium-stack/shared/shopbot/data/
```

Shopbot production unit should point to the current symlink:

```ini
WorkingDirectory=/srv/shupremium-stack/current/shopbot
ExecStart=/srv/shupremium-stack/current/shopbot/.venv/bin/python -m bot.main
```

### Key Vault Worker

```bash
mkdir -p /srv/shupremium-stack/shared/key-vault-worker/data
cp /path/to/known-good-key-vault-worker.env /srv/shupremium-stack/shared/key-vault-worker/.env
```

Initialize the vault DB explicitly before the first deploy, using the app's `scripts/initialize_vault.py` workflow and a valid `KEY_VAULT_MASTER_KEY`. The systemd unit must run the release-local uvicorn and bind localhost only:

```ini
WorkingDirectory=/srv/shupremium-stack/current/key-vault-worker
EnvironmentFile=/srv/shupremium-stack/shared/key-vault-worker/.env
ExecStart=/srv/shupremium-stack/current/key-vault-worker/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8093
```

### Proxy Gateway

```bash
mkdir -p /srv/shupremium-stack/shared/proxy-gateway/proxy-operator
cp /path/to/known-good-proxy-operator.env /srv/shupremium-stack/shared/proxy-gateway/proxy-operator/.env
```

Node dependencies are installed inside releases during deploy; do not copy `node_modules` into Git.

## DNS and TLS for a replacement VPS

Wildcard certificate is expected at:

```text
/etc/letsencrypt/live/shupremium-wildcard/fullchain.pem
/etc/letsencrypt/live/shupremium-wildcard/privkey.pem
```

Cloudflare credentials should live outside the repo, for example:

```text
/home/ubuntu/.secrets/cloudflare.ini
```

Example wildcard issue command:

```bash
sudo certbot certonly --dns-cloudflare \
  --dns-cloudflare-credentials /home/ubuntu/.secrets/cloudflare.ini \
  -d shupremium.com -d '*.shupremium.com' \
  --cert-name shupremium-wildcard \
  --non-interactive --agree-tos -m admin@shupremium.com
```

Do not switch DNS to a replacement VPS IP until that host passes local checks. Before cutover, test public hostnames against the target IP:

```bash
TARGET_VPS_IP=<target-ip>
curl --resolve shupremium.com:443:$TARGET_VPS_IP -I https://shupremium.com/
curl --resolve admin.shupremium.com:443:$TARGET_VPS_IP -I https://admin.shupremium.com/
curl --resolve gpt1.shupremium.com:443:$TARGET_VPS_IP -I https://gpt1.shupremium.com/
```

## Deploy commands on the single VPS

Use the same SSH session and checkout for every app. Run only the deploy scripts for apps changed by the release. For the Shopbot pricing ownership change, update **Shopbot first**, then Platform Control:

```bash
set -e
cd /srv/shupremium-stack/repo
git pull --ff-only origin main
bash ops/deploy/deploy-shopbot.sh 9012994 combined
bash ops/deploy/deploy-platform-control.sh 9012994 combined
bash ops/scripts/verify-all-health.sh combined
```

Commit `9012994` contains the pricing ownership change. For later releases, pass the intended commit or ref instead. Stop if either deploy fails; do not continue to the next app. These scripts restart their own runtimes and attempt rollback on post-switch failure.

Other apps are deployed on this same VPS when their code changes:

```bash
bash ops/deploy/deploy-portal.sh main combined
bash ops/deploy/deploy-proxy-gateway.sh main combined
bash ops/deploy/deploy-key-vault-worker.sh main combined
```

If the host has the `~/shupremium-repo` convenience symlink, it may be used instead of the canonical checkout path. Do not run additional Telegram polling instances during deployment.

## Deploy pipeline

Every deploy follows the same high-level flow:

1. Resolve git ref.
2. Extract only the app subtree with `git archive`.
3. Link shared `.env`/`data`, create the release-local `.venv`, and install dependencies.
4. Validate import/dependency health before switching `current`.
5. Switch `current/<app>` symlink.
6. Restart PM2 or systemd runtime.
7. Run smoke checks.
8. Attempt rollback if restart/smoke fails after switch.
9. Remove old releases, keeping the most recent 5 by default.

## Validation behavior

Python apps:

- shared `.env` and `data` are symlinked into the release
- a fresh `.venv` is created inside the release
- `requirements.txt` is installed
- `pip check` runs
- app import checks run without starting public servers or Telegram polling
- Shopbot additionally runs `npm ci` for its VietQR helper and release preflight checks for runtime secrets plus the explicit financial schema migration
- Key Vault Worker validates runtime settings, DB placement, and an explicitly initialized vault schema before switching the release

Proxy gateway:

- operator `.env` is symlinked from `shared`
- `npm ci --omit=dev` runs for `proxy-operator`
- `npm ci --omit=dev` runs for `proxy-service`
- `node --check` validates key JS entrypoints
- `npm ls --omit=dev --depth=0` validates installed packages

## Health checks

Run the host-wide verifier:

```bash
cd /srv/shupremium-stack/repo
bash ops/scripts/verify-all-health.sh combined
```

The combined verifier checks all five apps, including the Shopbot admin on localhost `8092`. Legacy `arm`/`shopbot` filters remain available for targeted diagnostics; they do not describe separate current VPSs.

Manual spot checks:

```bash
readlink -f /srv/shupremium-stack/current/portal
readlink -f /srv/shupremium-stack/current/platform-control
readlink -f /srv/shupremium-stack/current/proxy-gateway
readlink -f /srv/shupremium-stack/current/shopbot
```

PM2 runtimes on the shared VPS:

```bash
pm2 ls
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8090/ -o /dev/null
curl -fsS http://127.0.0.1:8091/health
```

Shopbot runtime on the same VPS:

```bash
systemctl status shopbot --no-pager
journalctl -u shopbot -n 80 --no-pager
```

## Rollback

Rollback to previous release:

```bash
cd /srv/shupremium-stack/repo
bash ops/deploy/rollback-app.sh portal
```

Rollback to a specific release:

```bash
bash ops/deploy/rollback-app.sh portal /srv/shupremium-stack/releases/<timestamp>/portal
```

Rollback uses the same restart and smoke logic as deploy. If rollback target also fails, inspect the audit log and runtime manager before attempting another switch.

## Shopbot backup and standby recovery

Back up the Shopbot runtime on the shared VPS from its current release:

```bash
cd /srv/shupremium-stack/current/shopbot
bash scripts/backup_shopbot.sh
```

Keep the SQLite snapshot from `shared/shopbot/data`, `/srv/shupremium-stack/shared/shopbot/.env`, and the current git commit/release timestamp together. Do not commit backups to Git.

To restore Shopbot on a replacement combined host (restore the other apps separately):

1. Prepare the canonical `/srv/shupremium-stack` layout and set `/etc/shupremium-host-role` to `combined`.
2. Restore `.env` and the DB snapshot into `/srv/shupremium-stack/shared/shopbot`.
3. If the restored DB predates the current financial schema, back it up again and run:

   ```bash
   cd /srv/shupremium-stack/repo/apps/shopbot
   python3 scripts/migrate_financial.py /srv/shupremium-stack/shared/shopbot/data/<database>.db
   ```

4. Update the repository, run `bash ops/deploy/bootstrap-host.sh`, then deploy with `bash ops/deploy/deploy-shopbot.sh main combined`.
5. Reload and restart the service:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart shopbot
   ```

6. Verify the runtime and restored state:

   ```bash
   systemctl status shopbot --no-pager
   journalctl -u shopbot -n 80 --no-pager
   readlink -f /srv/shupremium-stack/current/shopbot
   ls -la /srv/shupremium-stack/shared/shopbot
   ```

Confirm that Telegram polling starts once, recent users/orders/wallet balances are visible, and the payment, fulfillment, notification, key-alert, and control-plane sync workers stay running. Use the MBBank v3 settings below when restoring scanner configuration; do not restore old scanner URLs containing deprecated credentials or query parameters.

## Deploy audit log

Deploy and rollback append JSONL records to:

```text
/srv/shupremium-stack/shared/_ops/deploy-audit.jsonl
```

Each record includes app, host role, runtime kind, git ref, release path, previous release, phase, status, duration, and message.

Inspect recent deploys:

```bash
tail -n 50 /srv/shupremium-stack/shared/_ops/deploy-audit.jsonl
```

## Recover a stale deploy/runtime lock

Deploy/rollback uses `flock` at `/srv/shupremium-stack/shared/_ops/deploy.lock` to prevent concurrent deploys. Deploy and Proxy Operator also share `/srv/shupremium-stack/shared/_ops/runtime.lock` as a runtime guard.

Do not remove `runtime.lock` just because an operation reports it busy. First inspect its recorded owner and check whether that process still exists:

```bash
lock=/srv/shupremium-stack/shared/_ops/runtime.lock
lockfile=/srv/shupremium-stack/shared/_ops/deploy.lock

if ! sudo -n test -d "$lock"; then
  echo 'No runtime lock directory.'
else
  owner=$(sudo -n cat "$lock/owner" 2>/dev/null || true)
  printf 'Lock owner: %s\n' "${owner:-UNREADABLE}"
  pid=''
  case "$owner" in
    deploy-*) pid=${owner#deploy-}; pid=${pid%%-*} ;;
    *' pid='*) pid=${owner##* pid=} ;;
  esac
  if [[ "$pid" =~ ^[0-9]+$ ]]; then
    ps -p "$pid" -o pid=,ppid=,stat=,etime=,comm= || true
  fi
fi

if sudo -n flock --nonblocking "$lockfile" true; then
  echo 'No deploy currently holds flock.'
else
  echo 'Deploy flock is held or cannot be checked; do not remove the runtime lock.'
fi
```

Before clearing a stale runtime lock, verify that no deploy, rollback, proxy apply, nginx validation/reload, PM2 restart, or child process from those operations is still running. A missing PID alone is not sufficient proof.

After verification, set `expected` to the exact current owner string and remove only the owner file plus the now-empty directory:

```bash
set -euo pipefail
lock=/srv/shupremium-stack/shared/_ops/runtime.lock
expected='<exact owner string>'
actual=$(sudo -n cat "$lock/owner") || exit 1
[[ -n "$expected" && "$actual" == "$expected" ]] || exit 1
sudo -n rm -- "$lock/owner"
sudo -n rmdir -- "$lock"
```

Do not use recursive deletion for the lock directory. If `rmdir` fails, inspect the remaining files instead of forcing removal.

## Shopbot MBBank v3 settings

Scanner settings:

```env
MB_API_URL=https://api.apicanhan.com/transactions/MB
MB_API_KEY=<provider-api-key>
```

Runtime request built by code:

```text
https://api.apicanhan.com/transactions/MB/<ApiKey>/?version=3
```

Do not set `MB_API_URL` to a URL containing `?key=`, `username`, `password`, `accountNo`, or `version=3`. Username/password are deprecated for scanner. Account number/name/bank ID remain required for VietQR rendering.

## Production safety checklist

- Confirm host role before deploy.
- Confirm `git status` in `/srv/shupremium-stack/repo` is clean or intentionally dirty.
- Confirm shared `.env` and DB paths before first deploy.
- Do not copy local app folders into `current/`.
- Do not overwrite `shared/` state during code deploy.
- Use deploy scripts, not manual PM2/systemd start commands, for normal releases.
- After deploy, run `ops/scripts/verify-all-health.sh`.
- If payment or pricing changed, run focused verification scripts before deploy.
- If deploy/rollback or Proxy Operator reports the shared runtime lock busy after an interrupted operation, follow the recovery procedure above; never delete the lock blindly.
