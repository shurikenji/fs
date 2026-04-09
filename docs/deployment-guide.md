# Deployment Guide

This document describes the current monorepo deploy model for `shupremium-stack`. The goal is to keep runtime state outside the repo checkout, deploy each app independently by git ref, and prevent bad releases from becoming current.

## 1. Recommended Strategy

Use one private Git repository for the whole stack and deploy by `app + git ref`.

- each VPS clones the same repo into `/srv/shupremium-stack/repo`
- each deploy creates a timestamped release under `/srv/shupremium-stack/releases`
- `current/<app>` is a symlink to the active release
- `.env`, `data`, `venv`, and operator secrets stay under `/srv/shupremium-stack/shared`

Docker is intentionally not part of this phase. The main problem being solved here is deploy hygiene and rollback safety, not container orchestration.

## 2. VPS Layout

```text
/srv/shupremium-stack/
  repo/
  releases/
    20260405-120001/
      portal/
      platform-control/
      proxy-gateway/
      shopbot/
  current/
    portal -> /srv/shupremium-stack/releases/<ts>/portal
    platform-control -> /srv/shupremium-stack/releases/<ts>/platform-control
    proxy-gateway -> /srv/shupremium-stack/releases/<ts>/proxy-gateway
    shopbot -> /srv/shupremium-stack/releases/<ts>/shopbot
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

## 3. Bootstrap

On each VPS:

```bash
sudo mkdir -p /srv/shupremium-stack
sudo chown -R $USER:$USER /srv/shupremium-stack
git clone <PRIVATE_GITHUB_URL> /srv/shupremium-stack/repo
```

Create the host role file:

- ARM host:

```bash
echo arm | sudo tee /etc/shupremium-host-role
```

- Shopbot host:

```bash
echo shopbot | sudo tee /etc/shupremium-host-role
```

Run bootstrap:

```bash
cd /srv/shupremium-stack/repo
bash ops/deploy/bootstrap-host.sh
```

## 4. Shared Runtime Preparation

### Portal

```bash
mkdir -p /srv/shupremium-stack/shared/portal/data
cp /path/to/current-portal/.env /srv/shupremium-stack/shared/portal/.env
cp -a /path/to/current-portal/data/. /srv/shupremium-stack/shared/portal/data/
python3 -m venv /srv/shupremium-stack/shared/portal/venv
```

### Platform Control

```bash
mkdir -p /srv/shupremium-stack/shared/platform-control/data
cp /path/to/current-platform-control/.env /srv/shupremium-stack/shared/platform-control/.env
cp -a /path/to/current-platform-control/data/. /srv/shupremium-stack/shared/platform-control/data/
python3 -m venv /srv/shupremium-stack/shared/platform-control/venv
```

### Shopbot

```bash
mkdir -p /srv/shupremium-stack/shared/shopbot/data
cp /path/to/current-shopbot/.env /srv/shupremium-stack/shared/shopbot/.env
python3 -m venv /srv/shupremium-stack/shared/shopbot/venv
```

### Proxy Gateway

```bash
mkdir -p /srv/shupremium-stack/shared/proxy-gateway/proxy-operator
cp /path/to/current-proxy-operator/.env /srv/shupremium-stack/shared/proxy-gateway/proxy-operator/.env
```

## 5. Deploy Commands

### ARM host

```bash
cd /srv/shupremium-stack/repo
bash ops/deploy/deploy-portal.sh main
bash ops/deploy/deploy-platform-control.sh main
bash ops/deploy/deploy-proxy-gateway.sh main
```

### Shopbot host

```bash
cd /srv/shupremium-stack/repo
bash ops/deploy/deploy-shopbot.sh main
```

## 6. Deploy Pipeline

All deploy scripts now follow the same flow:

1. `extract`
2. `prepare`
3. `validate`
4. `switch`
5. `restart`
6. `smoke`

The important change is `validate` before the symlink switch.

### Prepare phase

- Python apps:
  - symlink shared `.env` and `data`
  - create or reuse shared `venv`
  - install `requirements.txt`
- Proxy gateway:
  - symlink shared operator `.env`
  - run `npm ci --omit=dev` for `proxy-operator`
  - run `npm ci --omit=dev` for `proxy-service`

### Validate phase

- `portal` and `platform-control`
  - run `pip check` in the shared `venv`
  - load `.env`
  - import `app.app:create_app`
  - instantiate the FastAPI app without starting `uvicorn`
- `shopbot`
  - run `pip check` in the shared `venv`
  - load `.env`
  - import `bot.main`
  - instantiate `admin.app:create_admin_app()`
  - do not start Telegram polling
- `proxy-gateway`
  - run `npm ls --omit=dev --depth=0` in `proxy-operator` and `proxy-service`
  - run `node --check` for `proxy-operator/src/server.js`
  - run `node --check` for `proxy-service/src/index.js`
  - run `require.resolve()` checks for key packages in both Node apps

If validation fails, deploy stops before `current/<app>` is changed.

### Restart and smoke phases

- `portal`, `platform-control`: restart PM2 process, then hit manifest-defined smoke URLs
- `shopbot`: restart and verify the `systemd` unit only
- `proxy-gateway`: restart `proxy-operator`, reload PM2 ecosystem for `proxy-service`, then probe each discovered proxy port via `/_internal/health`

If restart or smoke fails after the symlink switch, deploy attempts rollback to the previous release and records that result in the audit log.

## 7. Audit Logging

Each deploy appends JSONL records to:

```text
/srv/shupremium-stack/shared/_ops/deploy-audit.jsonl
```

Each record includes:

- `timestamp`
- `app`
- `host_role`
- `runtime_kind`
- `git_ref`
- `release_dir`
- `previous_release`
- `phase`
- `status`
- `duration_ms`
- `message`

Expected phases:

- `deploy`
- `prepare`
- `validate`
- `switch`
- `restart`
- `smoke`
- `rollback`

This log is intended for deploy traceability, not application logging.

## 8. Health Verification

Use the repo script:

```bash
bash ops/scripts/verify-all-health.sh
```

Behavior:

- reads the current host role from `/etc/shupremium-host-role` unless one is passed explicitly
- loads active apps from `ops/deploy/app-manifest.sh`
- verifies only apps assigned to the current host role
- reuses runtime smoke logic from the deploy library
- for `proxy-gateway`, discovers ports from the active `proxy-service/ecosystem.config.js`
- for `shopbot`, checks the `systemd` unit only

Examples:

```bash
bash ops/scripts/verify-all-health.sh arm
bash ops/scripts/verify-all-health.sh shopbot
```

## 9. Rollback

Rollback to the previous release:

```bash
cd /srv/shupremium-stack/repo
bash ops/deploy/rollback-app.sh portal
```

Rollback to a specific release:

```bash
bash ops/deploy/rollback-app.sh portal /srv/shupremium-stack/releases/20260405-120001/portal
```

Manual rollback uses the same restart and smoke checks as deploy. If the target release fails, the script attempts to restore the release that was current before rollback started.

## 10. Runtime Notes

- `portal` and `platform-control` stay on PM2
- `proxy-gateway` uses PM2 for both the operator and the generated proxy-service apps
- `shopbot` stays on `systemd` by design

Do not migrate `shopbot` to PM2 as part of routine deploy work unless a separate runtime migration project is explicitly planned.

## 11. Troubleshooting

### Dependency install failures

- Python:
  - check `requirements.txt`
  - inspect shared `venv`
  - rerun deploy after fixing the dependency graph
- Node:
  - inspect `package-lock.json`
  - verify `npm ci --omit=dev` works in both `proxy-operator` and `proxy-service`

### Validation failures

- check the deploy audit log for the failing phase
- verify shared `.env` exists and is readable
- for Python apps, test the same import path manually inside the shared `venv`
- for proxy apps, rerun `node --check` and `npm ls --omit=dev --depth=0`

### Restart failures

- verify PM2 or `systemd` is healthy on the target host
- inspect the active `current/<app>` symlink
- confirm the release still points to valid shared files and directories

### Smoke-check failures

- run `bash ops/scripts/verify-all-health.sh <host-role>`
- inspect the app-specific health endpoint or PM2 status
- for `proxy-gateway`, inspect the current `proxy-service/ecosystem.config.js`

### Rollback behavior

- deploy rollback is only attempted after `switch` when `restart` or `smoke` fails
- validate failures do not need rollback because the current symlink was never changed
- manual rollback writes the same audit records as a deploy-triggered rollback

## 12. Why Monorepo Still Works Across Two VPS Hosts

Monorepo is only the code layout. Deploy remains split by app and host role:

- one repository
- different host roles
- different deploy scripts
- shared deploy primitives

That is simpler than the old manual tarball flow because release creation, restart, smoke checks, rollback, and audit logging all now follow one model.
