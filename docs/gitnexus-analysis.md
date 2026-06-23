# GitNexus And Risk Map

Updated: 2026-06-23

Local GitNexus index was refreshed with:

```bash
npx gitnexus analyze
```

Analyzer output reported:

- `2,902` nodes
- `10,213` edges
- `160` clusters
- `235` flows

Use this document as a risk map, not as a replacement for live GitNexus queries. If GitNexus reports the index is stale, re-run analysis before relying on results.

`.gitnexus/` is local generated analysis state. Keep it out of public GitHub, but do not delete it from the working machine unless you are ready to regenerate the index.

## Required workflow for code edits

Before modifying a function, class, or method:

```text
gitnexus_impact(target="<symbol>", direction="upstream")
```

When exploring unfamiliar code:

```text
gitnexus_query(query="<concept>")
gitnexus_context(name="<symbol>")
```

Before commit:

```text
gitnexus_detect_changes(scope="all")
```

## High-risk areas

| Area | Why it is risky |
| --- | --- |
| `ops/deploy/lib.sh` | Shared deploy, restart, smoke, rollback primitives for every app |
| `ops/deploy/app-manifest.sh` | Host-role mapping, source extraction, runtime kind, process names, smoke URLs |
| `apps/portal/app/cache.py:fetch_pricing` | Public pricing data fetch/cache path |
| `apps/portal/app/translation_service.py:build_public_pricing` | Public pricing presentation and translation behavior |
| `apps/portal/app/server_profiles.py:describe_server_profile` | Provider payload/profile detection |
| `apps/portal/app/sync_service.py:refresh_server_snapshot` | Runtime snapshot refresh behavior |
| `apps/platform-control/app/pricing_hub_client.py:pricing_import_control_plane` | Platform-control to portal pricing bridge |
| `apps/shopbot/bot/services/payment_poller.py` | Payment matching, order status, dedup logic |
| `apps/shopbot/bot/services/mbbank.py` | Bank scanner integration contract |

## Deploy graph notes

Deploy scripts share one library:

- `deploy-portal.sh`
- `deploy-platform-control.sh`
- `deploy-shopbot.sh`
- `deploy-proxy-gateway.sh`
- `rollback-app.sh`

All source `ops/deploy/lib.sh`, so changes there affect:

- release extraction
- shared `.env/data/venv` linking
- dependency install
- validation
- current symlink switching
- PM2/systemd restart
- smoke checks
- rollback behavior
- release cleanup
- audit logging

Shell behavior is only partially modeled by GitNexus. Read deploy scripts directly before editing them.

## Portal and platform-control contract

Direction:

```text
platform-control
  -> owns admin/control-plane intent
  -> pushes/imports into portal
  -> portal materializes runtime cache/public output
```

Important token boundaries:

- `X-Control-Plane-Token`: platform-control internal APIs.
- `X-Pricing-Admin-Token`: portal internal pricing admin bridge.

Do not merge these token boundaries without a separate security review.

## Shopbot contract

Shopbot is not a child module of platform-control. It owns its DB, bot process, payment poller, admin UI, and fulfillment logic. Platform-control only opens Shopbot admin through signed launch token flow.

MBBank v3 scanner facts:

- request URL is `{MB_API_URL}/{MB_API_KEY}/?version=3`
- default base URL is `https://api.apicanhan.com/transactions/MB`
- scanner ignores deprecated MB username/password/account number
- VietQR still uses account number/name/bank ID

## Pricing refactor direction

Keep these responsibilities separate in future changes:

- upstream payload parser
- provider/profile detection
- pricing conversion engine
- model/group catalog and translation
- public presenter/output

Known behavior from prior production debugging:

- `gpt2` behaves like RixAPI/inline group pricing.
- `gpt1`, `gpt4`, `gpt5`, and `sv1` behave like catalog-list/Yunwu-style payloads.
- `quota_multiple` must remain present in public pricing output.

## Residual risk

- Some older docs and local runbooks may contain historical VPS output; verify production live state before using them.
- Public GitHub history may contain old secrets from scratch scripts. Rotate any affected provider tokens rather than relying only on file deletion.
- During the Singapore ARM migration, verify the new host through role files, `/srv/shupremium-stack`, PM2/systemd state, nginx, and DNS-resolved smoke checks before cutover.
