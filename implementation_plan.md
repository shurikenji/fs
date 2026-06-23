# Platform Control — Full Responsive Redesign

Kế hoạch chỉnh sửa responsive toàn diện cho **toàn bộ** admin portal tại `admin.shupremium.com`, bao gồm tất cả 13 templates và 1 stylesheet.

## Phạm vi kiểm tra

| Page | Template | Đã kiểm tra |
|------|----------|-------------|
| Dashboard `/control` | `dashboard.html` | ✅ Visual + Code |
| Pricing Sources `/control/pricing/sources` | `pricing_sources.html` | ✅ Visual + Code |
| Pricing Groups `/control/pricing/sources/{id}/groups` | `pricing_groups.html` | ✅ Code |
| Pricing Models `/control/pricing/sources/{id}/models` | `pricing_models.html` | ✅ Code |
| Runtime Settings `/control/pricing/settings` | `pricing_settings.html` | ✅ Visual + Code |
| Sync History `/control/pricing/sync-runs` | `pricing_sync_runs.html` | ✅ Visual + Code |
| Audit Logs `/control/logs` | `logs.html` | ✅ Visual + Code |
| System Settings `/control/settings` | `settings.html` | ✅ Visual + Code |
| Status `/status` | `status.html` | ✅ Code |
| Index `/` | `index.html` | ✅ Code |
| Login `/control/login` | `login.html` | ✅ Code |
| Admin Base (shared layout) | `admin_base.html` | ✅ Visual + Code |
| Public Base | `base.html` | ✅ Code |

---

## Tổng quan lỗi phát hiện

### A. Lỗi chung (Global — ảnh hưởng TẤT CẢ trang dùng admin_base.html)

| # | Vấn đề | Mức | Chi tiết |
|---|--------|-----|----------|
| G1 | **Topbar links overlap content** | 🔴 | Portal/Status/Sign Out đè lên page title và content ở ≤768px |
| G2 | **Breakpoint sidebar mâu thuẫn** | 🟠 | `admin_base.html` dùng 900px, `app.css` dùng 980px — sidebar hiện nửa vời ở 900–980px |
| G3 | **Nav toggle `display:none` inline** | 🟠 | Inline style override CSS, hamburger ẩn sai thời điểm |
| G4 | **Topbar flex không wrap** | 🟠 | `topbar__left` và `topbar__right` stack cùng `flex-direction:column` nhưng links không wrap |
| G5 | **Data table min-width: 700px quá lớn** | 🟡 | Nhiều bảng chỉ có 4-5 cột nhưng bị force min-width |

### B. Dashboard `/control` — `dashboard.html`

| # | Vấn đề | Mức |
|---|--------|-----|
| D1 | **Metric grid inline style ghi đè CSS** — `style="grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));"` ngăn media queries | 🔴 |
| D2 | **Content grid `1fr 1fr` inline style** — System Overview + Recent Activity không stack trên tablet | 🔴 |
| D3 | **Card Operator bị cắt** — metric grid 180px min quá nhỏ, không fit 4 card | 🟠 |
| D4 | **Action toolbar text bị cắt** — description text tràn | 🟡 |

````carousel
![Dashboard ở 768px — topbar overlap, Recent Activity bị cắt](C:\Users\arya\.gemini\antigravity\brain\c0614e0e-9468-4162-9e15-66b814eaf9a7\.system_generated\click_feedback\click_feedback_1782161527964.png)
<!-- slide -->
![Dashboard ở 768px — sidebar open che nội dung](C:\Users\arya\.gemini\antigravity\brain\c0614e0e-9468-4162-9e15-66b814eaf9a7\.system_generated\click_feedback\click_feedback_1782161536734.png)
````

### C. Pricing Sources `/control/pricing/sources` — `pricing_sources.html`

| # | Vấn đề | Mức |
|---|--------|-----|
| PS1 | **Page title overlap** — "Pricing Sources" H1 đè lên topbar links "Portal Status Sign Out" | 🔴 |
| PS2 | **Action buttons (New source, Import Runtime, Sync All) wrap không đều** — thiếu gap nhất quán | 🟡 |
| PS3 | **Table 7 cột + Actions cột 330px** — tràn ngang, "Latest sync" và "Actions" bị cắt trên mobile | 🟠 |
| PS4 | **Modal duplicate CSS** — modal styles đã copy vào `<style>` block, trùng lặp với dashboard | 🟡 |

````carousel
![Pricing Sources ở 500px — title overlap topbar links](C:\Users\arya\.gemini\antigravity\brain\c0614e0e-9468-4162-9e15-66b814eaf9a7\.system_generated\click_feedback\click_feedback_1782161875687.png)
<!-- slide -->
![Pricing Sources ở 768px — sidebar overlap](C:\Users\arya\.gemini\antigravity\brain\c0614e0e-9468-4162-9e15-66b814eaf9a7\.system_generated\click_feedback\click_feedback_1782161897411.png)
<!-- slide -->
![Pricing Sources ở 1920px — desktop OK](C:\Users\arya\.gemini\antigravity\brain\c0614e0e-9468-4162-9e15-66b814eaf9a7\.system_generated\click_feedback\click_feedback_1782161966994.png)
````

### D. Pricing Groups — `pricing_groups.html`

| # | Vấn đề | Mức |
|---|--------|-----|
| PG1 | **Filter toolbar inline grid `1fr auto auto auto`** — 4 cột không stack trên mobile | 🟠 |
| PG2 | **Table 6 cột** — cần scroll container | 🟡 |

### E. Pricing Models — `pricing_models.html`

| # | Vấn đề | Mức |
|---|--------|-----|
| PM1 | **Filter toolbar inline grid `1fr 220px auto auto auto`** — 5 cột cứng, vỡ layout trên mobile | 🔴 |
| PM2 | **Table 6 cột** — OK nhưng cần scroll container | 🟡 |

### F. Runtime Settings `/control/pricing/settings` — `pricing_settings.html`

| # | Vấn đề | Mức |
|---|--------|-----|
| RS1 | **Content grid inline `minmax(0, 1.2fr) minmax(320px, 0.8fr)`** — không thể override bằng media query | 🔴 |
| RS2 | **Form grid inline `repeat(2, minmax(0, 1fr))`** — 2 cột cứng, fields quá hẹp trên mobile | 🟠 |
| RS3 | **Buttons flex không wrap** — "Test AI Connection" + "Save Changes" tràn ra ngoài | 🟡 |

### G. Sync History `/control/pricing/sync-runs` — `pricing_sync_runs.html`

| # | Vấn đề | Mức |
|---|--------|-----|
| SH1 | **Filter form inline grid `repeat(5, minmax(0, 1fr)) auto`** — 6 cột cứng, vỡ hoàn toàn trên mobile | 🔴 |
| SH2 | **Table 11 cột** — bảng lớn nhất trong hệ thống, chắc chắn tràn | 🔴 |

### H. Audit Logs `/control/logs` — `logs.html`

| # | Vấn đề | Mức |
|---|--------|-----|
| AL1 | **Table 5 cột với fixed width** — `width:60px`, `width:160px`, `width:120px`, `width:180px` — cứng, không responsive | 🟡 |

### I. System Settings `/control/settings` — `settings.html`

| # | Vấn đề | Mức |
|---|--------|-----|
| SS1 | **Content grid `1fr 1fr` inline style** — 2 cards không stack trên mobile | 🔴 |

### J. Public Pages (index, status) — `index.html`, `status.html`

| # | Vấn đề | Mức |
|---|--------|-----|
| PB1 | **Index: content grid `1fr 1fr` inline style** — không stack | 🟠 |
| PB2 | **Status: header padding `var(--space-8)`** — quá rộng trên mobile | 🟡 |
| PB3 | **Index: main padding `var(--space-8)` + no width:100%** — content không fill screen | 🟡 |

### K. Login — `login.html`

| # | Vấn đề | Mức |
|---|--------|-----|
| — | **Không có lỗi** — Login page responsive tốt (centered card, max-width 440px) | ✅ |

---

## User Review Required

> [!IMPORTANT]
> **Nguyên tắc cốt lõi**: Tất cả inline `style="grid-template-columns: ..."` trên templates sẽ được thay thế bằng CSS classes. Đây là nguyên nhân gốc khiến media queries không thể override layout — inline styles luôn có specificity cao nhất. Thay đổi này ảnh hưởng **8 templates**.

> [!WARNING]
> **Tables trên mobile**: Có 2 cách tiếp cận:
> - **Option A (Đề xuất)**: Giữ bảng scroll ngang bên trong `.table-wrap`, thêm scroll gradient indicator. Đơn giản, không thay đổi HTML.
> - **Option B**: Chuyển bảng sang dạng card-list (mỗi row → 1 card). Phức tạp, thay đổi nhiều template + cần Alpine.js rework.
>
> Tôi sẽ dùng **Option A** trừ khi bạn muốn Option B.

> [!IMPORTANT]
> **Modal CSS hiện tại bị duplicate**: Cùng một bộ `.modal-backdrop`, `.modal-dialog`, `.modal-body`, `.modal-actions`, `.modal-grid-3/4` được copy-paste vào cả `dashboard.html` và `pricing_sources.html`. Tôi đề xuất **di chuyển tất cả modal CSS vào `app.css`** để tập trung quản lý và tránh conflict.

---

## Proposed Changes

### 1. Global Design System — CSS

#### [MODIFY] [app.css](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/static/css/app.css)

**A. Thống nhất breakpoint system**

Thay thế các breakpoint rải rác (820px, 900px, 980px, 1100px, 1320px) bằng hệ thống nhất quán:

```css
/* Breakpoints:
   ≤480px   — Mobile compact
   ≤768px   — Tablet portrait
   ≤1024px  — Tablet landscape / Sidebar collapses
   ≤1280px  — Small desktop
   >1280px  — Full desktop
*/
```

**B. Sidebar — một breakpoint duy nhất `1024px`**
- Xóa rules duplicate ở 980px
- Sidebar collapses + nav-toggle visible ở `≤1024px`

**C. Topbar responsive**
- Flex wrap tại `≤768px`
- Page title lên 1 dòng, links xuống dòng dưới
- Topbar height chuyển `auto` trên mobile

**D. Content grid utility classes** — thay cho inline styles
```css
.content-grid            { grid-template-columns: 1fr 1fr; }
.content-grid--settings  { grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr); }
@media (max-width: 1024px) {
    .content-grid, .content-grid--settings { grid-template-columns: 1fr; }
}
```

**E. Filter/toolbar grid classes** — cho sync-runs, groups, models
```css
.filter-grid-6   { grid-template-columns: repeat(5, minmax(0, 1fr)) auto; }
.filter-grid-4   { grid-template-columns: minmax(0, 1fr) auto auto auto; }
.filter-grid-5   { grid-template-columns: minmax(0, 1fr) 220px auto auto auto; }
@media (max-width: 768px) {
    .filter-grid-6, .filter-grid-4, .filter-grid-5 { grid-template-columns: 1fr; }
}
@media (max-width: 1024px) and (min-width: 769px) {
    .filter-grid-6 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .filter-grid-5 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
```

**F. Form grid classes** — cho settings forms
```css
.form-grid-2 { display: grid; gap: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (max-width: 480px) { .form-grid-2 { grid-template-columns: 1fr; } }
```

**G. Data table improvements**
- `.data-table` giảm `min-width` theo context (auto thay vì 700px fixed)
- `.table-wrap` thêm scroll gradient indicator
- Xóa fixed `width` trên `<th>` — dùng `min-width` thay thế

**H. Modal CSS — chuyển từ inline templates vào app.css**
- Di chuyển `.modal-backdrop`, `.modal-dialog`, `.modal-header`, `.modal-body`, `.modal-actions`, `.modal-grid-*` vào app.css
- Thêm `.modal-grid-2` class
- Thêm `.modal-toggle-grid` class
- Pricing source modal override `.pricing-source-modal` giữ nguyên

**I. Touch targets**
```css
@media (pointer: coarse) {
    .button, .button-secondary, .button-ghost { min-height: 44px; }
    .control, .select-control { min-height: 48px; }
}
```

**J. Action toolbar class**
```css
.action-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--space-3);
}
@media (max-width: 768px) {
    .action-toolbar { flex-direction: column; align-items: stretch; }
    .action-toolbar > * { width: 100%; }
}
```

**K. Page spacing responsive tối ưu**
```css
@media (max-width: 768px) {
    .site-main { padding: var(--space-4) var(--space-3); }
    .page-stack { gap: var(--space-4); }
}
@media (max-width: 480px) {
    .site-main { padding: var(--space-3) var(--space-2); }
    .shell-card, .shell-table, .shell-panel { padding: var(--space-4); }
}
```

---

### 2. Admin Base Layout

#### [MODIFY] [admin_base.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/admin_base.html)

- **Line 120**: Xóa `style="display:none;"` trên nav-toggle → CSS controls visibility
- **Lines 161-194**: Xóa duplicate `<style>` block cho responsive sidebar (giờ nằm trong app.css). Giữ lại status-banner styles nếu chưa có trong app.css.

---

### 3. Dashboard

#### [MODIFY] [dashboard.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/dashboard.html)

- **Line 176**: Xóa `style="grid-template-columns: ..."` trên `.metric-grid`
- **Line 212**: Xóa `style="grid-template-columns: 1fr 1fr;"` trên `.content-grid`
- **Line 252**: Thêm class `action-toolbar` thay cho inline flex styles
- **Lines 436-477**: Xóa `<style>` block (modal CSS di chuyển vào app.css)

---

### 4. Pricing Sources

#### [MODIFY] [pricing_sources.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/pricing_sources.html)

- **Lines 281-383**: Xóa duplicate `<style>` block (modal CSS + responsive rules đã ở app.css)

---

### 5. Pricing Groups

#### [MODIFY] [pricing_groups.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/pricing_groups.html)

- **Line 32**: Thay `style="display:grid; gap:16px; grid-template-columns: minmax(0, 1fr) auto auto auto;"` bằng `class="filter-grid-4"`

---

### 6. Pricing Models

#### [MODIFY] [pricing_models.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/pricing_models.html)

- **Line 30**: Thay `style="display:grid; gap:16px; grid-template-columns: minmax(0, 1fr) 220px auto auto auto;"` bằng `class="filter-grid-5"`

---

### 7. Runtime Settings

#### [MODIFY] [pricing_settings.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/pricing_settings.html)

- **Line 16**: Thay `style="grid-template-columns: ..."` bằng class `content-grid--settings`
- **Line 26**: Thay inline grid style bằng class `form-grid-2`
- **Line 40**: Thay `style="grid-column: span 2;"` bằng class `field-span-full` (responsive: span 2 → span 1 trên mobile)
- **Line 44**: Tương tự line 40
- **Line 50**: Thay inline grid style bằng class `form-grid-2`
- **Line 62**: Thay inline flex bằng class pattern có wrap

---

### 8. Sync History

#### [MODIFY] [pricing_sync_runs.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/pricing_sync_runs.html)

- **Line 29**: Thay `style="display:grid; gap:16px; grid-template-columns: repeat(5, minmax(0, 1fr)) auto;"` bằng class `filter-grid-6`

---

### 9. Audit Logs

#### [MODIFY] [logs.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/logs.html)

- **Lines 23-27**: Xóa fixed `width` trên `<th>` tags — sử dụng CSS `min-width` hoặc để auto

---

### 10. System Settings

#### [MODIFY] [settings.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/settings.html)

- **Line 15**: Xóa `style="grid-template-columns: 1fr 1fr;"` — dùng default `.content-grid` class (đã có responsive rule)

---

### 11. Public Pages

#### [MODIFY] [index.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/index.html)

- **Line 22**: Thêm `width: 100%` vào inline style (hiện thiếu)
- **Line 30**: Xóa `style="grid-template-columns: 1fr 1fr;"` — dùng `.content-grid` class

#### [MODIFY] [status.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/status.html)

- **Line 14**: Thêm responsive padding cho header (hiện `var(--space-8)` quá rộng trên mobile)
- **Line 22**: Thêm `width: 100%` và responsive padding

---

### 12. Login (No changes needed)

#### [SKIP] [login.html](file:///d:/Projects/Code/shupremium-stack/apps/platform-control/templates/login.html)
Login page đã responsive tốt — không cần chỉnh sửa.

---

## Breakpoint Map (After)

```
┌────────────────────────────────────────────────────────────────┐
│  ≤480px (Mobile Compact)                                       │
│  • All grids: 1 column                                        │
│  • Form fields: 1 column, span-2 → span-1                    │
│  • Cards: padding 16px                                        │
│  • site-main: padding 12px 8px                                │
│  • Modals: full-width, all grids → 1 column                  │
│  • Sidebar: off-canvas drawer                                 │
│  • Buttons: min-height 44px                                   │
├────────────────────────────────────────────────────────────────┤
│  ≤768px (Tablet Portrait)                                      │
│  • Metric grid: 2 columns                                     │
│  • Content grid: 1 column                                     │
│  • Filter grids: 1 column                                     │
│  • Topbar: wrap, links below title                            │
│  • Tables: scroll inside card                                 │
│  • Sidebar: off-canvas drawer                                 │
│  • Action toolbar: stacked vertical                           │
│  • Page head: stacked (title + actions vertical)              │
├────────────────────────────────────────────────────────────────┤
│  ≤1024px (Tablet Landscape — Sidebar collapses)                │
│  • Content grid: 1 column                                     │
│  • Filter grids: 2-3 columns                                  │
│  • Modal grids: 2 columns                                     │
│  • Sidebar: off-canvas drawer, nav toggle visible             │
│  • Metric grid: 2-3 columns (auto-fill)                      │
├────────────────────────────────────────────────────────────────┤
│  ≤1280px (Small Desktop)                                       │
│  • Model/admin grids: 3 columns                               │
│  • Toolbar grid: 2 columns                                    │
├────────────────────────────────────────────────────────────────┤
│  >1280px (Full Desktop)                                        │
│  • Full layout — all features visible                         │
│  • Sidebar: fixed left                                        │
│  • All grids: max columns                                     │
└────────────────────────────────────────────────────────────────┘
```

---

## Tổng kết thay đổi

| File | Loại thay đổi | Mô tả ngắn |
|------|---------------|-------------|
| `app.css` | Major | Thêm responsive classes, modal CSS, breakpoint system, scroll indicators |
| `admin_base.html` | Moderate | Xóa inline style nav-toggle, xóa duplicate CSS block |
| `dashboard.html` | Moderate | Xóa 2 inline grid styles, xóa modal CSS block, thêm class |
| `pricing_sources.html` | Minor | Xóa duplicate modal CSS block |
| `pricing_groups.html` | Minor | Thay inline grid → class |
| `pricing_models.html` | Minor | Thay inline grid → class |
| `pricing_settings.html` | Moderate | Thay 3 inline grids + 2 span → classes |
| `pricing_sync_runs.html` | Minor | Thay inline filter grid → class |
| `logs.html` | Minor | Xóa fixed th widths |
| `settings.html` | Minor | Xóa inline grid style |
| `index.html` | Minor | Xóa inline grid, thêm width |
| `status.html` | Minor | Responsive padding |
| `login.html` | None | Đã OK |

**Tổng: 12 files modified, 1 file skipped**

---

## Verification Plan

### Automated Browser Tests
Sau khi implement, chạy browser subagent kiểm tra ở 4 viewport (480px, 768px, 1024px, 1920px) cho:
1. `/control` — Dashboard
2. `/control/pricing/sources` — Pricing Sources (+ mở modal)
3. `/control/pricing/settings` — Runtime Settings
4. `/control/pricing/sync-runs` — Sync History
5. `/control/logs` — Audit Logs
6. `/control/settings` — System Settings

### Checklist cho mỗi viewport:
- [ ] Không horizontal page overflow
- [ ] Topbar links không overlap content
- [ ] Tables scroll bên trong card (không tràn page)
- [ ] Sidebar collapse/expand hoạt động đúng
- [ ] Tất cả metric cards visible
- [ ] Filter forms usable
- [ ] Buttons touch-friendly (≥44px)
- [ ] Modal forms usable
