# Current State And Roadmap

Updated: 2026-06-23

This replaces older rollout notes. The V4 migration is no longer a pending manual copy/scp rollout; the active target is the monorepo deploy model under `/srv/shupremium-stack`.

The current public GitHub repo must be treated as public. All docs and examples must stay sanitized.

## Current state

| Component | State | Canonical runtime |
| --- | --- | --- |
| `portal` | Active public runtime | ARM VPS, PM2, `/srv/shupremium-stack/current/portal` |
| `platform-control` | Active admin shell | ARM VPS, PM2, `/srv/shupremium-stack/current/platform-control` |
| `proxy-gateway` | Active proxy plane | ARM VPS, PM2, `/srv/shupremium-stack/current/proxy-gateway` |
| `shopbot` | Active commerce runtime | Shopbot VPS, systemd, `/srv/shupremium-stack/current/shopbot` |
| `balance-checker` | Archived legacy code | Not in active deploy manifest |

## Current migration state

- The existing ARM role is live and serving portal/admin/proxy traffic.
- A new Singapore Oracle ARM VPS is being prepared as the replacement ARM role host.
- DNS cutover is pending and must wait for VCN/UFW, nginx, wildcard cert, PM2 persistence, and local health checks.
- The target OS for the new ARM host is Ubuntu 22.04 aarch64.
- GitHub remains public for now, so `_local_cleanup/`, secrets, DBs, generated data, `node_modules`, logs, and design exports must remain out of Git.

## Completed direction

- Monorepo is the source of truth.
- Deploy is app-specific, release-based, and rollback-capable.
- Runtime state is separated into `/srv/shupremium-stack/shared`.
- `platform-control` is the admin/control-plane entry point.
- `portal` serves public Shupremium pages and runtime cache.
- `shopbot` remains isolated on its own VPS and owns commerce data.
- `proxy-gateway` remains on the ARM VPS and is managed through `proxy-operator`.
- MBBank scanner integration in Shopbot uses MBBank v3:
  - base URL: `https://api.apicanhan.com/transactions/MB`
  - runtime URL: `{base_url}/{ApiKey}/?version=3`
  - scanner no longer uses MB username/password/account number
  - VietQR still uses MB account number/name/bank ID

## Near-term priorities

1. Finish Singapore ARM host setup without switching DNS early.
2. Keep the public GitHub repo sanitized until it is moved private, and keep the same hygiene after that.
3. Verify the new ARM host with `ops/scripts/verify-all-health.sh`, PM2 persistence, nginx, and `curl --resolve`.
4. Keep Shopbot deploys through `ops/deploy/deploy-shopbot.sh`, not through the old standalone path.
5. Continue UI/content alignment from the redesign across portal and platform-control.
6. Continue pricing cleanup by separating parser, pricing engine, translation/catalog, and public presenter responsibilities.

## Future refactor targets

### Pricing pipeline

Current risk: parser/profile detection, pricing conversion, translation, and public output are still tightly coupled.

Target:

- raw upstream parser layer
- provider/profile detection layer
- pricing engine layer
- catalog/translation layer
- public presenter layer
- focused tests for each source payload shape

### Deploy tooling

Current deploy tooling is usable and should stay script-based for now.

Target:

- keep deploy scripts as the only production release path
- improve smoke coverage for proxy-service generated processes
- keep audit log review simple
- document every manual production exception in `memory.md`

### Secret hygiene

Current rule:

- real `.env`, provider tokens, API keys, cookies, SQLite DBs, logs, and local agent session files must never be committed.
- current GitHub visibility is public, so every committed file must be safe to expose.

Target:

- all docs use placeholders only
- scratch scripts stay outside Git or use `.example` files only
- public GitHub history containing old secrets should be treated as compromised until those secrets are rotated
- `_local_cleanup/` is a local quarantine only and must not be pushed.

## Acceptance checks for future changes

- The touched app has focused local verification.
- GitNexus impact/context was used before code-symbol edits.
- `gitnexus_detect_changes()` matches the expected scope before commit.
- Deploy goes through the relevant `ops/deploy/deploy-*.sh`.
- Runtime state under `shared/` is not overwritten.
- Health check passes after deploy:

```bash
cd /srv/shupremium-stack/repo
bash ops/scripts/verify-all-health.sh
```
