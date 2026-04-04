# Shupremium Deployment Memory

## Current State (updated 2026-04-04)

- `shopbot` stays isolated on its own Ubuntu VPS.
- `platform-control` is the only admin shell and is live at `https://admin.shupremium.com`.
- `proxy-operator` is live on the ARM VPS at `:8091`.
- `proxy-gateway` on the ARM VPS is still serving live customer traffic for:
  - `gpt1` to `gpt5`
  - `sv1`
  - `sv2`
- `portal` (`pricing-hub`) is live on the ARM VPS behind `https://shupremium.com`.
- Old `admin-panel` runtime is stopped and no longer serves public/admin traffic.
- Legacy standalone `balance-checker` on Oracle free-tier still exists, but public balance now also exists inside `portal`.

## Live Architecture

```text
Users
  -> https://shupremium.com
  -> portal / pricing-hub
  -> public tools: pricing, balance, keys, logs, status

Admins
  -> https://admin.shupremium.com
  -> platform-control
  -> pricing admin, proxy admin, deploy jobs, linked launch to shopbot

platform-control
  -> control-plane DB: /home/ubuntu/platform-control/data/platform_control.db
  -> calls proxy-operator at http://127.0.0.1:8091
  -> calls pricing-hub internal admin bridge at http://127.0.0.1:8080

pricing-hub / portal
  -> runtime DB: /home/ubuntu/portal/data/hub.db
  -> keeps pricing cache, group catalog, translations, public registry
  -> imports source metadata/settings from platform-control

shopbot
  -> separate VPS, separate DB/runtime
  -> admin launch via signed SSO token from platform-control
```

## Important Ports / Processes

### ARM VPS
- `8080` -> `portal`
- `8090` -> `platform-control`
- `8091` -> `proxy-operator`

### PM2 on ARM VPS
- `platform-control` -> online
- `portal` -> online
- `proxy-operator` -> online
- `proxy-gpt1..5`, `proxy-sv1..2` -> online
- `admin-panel` -> stopped

## What Was Completed

### 1. Platform-Control became the only admin shell

- `platform-control` now owns:
  - service sources
  - proxy endpoints
  - portal modules
  - pricing admin
  - pricing runtime settings
  - pricing sync history
- linked launch to `shopbot` admin works
- `admin.shupremium.com` is routed to `platform-control`

### 2. Pricing admin parity moved into platform-control

- Added separate pricing admin pages:
  - `Pricing Sources`
  - `Pricing Groups`
  - `Pricing Models`
  - `Pricing Settings`
  - `Pricing Sync Runs`
- Added new source fields in control-plane DB:
  - `sort_order`
  - `quota_multiple`
  - `supports_group_chain`
  - `ratio_config_enabled`
  - `groups_path`
  - `manual_groups`
  - `hidden_groups`
  - `excluded_models`
  - `public_pricing_enabled`
  - `public_balance_enabled`
  - `public_keys_enabled`
  - `public_logs_enabled`
  - `balance_rate`
- Added runtime settings table in control-plane DB:
  - `ai_provider`
  - `ai_api_key`
  - `ai_model`
  - `ai_base_url`
  - `ai_enabled`
  - `auto_sync_enabled`
  - `auto_sync_interval_minutes`
- Added pricing sync history table in control-plane DB.

### 3. pricing-hub stayed runtime-only

- `pricing-hub` remains responsible for:
  - upstream fetch
  - pricing cache
  - group catalog
  - translation cache
  - public pages and APIs
  - key tools
  - usage log tools
- Added internal admin bridge with `PRICING_ADMIN_TOKEN`.
- `platform-control` pushes/imports control-plane state into `pricing-hub`.

### 4. Public source visibility now follows admin settings

- Public dropdowns no longer use plain `enabled`.
- Each public tool respects its own visibility flag:
  - `pricing` -> `public_pricing_enabled`
  - `balance` -> `public_balance_enabled`
  - `keys` -> `public_keys_enabled`
  - `logs` -> `public_logs_enabled`

## Security / Hardening Completed

### CSRF protection for admin

- Added session CSRF token generation and validation in `platform-control`.
- All admin POST routes now require CSRF.
- Admin templates auto-inject CSRF hidden inputs.
- AI test POST from pricing settings also sends CSRF.

### Public logs hardening

- `/api/logs` no longer works in admin-token fallback mode.
- Public log search now requires a real user API key.
- Removed permissive flows that allowed:
  - token-name only lookup
  - accessToken fallback
  - implicit admin-backed log browsing

### Public error sanitization

- Public balance no longer echoes raw transport/upstream exception text.
- Public key/log endpoints now return generic failure messages instead of leaking backend details.

### Public rate limiting

- Added in-memory rate limiting for:
  - `/api/check-balance`
  - `/api/keys/resolve`
  - `/api/keys`
  - `/api/logs`

## Pricing / Ratio Behavior

### Current formulas in public

- `pricing` follows `quota_multiple`
- `balance` follows `balance_rate`
- `logs` follows `quota_multiple` in both:
  - matched pricing path
  - raw fallback estimation path

### Effective behavior

- token pricing shown to users is scaled by `quota_multiple`
- request/fixed pricing shown to users is scaled by `quota_multiple`
- balance checker divides subscription/usage by `balance_rate`
- logs estimated cost now also divides fallback estimates by `quota_multiple`

## Public Pricing Fetch Policy

### Old behavior

- Public request could trigger upstream fetch when RAM cache expired.

### New behavior (implemented)

- Public request no longer triggers upstream pricing fetch.
- Public `pricing`, `keys`, and `logs` now read only from:
  - in-memory cache
  - DB snapshot (`pricing_cache`)
- Only these flows may fetch upstream pricing:
  - manual sync
  - auto-sync poller

### New pricing flow

```text
Admin manual sync / auto-sync poller
  -> fetch upstream pricing
  -> normalize
  -> store pricing_cache snapshot
  -> warm in-memory cache

Public request
  -> read RAM cache
  -> if miss, read DB snapshot
  -> no upstream fetch
```

This means:
- user traffic does not hit upstream pricing servers directly anymore
- admin metadata can still change public output immediately after save/import
- but public traffic itself does not cause upstream refresh

## gpt2 Pricing Incident

- `gpt2` once showed empty pricing because stale `groups_cache` did not match current pricing groups.
- Fixed by ignoring stale group catalogs when they have no intersection with actual pricing groups.
- Result: public pricing now falls back to current normalized pricing instead of blanking everything.

## Local Test Notes

- Local admin login password used during testing:
  - `admin123`
- Local ports used in dev:
  - `8080` -> `pricing-hub`
  - `8090` -> `platform-control`
- Local listeners were stopped after verification unless explicitly restarted.

## Latest VPS Deploy Status

### Already deployed to ARM VPS

- pricing admin parity changes
- public visibility fixes
- CSRF protection
- public logs hardening
- public rate limiting
- logs ratio fallback fix
- snapshot-only public pricing fetch policy
- canonical public group label fix:
  - `Azure` now stays `Azure`
  - public group descriptions are blanked
- server-aware Yunwu pricing display patch:
  - public `sv1` pricing now uses Yunwu frontend-equivalent pricing rules for supported fixed-price families
  - public endpoint display now shows actual path + method from `supported_endpoint` when available

### Recent production config truths

- `platform-control/.env` contains:
  - `CONTROL_PLANE_TOKEN`
  - `PRICING_HUB_URL=http://127.0.0.1:8080`
  - `PRICING_ADMIN_TOKEN`
- `portal/.env` contains:
  - `CONTROL_PLANE_URL=http://127.0.0.1:8090`
  - `CONTROL_PLANE_TOKEN`
  - `PRICING_ADMIN_TOKEN`
- verified production truth on 2026-04-04:
  - `/home/ubuntu/portal/.env` must be:
    - `APP_DEBUG=false`
    - `CONTROL_PLANE_TOKEN=37fbd0bb9a8478a12697312702bc75f9aeb3e62103951a185949c5a989d38c86`
    - `PRICING_ADMIN_TOKEN=53adc45fa24135818d94966f171a93bf5b1311b2a46fbe7b0b394fcb9065fce4`
- `/home/ubuntu/platform-control/.env` holds the same correct control-plane/pricing tokens as above.

Do not overwrite these from local tarballs.

### Recent production recovery notes

- `portal/.env` was accidentally overwritten more than once by a bad local tarball that still contained `.env`.
- `portal/data/hub.db` also became corrupted during deploy attempts.
- working recovery used:
  - backup dir: `/home/ubuntu/portal-backup-20260404-080748`
  - restored DB from `/home/ubuntu/portal-backup-20260404-080748/data/hub.db`
- older backup also exists:
  - `/home/ubuntu/portal-backup-20260404-061525`
- when production breaks after deploy, check in this order:
  1. `portal/.env`
  2. `pm2 logs portal`
  3. `sqlite3 ... 'PRAGMA integrity_check;'`
  4. restore `hub.db` from latest known-good backup

## Server Reality Check

### Actual pricing payload families observed on 2026-04-04

- `gpt2` is the only true `rixapi` / inline-group family in the current fleet.
- `gpt1`, `gpt4`, `gpt5`, `sv1` are all catalog-list payloads, not classic `newapi model_info` dict payloads.

### Actual server family map

- `gpt1` -> catalog-list family
- `gpt2` -> `rixapi` / inline group family
- `gpt4` -> catalog-list family
- `gpt5` -> catalog-list family
- `sv1` -> Yunwu catalog-list family

### Shape highlights

- `gpt1`, `gpt4`, `gpt5`, `sv1` pricing payloads expose top-level keys like:
  - `data`
  - `group_ratio`
  - `usable_group`
  - `supported_endpoint`
  - `vendors`
- `gpt2` pricing payload exposes:
  - `data.group_info`
  - `data.model_info`
  - `vendor_info`

Do not trust admin `type` blindly when reasoning about rendering behavior. Use the real pricing payload shape.

## Yunwu Pricing Notes

### What was verified from live Yunwu assets

- live pricing JSON checked:
  - `https://yunwu.ai/api/pricing_new`
- live pricing pages checked:
  - `https://yunwu.ai/pricing?keyword=aigc-image-gem`
  - `https://yunwu.ai/pricing?keyword=aigc-image-qwen`
  - `https://yunwu.ai/pricing?keyword=aigc-image`
- live frontend bundle checked:
  - `https://assets.wlai.vip/assets/js/index-A6zyR7Tf.js`

### Core finding

- Yunwu pricing display is not driven by `pricing_new` alone.
- The frontend bundle contains a deterministic pricing dispatcher by `quota_type`.
- For many fixed-price multimedia models, the frontend applies a model-specific multiplier on top of `model_price * group_ratio`.

### Confirmed Yunwu frontend pricing behavior

- `quota_type = 0`
  - token pricing
  - uses `model_ratio`, `completion_ratio`, optional `audio_ratio`, `audio_completion_ratio`
- `quota_type = 1`
  - fixed pricing with frontend multiplier
  - formula:
    - `displayed_price = group_ratio * model_price * multiplier`
- `quota_type = 2`
  - fixed pricing:
    - `displayed_price = group_ratio * model_price`
- `quota_type = 3`
  - fixed pricing:
    - `displayed_price = group_ratio * model_price`
- `quota_type = 4`
  - timed pricing
  - special multiplier branch exists for some models such as:
    - `kling-motion-control`
    - `doubao-seedance-2-0`
    - `grok-imagine-video`

### Confirmed Yunwu quota_type=1 multipliers extracted from frontend bundle

- `aigc-image` -> `20`
- `aigc-video` -> `23`
- `aigc-image-gem` -> `30`
- `aigc-image-qwen` -> `30`
- `aigc-image-hunyuan` -> `20`
- `aigc-video-vidu` -> `25`
- `aigc-template-effect-vidu` -> `40`
- `aigc-video-kling` -> `30`
- `aigc-video-hailuo` -> `23`
- `kling-image` -> `2.5`
- `kling-omni-image` -> `20`
- `kling-video` / `kling-omni-video` / `kling-avatar-image2video` -> `100`
- `kling-audio` / `kling-custom-voices` -> `5`
- `kling-effects` -> `200`
- `kling-multi-elements` / `kling-video-extend` -> `100`
- `kling-advanced-lip-sync` -> `50`
- `kling-image-recognize` -> `10`
- `viduq2` -> `18.75`
- `viduq1` -> `62.5`
- `viduq2-turbo` -> `18.75`
- `viduq2-pro` -> `25`
- `viduq3-pro` -> `218.75`
- `viduq3-turbo` -> `125`
- `viduq3` -> `156.25`
- `viduq3-mix` -> `390.625`
- `viduq1-classic` -> `250`
- `vidu2.0` -> `62.5`
- `audio1.0` / `vidu-tts` -> `31.25`
- `MiniMax-Hailuo-02` / `MiniMax-Hailuo-2.3` -> `200`
- `MiniMax-Hailuo-2.3-Fast` -> `135`
- `S2V-01` -> `200`
- `MiniMax-Voice-Clone` -> `990`
- `MiniMax-Voice-Design` -> `200`
- `speech-02-hd` -> `350`
- `speech-02-turbo` -> `200`
- `speech-2.6-hd` -> `350`
- `speech-2.6-turbo` -> `200`
- `speech-2.8-hd` -> `350`
- `speech-2.8-turbo` -> `200`

### Current backend implementation for Yunwu

- new file:
  - `pricing-hub/app/yunwu_pricing.py`
- backend now mirrors the verified Yunwu dispatcher rather than overfitting one model.
- public payload now includes for Yunwu fixed-price models:
  - `billing_label`
  - `billing_unit`
  - `price_multiplier`
- public endpoint display now keeps safe path + method, for example:
  - `/tencent-vod/v1/aigc-image`
  - `POST`

### Important constraint

- Do not invent variant matrices if `pricing_new` does not actually return variant rows.
- The Yunwu frontend can still have richer presentation for some models than the raw API returns.
- Backend should only synthesize what can be justified from:
  - actual pricing payload
  - deterministic frontend pricing rules
  - safe endpoint metadata

## Deployment Rules (must follow)

### Never deploy via broad tarball copy unless exclude rules are verified

- Previous failure cause:
  - local tarball exclude patterns were wrong
  - `.env` and other sensitive files leaked into deploy artifact
- with `tar -C pricing-hub .`, excludes must be relative to that root:
  - use `--exclude=.git`
  - use `--exclude=.env`
  - use `--exclude=.venv`
  - use `--exclude=data`
  - use `--exclude=__pycache__`
- do not use `--exclude=pricing-hub/.env` with `-C pricing-hub .`

### Preferred hotfix method for small runtime patches

- copy only changed files by hand with `scp`
- create a separate patch dir on VPS, for example:
  - `/home/ubuntu/portal-patch-YYYYMMDD`
- back up only the exact files being replaced
- copy only runtime files into `/home/ubuntu/portal`
- never touch:
  - `/home/ubuntu/portal/.env`
  - `/home/ubuntu/portal/data`
  - `/home/ubuntu/portal/.venv`

### Files used in the Yunwu pricing patch deploy on 2026-04-04

- `pricing-hub/app/yunwu_pricing.py`
- `pricing-hub/app/adapters/newapi.py`
- `pricing-hub/app/server_profiles.py`
- `pricing-hub/app/sanitizer.py`
- `pricing-hub/app/schemas.py`
- `pricing-hub/templates/pricing.html`

### Post-deploy verification used successfully

```text
curl -i http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/api/pricing/sv1
```

Expected sample for `aigc-image-gem` after deploy:

```json
{
  "request_price": 0.51,
  "billing_label": "Per image",
  "billing_unit": "image",
  "price_multiplier": 30.0,
  "supported_endpoints": ["/tencent-vod/v1/aigc-image"],
  "endpoint_aliases": [
    {
      "key": "aigc-image",
      "label": "AIGC Image",
      "method": "POST",
      "public_path": "/tencent-vod/v1/aigc-image"
    }
  ]
}
```

### After any pricing-hub deploy

- restart:
  - `pm2 restart portal --update-env`
- verify:
  - `pm2 logs portal --lines 40`
  - `/health`
  - `/`
- then sync pricing snapshots:
  - `gpt1`
  - `gpt2`
  - `gpt4`
  - `gpt5`
  - `sv1`
- save PM2 state:
  - `pm2 save`

## Nginx / Domain Status

- `admin.shupremium.com` -> `platform-control`
- `shupremium.com` -> `portal`
- HTTPS is active through nginx using the existing certificate paths already configured on the ARM VPS.
- `/pricing` was previously blocked at nginx, then re-opened.

## Operational Rules

- Never overwrite production `.env`, `.venv`, or SQLite DB from local deploy tarballs.
- For production deploys:
  - pack locally
  - upload tarball
  - unpack to staging
  - delete `.env`, `.venv`, `data`, `.git`, and dev-only folders from staging
  - copy code into prod paths
  - compile
  - restart services in the right order
- Restart order when both apps change:
  1. `platform-control`
  2. `portal`

## Remaining Legacy / Pending Items

- Old Oracle `balance-checker` still exists and is not fully retired.
- Old `admin-panel` process is stopped but code still exists.
- No CDN/asset pipeline cleanup yet; public pages still rely on current static asset strategy.
- Tailwind CDN warning is still acceptable but not yet production-hardened.

## Recommended Next Steps

1. Keep monitoring public tools after the security + snapshot-only pricing change.
2. If needed, deploy the same patch set to any other environment mirroring ARM VPS.
3. Decide later whether to:
   - freeze admin metadata until sync/poller
   - retire Oracle balance-checker
   - remove old admin-panel code/process completely
