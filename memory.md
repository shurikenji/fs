# Shupremium Stack Memory

Last updated: 2026-05-05

This file is the compact source of truth for future work. Keep it short and update it only with facts that affect code changes, deploys, rollback, or production operations.

## Workspace

- Canonical local repo: `D:\Projects\Code\shupremium-stack`
- Git branch: `main`
- Git remote: `origin = https://github.com/shurikenji/fs.git`
- Main memory file: `memory.md`
- Older imported notes may still exist under `docs/`, but this root `memory.md` is the active handoff file.
- GitNexus repo name: `shupremium-stack`
- GitNexus was re-analyzed locally on 2026-05-05 with `npx gitnexus analyze`; analyzer output reported `2,902 nodes`, `10,213 edges`, `160 clusters`, `235 flows`.

Current local working tree note:

- Existing unrelated local changes were present before this memory cleanup: `AGENTS.md`, `CLAUDE.md`, `.claude/*`, `_plan_lines.json`, `docs/portal-arm-cutover-runbook.md`, `key.py`, `vps-arm.md`, `vps-shopbot.md`.
- Do not revert those files unless the user explicitly asks.

## Active Apps

- `apps/portal`: public Shupremium site for pricing, balance, keys, logs, status; Python/FastAPI.
- `apps/platform-control`: control plane/admin shell; Python/FastAPI.
- `apps/shopbot`: Telegram shop bot plus embedded admin panel; Python/FastAPI admin inside bot process.
- `services/proxy-gateway`: proxy operator and proxy services; Node.js/PM2.
- `archive/services/balance-checker`: legacy archived service, not in active deploy manifest.

Runtime state must stay outside Git:

- `.env`
- virtualenvs
- `node_modules`
- SQLite DB files
- `data/`
- logs and release archives

## Deploy Model

Canonical production layout:

```text
/srv/shupremium-stack/
  repo/
  releases/
  current/
  shared/
```

Deploy scripts:

- `ops/deploy/deploy-portal.sh main`
- `ops/deploy/deploy-platform-control.sh main`
- `ops/deploy/deploy-shopbot.sh main`
- `ops/deploy/deploy-proxy-gateway.sh main`
- `ops/deploy/rollback-app.sh <app>`

Manifest facts from `ops/deploy/app-manifest.sh`:

- `portal`: host role `arm`, runtime `pm2-python`, process `portal`, smoke `127.0.0.1:8080`.
- `platform-control`: host role `arm`, runtime `pm2-python`, process `platform-control`, smoke `127.0.0.1:8090`.
- `shopbot`: host role `shopbot`, runtime `systemd-python`, unit `shopbot`.
- `proxy-gateway`: host role `arm`, runtime `pm2-node-multi`, process `proxy-operator`.

Important deploy behavior:

- Deploy extracts only the app subtree with `git archive`.
- Python releases symlink `.env`, `data`, and `.venv` from `shared`.
- Proxy gateway installs dependencies for both `proxy-operator` and `proxy-service` during prepare.
- `current/<app>` is switched before restart/smoke; deploy attempts rollback if restart or smoke fails.
- Audit log path: `/srv/shupremium-stack/shared/_ops/deploy-audit.jsonl`.

## Production Topology

### ARM VPS

- Host: `ubuntu@instance-20260114-0319`
- OS observed: Ubuntu 22.04.5 LTS, ARM/aarch64.
- Role should be `arm`, but older `vps-arm.md` output showed `/etc/shupremium-host-role` missing and `/srv/shupremium-stack/current/*` missing. Treat that file as stale/noisy until re-verified.
- PM2 processes observed in old output: `portal`, `platform-control`, `proxy-operator`, `proxy-gpt1..5`, `proxy-sv1..2`, and stopped `admin-panel`.
- Ports observed in old output: `portal` on `127.0.0.1:8080`, `platform-control` on `0.0.0.0:8090`, `proxy-operator` on `0.0.0.0:8091`, proxy services on `3001..3005` and `4001..4002`.

Before any ARM VPS change, re-run a fresh verification:

```bash
cat /etc/shupremium-host-role 2>/dev/null || echo missing
ls -la /srv/shupremium-stack
for d in /srv/shupremium-stack/current/portal /srv/shupremium-stack/current/platform-control /srv/shupremium-stack/current/proxy-gateway; do
  echo "--- $d"
  [ -e "$d" ] && readlink -f "$d" || echo missing
done
pm2 ls
ss -ltnp | grep -E ":8080|:8090|:8091|:3001|:3002|:3003|:3004|:3005|:4001|:4002" || true
```

### Shopbot VPS

- Host: `ubuntu@instance-20260306-0442`
- OS observed: Ubuntu 22.04.5 LTS, x86_64.
- Role is now set to `shopbot`.
- Runtime is `systemd` unit `shopbot`.
- Canonical code/deploy root is `/srv/shupremium-stack`, not the old standalone repo.
- Current unit shape verified by user:
  - `WorkingDirectory=/srv/shupremium-stack/current/shopbot`
  - `ExecStart=/srv/shupremium-stack/shared/shopbot/venv/bin/python -m bot.main`
- Home directory was cleaned on 2026-05-05. It should contain only:
  - `backups`
  - `shopbot-current -> /srv/shupremium-stack/current/shopbot`
  - `shopbot-shared -> /srv/shupremium-stack/shared/shopbot`
  - `shupremium-repo -> /srv/shupremium-stack/repo`
- Old `/home/ubuntu/shopbot` standalone repo and cutover backup folder were removed after the bot had already been running from the monorepo layout.

Shopbot deploy command:

```bash
cd ~/shupremium-repo
git fetch origin
git pull --ff-only origin main
bash ops/deploy/deploy-shopbot.sh main
```

Shopbot runtime checks:

```bash
systemctl status shopbot --no-pager
journalctl -u shopbot -n 80 --no-pager
readlink -f ~/shopbot-current
ls -la ~/shopbot-shared
```

## Recent Shopbot Payment Change

Commit pushed to `origin/main`:

- `70893d9 Update shopbot MBBank v3 transaction integration`

Behavior:

- `apps/shopbot/bot/services/mbbank.py` now calls MBBank v3 as:
  - base URL setting: `https://api.apicanhan.com/transactions/MB`
  - runtime request: `{base_url}/{ApiKey}/?version=3`
- `MB_API_URL` must not include `?key=`, username, password, account number, or `?version=3`.
- `MB_API_KEY` is the provider key.
- `MB_USERNAME` and `MB_PASSWORD` are deprecated for scanning and no longer used by the new client.
- `MB_ACCOUNT_NO`, `MB_ACCOUNT_NAME`, and `MB_BANK_ID` are still used for VietQR rendering.
- Admin settings UI was updated to remove scanner username/password and split scanner settings from VietQR settings.
- Verification added: `apps/shopbot/verification/verify_mbbank.py`.
- User confirmed after deploy that the bot ran correctly and processed a successful payment transaction with the new API.

## Cross-App Contracts

- `platform-control` owns source/runtime intent for pricing and pushes/imports into `portal`.
- `portal` owns public pricing serving, cache/snapshot behavior, translation, visibility, and public-safe output.
- Internal token boundary:
  - `X-Control-Plane-Token` protects platform-control internal endpoints.
  - `X-Pricing-Admin-Token` protects portal internal pricing admin endpoints.
- Separate shopbot bridge:
  - `apps/shopbot/admin/routers/internal_portal.py`
  - protected by portal/shopbot internal token settings.
  - used for health, user summary, and portal-session issue/verify.

## High-Risk Code Areas

Use GitNexus impact/context before editing these:

- `apps/portal/app/cache.py:fetch_pricing`
- `apps/portal/app/translation_service.py:build_public_pricing`
- `apps/portal/app/server_profiles.py:describe_server_profile`
- `apps/portal/app/sync_service.py:refresh_server_snapshot`
- `apps/platform-control/app/pricing_hub_client.py:pricing_import_control_plane`
- `ops/deploy/lib.sh`
- `ops/deploy/app-manifest.sh`

Why:

- Pricing parser, cache, engine, translation, and presenter responsibilities are still interleaved.
- Deploy scripts control all app release, restart, smoke, and rollback flows.
- Shell deploy scripts are not deeply modeled by GitNexus; read them directly before changing.

## Pricing Facts To Preserve

- Public pricing should use cache/snapshot and not fetch upstream directly per user request.
- Parser/profile selection should be based on actual payload shape, not only admin-configured source type.
- Known payload behavior from prior work:
  - `gpt2` behaves like RixAPI/inline group pricing.
  - `gpt1`, `gpt4`, `gpt5`, and `sv1` behave like catalog-list/Yunwu-style payloads.
- `quota_multiple` remains mandatory in pricing output and must not be dropped.
- Long-term refactor direction:
  - raw parser layer
  - pricing engine layer
  - catalog/translation layer
  - public presenter layer

## Production Safety Rules

- Do not copy whole local app folders onto production.
- Do not overwrite production `.env`, `data`, DB files, `.venv`, or `node_modules`.
- Do not deploy tarballs unless there is an explicit emergency reason.
- Use deploy scripts from `/srv/shupremium-stack/repo`.
- Before production deploy, check:
  - correct host role
  - current symlink target
  - runtime manager status
  - relevant health/smoke output
- After code changes, run focused verification/tests locally where feasible.
- Before commit, run `gitnexus_detect_changes()` when code was modified.

## Useful Commands

Local repo:

```powershell
cd D:\Projects\Code\shupremium-stack
git status --short
git log --oneline -n 12
```

Deploy shopbot:

```bash
cd ~/shupremium-repo
bash ops/deploy/deploy-shopbot.sh main
```

Verify all apps on a host:

```bash
cd /srv/shupremium-stack/repo
bash ops/scripts/verify-all-health.sh
```

Check shopbot MBBank config:

```bash
grep '^MB_API_URL=' ~/shopbot-shared/.env
grep -n "accountNo\|username\|version=3" ~/shopbot-current/bot/services/mbbank.py
```
