# Current State And Roadmap

Updated: 2026-11-11

The active deployment model is the monorepo release layout under `/srv/shupremium-stack`. Keep this file focused on current repository state and remaining work; historical rollout notes belong outside the active docs set.

All committed docs and examples must stay sanitized regardless of repository visibility.

## Current state

Production is consolidated onto one VPS (operator confirmation, 2026-11-11); deploy with role `combined`. App process and database boundaries remain separate. This update does not claim live inspection of the VPS.

| Component | State | Canonical runtime |
| --- | --- | --- |
| `portal` | Active public runtime | Same VPS (`combined`), PM2, `/srv/shupremium-stack/current/portal` |
| `platform-control` | Active admin shell | Same VPS (`combined`), PM2, `/srv/shupremium-stack/current/platform-control` |
| `proxy-gateway` | Active proxy plane | Same VPS (`combined`), PM2, `/srv/shupremium-stack/current/proxy-gateway` |
| `shopbot` | Active commerce runtime | Same VPS (`combined`), systemd, `/srv/shupremium-stack/current/shopbot` |
| `key-vault-worker` | Active deploy target | Same VPS (`combined`), systemd, `/srv/shupremium-stack/current/key-vault-worker` |
| `balance-checker` | Archived legacy code | Not in active deploy manifest |

## Current repository state

- `ops/deploy/app-manifest.sh` defines five deployable apps and their compatibility roles; `combined` deploys all five on the current single VPS.
- Python releases use a release-local `.venv`; persistent `.env` and `data/` remain under `shared/`.
- Shopbot requires the explicit financial schema migration before release preflight succeeds.
- Shopbot polling is limited to `message` and `callback_query`; purchase creation uses DB-backed idempotency via `purchase_nonce`.
- Shopbot runs payment, fulfillment, notification, key-alert, and control-plane background tasks as one supervised runtime.
- `key-vault-worker` is a separate systemd service for persistent encrypted key history and internal lookup/summary APIs.
- `_local_cleanup/`, secrets, DBs, generated data, `node_modules`, logs, and design exports must remain out of Git.

## Completed direction

- Monorepo is the source of truth.
- Deploy is app-specific, release-based, and rollback-capable.
- Runtime state is separated into `/srv/shupremium-stack/shared`.
- `platform-control` is the admin/control-plane entry point.
- `portal` serves public Shupremium pages and runtime cache.
- `shopbot` owns commerce data and runs in its own systemd service on the shared VPS. Prices, discounts and spend tiers are managed in Shopbot Admin.
- `proxy-gateway` runs on the same VPS and is managed through `proxy-operator`.
- `key-vault-worker` is isolated behind localhost on the `combined` role and validates its DB/schema before release switch.
- Shopbot money paths now include purchase idempotency, explicit financial migration/preflight, fulfillment queueing, notification queueing, and transaction ownership checks.
- MBBank scanner integration in Shopbot uses MBBank v3:
  - base URL: `https://api.apicanhan.com/transactions/MB`
  - runtime URL: `{base_url}/{ApiKey}/?version=3`
  - scanner no longer uses MB username/password/account number
  - VietQR still uses MB account number/name/bank ID

## Near-term priorities

1. Verify the actual host role, runtime manager, shared state, and health output before every production deploy; docs must not assume a historical VPS state.
2. Keep Shopbot deploys through `ops/deploy/deploy-shopbot.sh` and run the explicit financial migration only against a backed-up DB when required.
3. Deploy `key-vault-worker` only on the `combined` role after its `.env` and vault DB have been explicitly initialized.
4. Keep the repository sanitized: secrets, DBs, generated data, logs, `node_modules`, and local cleanup snapshots stay outside Git.
5. Continue pricing cleanup by separating parser, pricing engine, translation/catalog, and public presenter responsibilities.

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
- improve smoke coverage for proxy-service generated processes when a concrete failure mode justifies it
- keep audit log review simple
- keep production exceptions in operational runbooks instead of accumulating transient host snapshots in `memory.md`

### Secret hygiene

Current rule:

- real `.env`, provider tokens, API keys, cookies, SQLite DBs, logs, and local agent session files must never be committed.
- every committed file must be safe to expose.

Target:

- all docs use placeholders only
- scratch scripts stay outside Git or use `.example` files only
- if a secret was ever committed, treat it as compromised and rotate it rather than relying on file deletion
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
