# GitNexus Analysis

Date: 2026-04-05
Repo: `shupremium-stack`
Index stats: `300 files`, `2457 symbols`, `7272 edges`, `196 flows`

## Scope

This note consolidates the first GitNexus pass for three workstreams already called out in `memory.md`:

- deploy and runtime blast radius
- `portal` and `platform-control` integration map
- pricing refactor map for the parser/engine/presenter direction

GitNexus indexed the monorepo successfully, but the shell deploy layer is only partially modeled. The deploy section below is therefore a hybrid of GitNexus plus direct code reading.

## 1. Deploy and Runtime Blast Radius

### Core deploy spine

The deploy layer is centered on these files:

- `ops/deploy/lib.sh`
- `ops/deploy/app-manifest.sh`
- `ops/deploy/bootstrap-host.sh`
- `ops/deploy/deploy-portal.sh`
- `ops/deploy/deploy-platform-control.sh`
- `ops/deploy/deploy-shopbot.sh`
- `ops/deploy/deploy-proxy-gateway.sh`
- `ops/deploy/rollback-app.sh`

The critical runtime invariants live in `ops/deploy/lib.sh`:

- stack layout is fixed to `repo`, `releases`, `current`, `shared`
- every deploy extracts only one subtree from git via `git archive`
- `.env`, `data`, and `.venv` are linked from `shared`, not copied into the release
- `current/<app>` is the active switch point for runtime restarts
- runtime restart logic branches by `RUNTIME_KIND`

### Invariants per app

From `ops/deploy/app-manifest.sh`:

- `portal` and `platform-control` are `pm2-python`
- `shopbot` is `systemd-python`
- `proxy-gateway` is `pm2-node-multi`
- archived `balance-checker` is intentionally excluded from the active deploy manifest

### Blast radius notes

Changes in `ops/deploy/lib.sh` affect all app deploys and rollback flows because every `deploy-*.sh` sources it and then calls the same primitives:

- `create_release_dir`
- `extract_release_subtree`
- `switch_current_link`
- `prepare_python_release` or `prepare_proxy_gateway_release`
- `restart_app_runtime`
- `run_runtime_smoke_checks`

Changes in `ops/deploy/app-manifest.sh` affect host-role gating, source extraction paths, smoke URLs, runtime type, and PM2/systemd selection for every app.

`bootstrap-host.sh` is low-logic but high-impact operationally because it creates the canonical directory tree that every later symlink and shared-runtime assumption depends on.

### Deploy risks worth treating as release blockers

- `ops/deploy/lib.sh` switches `current` before restart and smoke checks. That is fine for rollback-capable flows, but any code that assumes `current` always points to a healthy release is only conditionally true during a failed rollout.
- `ops/deploy/rollback-app.sh` does not have a second-level recovery path if the target rollback release also fails restart or smoke checks. It will stop after changing `current` and attempting restart.
- `proxy-gateway` is the highest-drift deploy target because it mixes three runtimes inside one release tree: `proxy-operator`, `proxy-service`, and optional `admin-panel`.
- `shopbot` depends on `systemd` continuing to point at the symlinked `current/shopbot` layout. Any unit file that hardcodes a release path will bypass the monorepo release model.
- archived `balance-checker` no longer participates in the active deploy/runtime branch. Any legacy Oracle instance should be treated as external runtime, not as a managed monorepo app.

### What to verify next in production review

- confirm the `shopbot.service` unit uses the `current/shopbot` path, not a timestamped release path
- confirm PM2 process names match the manifest assumptions on the VPS
- add or verify smoke checks for `proxy-service` and optional `admin-panel`, not only `proxy-operator`
- keep any surviving Oracle `balance-checker` runtime outside the active deploy scope

## 2. Portal and Platform-Control Integration Map

### Actual direction of control

The pricing control loop is not symmetric. The current design is:

1. `platform-control` stores service-source and runtime-setting intent locally.
2. `platform-control` pushes that state into `portal`.
3. `portal` imports and materializes the state into pricing runtime tables and caches.
4. `platform-control` then calls back into `portal` admin endpoints to trigger sync, group refresh, model visibility, and runtime-setting reads.

### Main code path

`platform-control` side:

- `apps/platform-control/app/pricing_admin.py`
- `apps/platform-control/app/pricing_hub_client.py`
- `apps/platform-control/app/security.py`

`portal` side:

- `apps/portal/app/control_plane.py`
- `apps/portal/app/routers/internal_admin_pricing.py`

### Token boundaries

There are two distinct internal token boundaries:

- `X-Control-Plane-Token` protects `platform-control` internal endpoints
- `X-Pricing-Admin-Token` protects `portal` internal pricing admin bridge

This is important because `portal` does two different things:

- it pulls service-source and runtime-setting payloads from `platform-control`
- it exposes a separate admin bridge back to `platform-control`

### GitNexus impact highlights

GitNexus shows `apps/platform-control/app/pricing_hub_client.py:pricing_import_control_plane` as `HIGH` risk upstream:

- direct callers: `_import_runtime_registry`, `control_service_sources_save`, `control_service_sources_delete`
- affected processes include `pricing_sources_save`, `pricing_source_groups_save`, and `pricing_source_models_save`

GitNexus shows `apps/portal/app/control_plane.py:import_control_plane_state` as `LOW` risk upstream inside `portal`, but that is because the blast radius is concentrated and explicit:

- direct callers: `import_control_plane_sources`, `import_control_plane`
- indirect callers: portal lifespan import and control server import actions

### Integration edges that matter most

`portal` pulls from `platform-control` here:

- `GET /api/internal/service-sources`
- `GET /api/internal/pricing-runtime-settings`

That fetch happens in `apps/portal/app/control_plane.py`.

`platform-control` pushes into `portal` here:

- `POST /api/internal/admin/pricing/import-control-plane`
- `POST /api/internal/admin/pricing/sources/{source_id}/sync`
- `GET /api/internal/admin/pricing/sources/{source_id}/groups`
- `POST /api/internal/admin/pricing/sources/{source_id}/groups/refresh`
- `GET /api/internal/admin/pricing/sources/{source_id}/models`
- `GET /api/internal/admin/pricing/settings`
- `POST /api/internal/admin/pricing/settings/save`
- `POST /api/internal/admin/pricing/settings/ai/test`

Those calls are wrapped by `apps/platform-control/app/pricing_hub_client.py`.

### Coupling observations

- `platform-control` owns source metadata and runtime settings, but `portal` owns the actual pricing snapshot, visibility application, translation cache warmup, and public serving path.
- `platform-control` templates and forms are tightly coupled to `portal` bridge response shapes.
- the internal bridge currently acts like an orchestration API, not just a read-only control API

### Related cross-app boundary

There is a separate `portal` to `shopbot` internal bridge in `apps/shopbot/admin/routers/internal_portal.py` for health, user summary, and session issue/verify. It is distinct from the pricing control loop but follows the same pattern: protected internal token, no direct DB access across services.

## 3. Pricing Refactor Map

### Current architecture in practice

The current pricing stack is already partly split, but the boundaries are still blurred.

### Parser and profile selection

Parser selection is centered on:

- `apps/portal/app/server_profiles.py`
- `apps/portal/app/adapters/newapi.py`
- `apps/portal/app/adapters/rixapi.py`
- `apps/portal/app/adapters/custom.py`

`describe_server_profile` is the main switchboard. It determines:

- `parser_id`
- `display_profile`
- `variant_pricing_mode`
- endpoint alias map

GitNexus rates `describe_server_profile` as `CRITICAL` upstream because it fans into:

- adapter selection
- internal admin source inspection endpoints
- public pricing
- API logs
- API key resolution
- control pages

### Pricing engine and snapshot materialization

The current engine-like behavior is spread across:

- `apps/portal/app/cache.py`
- `apps/portal/app/sync_service.py`
- `apps/portal/app/group_catalog.py`
- `apps/portal/app/translation_service.py`
- `apps/portal/app/visibility.py`

`apps/portal/app/cache.py:fetch_pricing` is the heaviest hot spot in the repo. GitNexus rates it `CRITICAL` upstream because it feeds:

- public pricing
- API pricing
- API logs
- API key resolution and update
- admin sync flows
- auto-sync

This function currently mixes several responsibilities:

- cache lookup
- DB snapshot fallback
- upstream fetch
- adapter dispatch
- sync logging
- quota-multiple scaling

That is the strongest evidence for extracting a dedicated pricing engine layer.

### Public presenter

Public presentation is currently spread across:

- `apps/portal/app/translation_service.py:build_public_pricing`
- `apps/portal/app/public_pricing_cache.py`
- `apps/portal/app/sanitizer.py`
- `apps/portal/app/visibility.py`
- `apps/portal/app/routers/public_pricing.py`

GitNexus rates `build_public_pricing` as `CRITICAL` upstream because it feeds:

- public pricing page
- API pricing
- API logs
- API key flows

This is already the closest thing to a presenter layer, but translation, visibility, catalog reconciliation, and sanitization are still interleaved.

### Yunwu-specific logic

Yunwu behavior is spread across:

- `apps/portal/app/yunwu_pricing.py`
- `apps/portal/app/adapters/newapi.py`
- tests in `apps/portal/tests/test_server_specific_pricing.py`

The useful part is that the repo already has explicit fields for:

- `billing_label`
- `billing_unit`
- `price_multiplier`
- `display_profile`
- `variant_pricing_mode`

The weak part is that Yunwu-specific decisions are still embedded inside the generic `newapi` adapter path, especially in `_compute_display_values` and variant-building logic.

### Suggested refactor seam

The clean split for the next refactor should be:

1. Raw parser layer

- adapter returns a parser-oriented raw normalized payload
- no public translation, no visibility filtering, no cache policy

2. Pricing engine layer

- apply server profile
- apply quota multiple
- derive billing labels, units, multipliers
- build variant matrices
- persist canonical snapshot

3. Catalog and translation layer

- group catalog fetch and normalization
- translation cache warmup
- text label enrichment

4. Public presenter layer

- apply visibility
- reconcile catalog with snapshot
- sanitize labels, descriptions, endpoints
- emit public-safe `NormalizedPricing`

### First extractions with the best payoff

- split `apps/portal/app/cache.py:fetch_pricing` into cache policy plus canonical pricing engine
- move Yunwu display math out of `apps/portal/app/adapters/newapi.py` into a dedicated pricing-engine module
- keep `apps/portal/app/server_profiles.py` as registry only, not as a place that indirectly controls fetch, display, and presenter concerns
- narrow `build_public_pricing` so it becomes presenter-only, with translation and catalog preparation passed in as ready inputs

## 4. GitNexus Findings Summary

Highest-risk symbols found during this pass:

- `apps/portal/app/cache.py:fetch_pricing` -> `CRITICAL`
- `apps/portal/app/translation_service.py:build_public_pricing` -> `CRITICAL`
- `apps/portal/app/server_profiles.py:describe_server_profile` -> `CRITICAL`
- `apps/portal/app/sync_service.py:refresh_server_snapshot` -> `HIGH`
- `apps/platform-control/app/pricing_hub_client.py:pricing_import_control_plane` -> `HIGH`
- `services/proxy-gateway/admin-panel/src/utils/pm2Manager.js:generateEcosystem` -> `LOW`

## 5. GitNexus Coverage Limits Seen in This Repo

- `route_map` is not usable yet on this index because the `Route` table is missing in the current graph schema for this repo.
- shell deploy scripts are not modeled deeply enough to rely on `impact()` alone; deploy review still needs direct script reading.
- the index is valid even though the repo has no first git commit yet, but `gitnexus status` still prints a `HEAD` warning until the initial commit exists.

## 6. Recommended Next Moves

- production-hardening pass on `ops/deploy/lib.sh` and `rollback-app.sh`
- focused pricing refactor starting from `fetch_pricing`
- contract review between `platform-control` and `portal` for the pricing admin bridge
- initial git commit so GitNexus status and later diff-based analyses become cleaner
