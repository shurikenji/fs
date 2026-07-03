# Báo cáo Kiểm tra UI & Kế hoạch Tối ưu

## Tổng quan kiểm tra

Tôi đã mở trực tiếp website shupremium.com và kiểm tra từng trang. Dưới đây là kết quả:

---

## ✅ Các trang đã ổn

### Landing page (`/`)
- "Available servers", "Browse all servers", "enabled servers" — ✅ đã đổi hết
- Layout đẹp, không có vấn đề

### Pricing Explorer (`/pricing`)
- Label dropdown: **"Server"** — ✅
- Subtitle: "Inspect public model pricing by **server**..." — ✅
- **Search query giữ lại khi đổi server** — ✅ verified (gõ "gpt" → đổi sang Server 2 → query vẫn còn)

### Key Tools (`/keys`)
- Label: **"Server"**, description: "Select a **server**..." — ✅

### Usage Logs (`/logs`)
- Label: **"Server"**, description: "Pick a **server**..." — ✅

---

## ⚠️ Vấn đề phát hiện — Balance Check (`/check`)

Trang Balance Check hoạt động nhưng có **nhiều vấn đề UI/UX cần tối ưu**:

### Vấn đề 1: Tab switcher bị wrap 2 dòng trên mobile

![Tab switcher bị wrap](file:///C:/Users/arya/.gemini/antigravity-ide/brain/03ff7f92-4d6b-43a4-96a5-ceb7a5ea6f56/check_1_key_tab_1783062342911.png)

Tab "Multi-Key, Multi-Server" bị rớt xuống dòng thứ 2. Trên mobile viewport, 3 tab không đủ chỗ nằm 1 hàng.

**Fix**: Rút gọn label tab:
- "Check 1 Key" → **"Single"**
- "Multi-Key, 1 Server" → **"Bulk"**
- "Multi-Key, Multi-Server" → **"Multi-Server"**

Hoặc dùng icon + text ngắn, hoặc cho phép scroll horizontal.

---

### Vấn đề 2: Single mode dùng `toolbar-grid` — Server và Key nằm cạnh nhau

Trên mobile, Server dropdown và API key input xếp dọc ổn, nhưng trên desktop chúng nằm ngang (toolbar-grid) khiến layout khác biệt so với các trang Keys/Logs nơi chúng xếp dọc. Nên **thống nhất layout dọc** cho cả 3 tab.

---

### Vấn đề 3: Mapping table (Multi-Server tab) — thiếu cột Remove header & horizontal scroll

![Mapping table](file:///C:/Users/arya/.gemini/antigravity-ide/brain/03ff7f92-4d6b-43a4-96a5-ceb7a5ea6f56/parsed_mapping_table_1783062424188.png)

- Table bị horizontal scroll trên mobile → UX kém
- Cột "Remove" header text + nút "Remove" text dài, chỉ cần icon ✕
- Dòng "Add another key" input + "Add key" button + "Set unassigned to server" dropdown + "Apply" button đều xếp ngang → **bị vỡ layout hoàn toàn trên mobile**

---

### Vấn đề 4: Khu vực "Add key" + "Set all to server" bị vỡ mobile

Khu vực dưới table: `controls-row` chứa input + button + dropdown + button nằm cùng 1 hàng `justify-content: space-between` — trên mobile bị chồng chéo, xấu.

---

### Vấn đề 5: Khi đổi tab, results/error cũ vẫn còn

Nếu user check xong ở tab Single, rồi chuyển sang tab Multi-Key → results/summary/error cũ vẫn hiển thị. Nên **clear results khi đổi tab**.

---

### Vấn đề 6: Nút "Parse keys" trông disabled quá mờ

Nút "Parse keys" khi textarea rỗng bị disabled nhưng style quá mờ, user có thể không nhận ra cần paste key trước.

---

### Vấn đề 7: Thiếu key count indicator

Khi user paste keys vào textarea (cả Multi-Key và Multi-Server tab), không có chỉ số đếm bao nhiêu key đã paste. Nên hiển thị "X keys detected" realtime.

---

### Vấn đề 8: Results table thiếu color coding cho balance

Trong results table, balance values chỉ hiển thị text thuần. Nên:
- Balance > 0: **màu xanh (success)**
- Balance = 0 hoặc error: **màu đỏ (danger)**

---

### Vấn đề 9: Thiếu nút Export CSV cho bulk results

Trang Logs có Export CSV, nhưng bulk balance check không có. Sẽ hữu ích khi check 20 keys.

---

## Kế hoạch Tối ưu

### Phase 1: Fix Layout & Responsive (ưu tiên cao)

#### [MODIFY] [balance.html](file:///d:/Projects/Code/shupremium-stack/apps/portal/templates/balance.html)

**1.1 — Tab switcher responsive**
```diff
- "Check 1 Key" → "Single"
- "Multi-Key, 1 Server" → "Bulk"
- "Multi-Key, Multi-Server" → "Multi-Server"
```
Thêm `flex-wrap: nowrap; min-width: 0;` cho container và `flex: 1 1 0; min-width: 0; text-align: center;` cho mỗi button.

**1.2 — Single mode layout thống nhất**
- Bỏ `toolbar-grid`, dùng `display: grid; gap: var(--space-4);` xếp dọc giống Multi-Key tab
- Server dropdown → full width
- API key input → full width

**1.3 — Mapping table responsive**
- Bỏ cột # (không cần thiết)
- Cột "Remove" → dùng icon ✕ button thay vì text "Remove"
- Ẩn header "Remove", dùng `aria-label`
- Table thêm `table-layout: fixed` để không bị overflow

**1.4 — "Add key" + "Set all" section responsive**
- Tách thành 2 hàng riêng biệt trên mobile:
  - Hàng 1: Input "Add another key" + button "Add"
  - Hàng 2: Dropdown "Set all to server" + button "Apply"
- Dùng `@media (max-width: 640px)` để stack dọc

### Phase 2: UX Improvements

**2.1 — Clear results khi đổi tab**
```javascript
switchMode(mode) {
    this.mode = mode;
    this.error = '';
+   this.results = [];
+   this.summary = null;
}
```

**2.2 — Key count indicator**
- Thêm realtime counter dưới textarea: `<span x-text="parsedBulkKeys().length + ' keys detected'"></span>`
- Kèm warning nếu > 20 keys

**2.3 — Balance color coding trong results**
```html
<td :style="'color: ' + (parseFloat(row.balance_usd) > 0 ? 'var(--success)' : 'var(--danger)')">
```

**2.4 — Export CSV cho bulk results**
- Thêm nút "Export CSV" bên cạnh results heading
- Logic tương tự trang Logs

**2.5 — Cải thiện "Parse keys" button visibility**
- Khi textarea có nội dung, button đổi sang primary style thay vì secondary

### Phase 3: Polish

**3.1 — Thêm toast notification khi copy hoặc export xong**

**3.2 — Loading progress cho bulk**
- Thay vì "Checking..." đơn giản, hiển thị "Checking 3/20..." với progress realtime (cần backend stream hoặc estimate)

---

## Thứ tự triển khai đề xuất

| # | Task | Impact | Effort |
|---|------|--------|--------|
| 1 | Tab labels ngắn hơn + responsive | 🔴 High | Low |
| 2 | Single mode layout dọc | 🟡 Medium | Low |
| 3 | Mapping table responsive + icon ✕ | 🔴 High | Medium |
| 4 | "Add key" + "Set all" section responsive | 🔴 High | Low |
| 5 | Clear results khi đổi tab | 🟡 Medium | Trivial |
| 6 | Key count indicator | 🟡 Medium | Low |
| 7 | Balance color coding | 🟢 Low | Trivial |
| 8 | Export CSV | 🟡 Medium | Low |
| 9 | Parse keys button visibility | 🟢 Low | Trivial |
