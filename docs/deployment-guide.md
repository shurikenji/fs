# Deployment Guide

Updated: 2026-06-23

This is the current deploy guide for `shupremium-stack`. The production contract is:

- Git is source of truth.
- Deploy is per app and per host role.
- Runtime state stays outside releases.
- Rollback is symlink-based.
- Manual folder copy/scp deploy is not the normal path.
- GitHub must be treated as public until confirmed otherwise; never commit runtime secrets or copied production data.

## Hosts and roles

| Host | Role file | Apps |
| --- | --- | --- |
| ARM VPS | `/etc/shupremium-host-role = arm` | `portal`, `platform-control`, `proxy-gateway` |
| Shopbot VPS | `/etc/shupremium-host-role = shopbot` | `shopbot` |

Set role:

```bash
echo arm | sudo tee /etc/shupremium-host-role
echo shopbot | sudo tee /etc/shupremium-host-role
```

Only set the role that matches the current VPS.

## ARM VPS baseline

Recommended baseline for the ARM host role:

- Ubuntu `22.04` aarch64 for lowest migration risk with the current Python 3.10/nginx/PM2 stack.
- Node.js 20 LTS, npm, PM2, Python venv, nginx, certbot, and certbot Cloudflare DNS plugin.
- Oracle VCN or NSG ingress: TCP `22`, `80`, and `443` only.
- UFW on the VPS: allow `OpenSSH`, `80/tcp`, and `443/tcp`.

Do not expose internal app ports publicly:

| Port | Owner | Exposure |
| --- | --- | --- |
| `8080` | `portal` | localhost/nginx only |
| `8090` | `platform-control` | localhost/nginx only |
| `8091` | `proxy-operator` | localhost/internal admin only |
| proxy service ports | generated `proxy-service` processes | localhost/nginx only |

Safe UFW sequence:

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

Oracle VCN rules are separate from UFW. Both layers must allow `22`, `80`, and `443`, otherwise SSH or public HTTPS can still fail.

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
  current/
    portal -> /srv/shupremium-stack/releases/<timestamp>/portal
    platform-control -> /srv/shupremium-stack/releases/<timestamp>/platform-control
    proxy-gateway -> /srv/shupremium-stack/releases/<timestamp>/proxy-gateway
    shopbot -> /srv/shupremium-stack/releases/<timestamp>/shopbot
  shared/
    portal/
      .env
      data/
      venv/
    platform-control/
      .env
      data/
      venv/
    shopbot/
      .env
      data/
      venv/
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
If the repo is later moved to private GitHub, replace the clone URL with the new private remote.

For a new ARM migration host, set the role before first deploy:

```bash
echo arm | sudo tee /etc/shupremium-host-role
```

Keep the old ARM host serving traffic until the new host passes local and DNS-resolved checks.

## Shared runtime preparation

Prepare the matching shared directory before the first deploy.

### Portal

```bash
mkdir -p /srv/shupremium-stack/shared/portal/data
cp /path/to/known-good-portal.env /srv/shupremium-stack/shared/portal/.env
cp -a /path/to/known-good-portal-data/. /srv/shupremium-stack/shared/portal/data/
python3 -m venv /srv/shupremium-stack/shared/portal/venv
```

### Platform Control

```bash
mkdir -p /srv/shupremium-stack/shared/platform-control/data
cp /path/to/known-good-platform-control.env /srv/shupremium-stack/shared/platform-control/.env
cp -a /path/to/known-good-platform-control-data/. /srv/shupremium-stack/shared/platform-control/data/
python3 -m venv /srv/shupremium-stack/shared/platform-control/venv
```

### Shopbot

```bash
mkdir -p /srv/shupremium-stack/shared/shopbot/data
cp /path/to/known-good-shopbot.env /srv/shupremium-stack/shared/shopbot/.env
cp -a /path/to/known-good-shopbot-data/. /srv/shupremium-stack/shared/shopbot/data/
python3 -m venv /srv/shupremium-stack/shared/shopbot/venv
```

Shopbot production unit should point to the current symlink:

```ini
WorkingDirectory=/srv/shupremium-stack/current/shopbot
ExecStart=/srv/shupremium-stack/shared/shopbot/venv/bin/python -m bot.main
```

### Proxy Gateway

```bash
mkdir -p /srv/shupremium-stack/shared/proxy-gateway/proxy-operator
cp /path/to/known-good-proxy-operator.env /srv/shupremium-stack/shared/proxy-gateway/proxy-operator/.env
```

Node dependencies are installed inside releases during deploy; do not copy `node_modules` into Git.

## DNS and TLS for ARM cutover

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

Do not switch Cloudflare DNS to the new ARM IP until the new host passes local checks. Before DNS cutover, test public hostnames against the new IP:

```bash
NEW_ARM_IP=<new-singapore-ip>
curl --resolve shupremium.com:443:$NEW_ARM_IP -I https://shupremium.com/
curl --resolve admin.shupremium.com:443:$NEW_ARM_IP -I https://admin.shupremium.com/
curl --resolve gpt1.shupremium.com:443:$NEW_ARM_IP -I https://gpt1.shupremium.com/
```

## Deploy commands

### ARM VPS

```bash
cd /srv/shupremium-stack/repo
git fetch origin
git pull --ff-only origin main
bash ops/deploy/deploy-portal.sh main
bash ops/deploy/deploy-platform-control.sh main
bash ops/deploy/deploy-proxy-gateway.sh main
```

### Shopbot VPS

```bash
cd /srv/shupremium-stack/repo
git fetch origin
git pull --ff-only origin main
bash ops/deploy/deploy-shopbot.sh main
```

If the host has convenience symlinks:

```bash
cd ~/shupremium-repo
bash ops/deploy/deploy-shopbot.sh main
```

## Deploy pipeline

Every deploy follows the same high-level flow:

1. Resolve git ref.
2. Extract only the app subtree with `git archive`.
3. Prepare shared `.env`, `data`, venv, and dependencies.
4. Validate import/dependency health before switching `current`.
5. Switch `current/<app>` symlink.
6. Restart PM2 or systemd runtime.
7. Run smoke checks.
8. Attempt rollback if restart/smoke fails after switch.
9. Remove old releases, keeping the most recent 5 by default.

## Validation behavior

Python apps:

- shared `.env` and `data` are symlinked into the release
- shared `venv` is created/reused
- `requirements.txt` is installed
- `pip check` runs
- app import checks run without starting public servers or Telegram polling

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
bash ops/scripts/verify-all-health.sh
```

Explicit host role:

```bash
bash ops/scripts/verify-all-health.sh arm
bash ops/scripts/verify-all-health.sh shopbot
```

Manual spot checks:

```bash
readlink -f /srv/shupremium-stack/current/portal
readlink -f /srv/shupremium-stack/current/platform-control
readlink -f /srv/shupremium-stack/current/proxy-gateway
readlink -f /srv/shupremium-stack/current/shopbot
```

ARM runtime:

```bash
pm2 ls
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8090/ -o /dev/null
curl -fsS http://127.0.0.1:8091/health
```

Shopbot runtime:

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
