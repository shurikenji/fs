# Rà soát cài đặt giá Shopbot và đề xuất thống nhất

Ngày kiểm tra: 11/11/2026, múi giờ Asia/Bangkok. Mã nguồn: commit `ba2848f`.

Quyết định sau rà soát: người dùng chọn giữ giá/discount/tier tại Bot. Phần đề xuất gom về Platform Control bên dưới là phương án lịch sử, đã được thay thế bằng quyền quản lý giá riêng tại Shopbot; xem `docs/server.md`.

## 1. Phạm vi và bằng chứng

Đã đọc trực tiếp hai modal **Edit API Source: API1** đang mở trong Chrome:

- `https://admin.shupremium.com/control#service-sources`
- `https://bot.shupremium.com/servers`

Đã cuộn modal bot từ kết nối, xác thực, routing, chính sách chi tiêu đến lịch sử giá và giá mặc định; đã đọc modal admin và bảng nguồn phía sau. Không bấm Save, đổi giá, thêm tier, gọi mua hàng hoặc thay đổi production.

Đã đối chiếu template, route lưu, schema, snapshot đồng bộ, bộ tính giá, caller mua gói/nhập USD, định giá key nhập, ledger chi tiêu, phần cấp quota, công thức Portal và kiểm chứng có sẵn. Không đọc database production hay xác minh commit đang triển khai trên máy chủ; vì vậy phát hiện runtime dựa trên mã local được ghi rõ bên dưới.

Không dùng Jev: các phép quy đổi và thứ tự thực thi được xác định trực tiếp từ mã.

## 2. Những gì đang hiển thị trên website

### API1 trong hai modal

| Thuộc tính | Admin | Bot |
|---|---|---|
| Tên | API1 | API1 |
| Source ID / server ID | `API1` | `#7`, có nhãn Managed by platform-control |
| API type | newapi | NewAPI |
| Upstream | Đã cấu hình | Cùng upstream đang hiển thị |
| Public URL | `https://api1.shupremium.com` | Không có trường riêng trong modal |
| Giá/đơn vị | 4.100 VND | 4.100 VND, nhãn Price / $1 |
| USD/đơn vị | 1 | 1 |
| Quota/đơn vị | 500.000 | 500.000, nhãn Quota / $1 |
| Hệ số quota bot | 0,5 | 0,5 |
| Balance rate | 0,5 | Không có trường riêng |
| Default group | default | default |
| Bật bot | Có | State: Enabled |
| Tích lũy từ key nhập | Tắt | Tắt |
| Token ID lookup | Bật | Bật |
| Key-vault backup | Bật | Không có trường tương ứng trong modal |
| Chế độ ưu đãi | Không có điều khiển nhìn thấy | Best Benefit Only |
| Tier | Không có trình soạn | Chưa có tier |
| Lịch sử giá | Không có | #2 hệ số 0,5; #1 hệ số 1,0 |

Lịch sử bot hiển thị #2 hiệu lực `2026-08-21 13:27:25`, #1 `2026-08-21 13:26:17`. Bảng này không hiển thị USD/đơn vị, nên riêng cột Price / $1 chưa đủ để chứng minh tỷ giá thật của mọi phiên bản.

Admin hiển thị 2 nguồn: API1 và Server 4. Bot hiển thị 6 server, 2 enabled; API1 và Server 4 có nhãn centrally managed, 4 dòng còn lại không có nhãn này. Đây là dấu hiệu cần rà mapping dữ liệu cũ khi hợp nhất, không phải căn cứ để xóa chúng.

Dashboard admin hiển thị Shopbot sync `healthy`, desired 36 / applied 36. Chỉ số này chưa chứng minh phiên bản giá mà quote sử dụng cũng đã cập nhật.

## 3. Danh mục đầy đủ các thành phần trong hai modal

### 3.1 Modal admin: nguồn và hồ sơ Shopbot

| Thành phần | Trường / vai trò | Liên quan giá |
|---|---|---|
| API Source ID | `source_id`, bất biến khi sửa | Định danh liên kết; không dùng server ID số làm định danh chung |
| Display name | `name` | Tên trên giao diện |
| API Source type | `source_type` | Chọn adapter upstream |
| Upstream base URL | `upstream_base_url` | Nguồn gọi API |
| Public base URL | `public_base_url` | URL public; sync bot ưu tiên URL này cho `base_url` |
| Balance rate | `balance_rate` | Quy đổi số dư Portal; không phải giá VND |
| Auth mode | `auth_mode` | Xác thực khi lấy dữ liệu/gọi nguồn |
| Header name/value | `auth_user_header`, `auth_user_value` | Xác thực nguồn |
| Token / Cookie | `auth_token`, `auth_cookie` | Bí mật; admin giữ nguyên khi để trống lúc sửa |
| Enable in shopbot | Có/xóa hồ sơ `shopbot_source_profiles` | Điều kiện nguồn có mặt trong snapshot bot |
| Import spend accrual | `import_spend_accrual_enabled` | Cho cộng giá trị quota key nhập vào chi tiêu |
| Token ID key lookup | `supports_key_lookup_by_id` | Khả năng lấy key đầy đủ, không phải hệ số giá |
| Key-vault backup | `key_backup_enabled` | Cấu hình worker kho key riêng |
| Price / unit | `shopbot_price_per_unit` → `price_per_unit` | VND cho một đơn vị cấu hình |
| Quota / unit | `shopbot_quota_per_unit` → `quota_per_unit` | Quota cơ sở của một đơn vị, trước hệ số bot |
| Shopbot quota multiplier | `shopbot_quota_multiple` | Hệ số quota cấp bởi bot, tách biệt Portal |
| Dollar / unit | `shopbot_dollar_per_unit` → `dollar_per_unit` | USD danh nghĩa của một đơn vị |
| Default group | `shopbot_default_group` | Group mặc định; sản phẩm có thể ghi đè |
| Enabled | `enabled` | Bật nguồn chung |
| Public pricing | `public_pricing_enabled` | Quyền công khai pricing Portal |
| Public balance | `public_balance_enabled` | Quyền tra số dư public |
| Cancel / đóng / Save Changes | Hành động modal | Lưu nguồn rồi lưu profile và tăng revision |

Ba trường **ẩn** trong template admin vẫn được submit: `shopbot_discount_stack_mode`, `shopbot_discount_allowed_stack_types`, `shopbot_token_key_endpoint_template`. Người dùng không chỉnh được trực tiếp trong modal đang mở. Giá trị mặc định lần lượt `exclusive`, `cashback`, `/api/token/{id}/key`.

Route admin còn nhận `pricing_path`, `ratio_config_path`, `log_path`, `token_search_path`, `notes`; đây là cấu hình nguồn liên quan khả năng lấy dữ liệu, không phải giá bán. Cấu hình mở rộng nằm ở màn Pricing API Sources, không được phép bỏ qua khi hợp nhất registry.

### 3.2 Modal bot: kết nối và routing

- Core Connection: Source Name, Base URL, API Type (`newapi`, `rixapi`, `other`).
- Authentication: Auth Strategy (`header`, `bearer_only`, `cookie`, `none`), User Header Name, User Identifier, Access Token, Cookie; một số trường bị ẩn/được chuẩn hóa theo API type.
- Supports multi-group policies.
- Supports resolving the full key from a token ID và Token ID Lookup Endpoint.
- Advanced Routing: Groups Endpoint, Manual Group List, Custom Headers JSON.
- Với NewAPI, route lưu ép auth header `new-api-user`, bỏ custom headers/cookie/groups endpoint trong payload của nhánh này. RixAPI ép multi-group, header `rix-api-user`, tắt ID lookup. Vì vậy không thể coi mọi ô template là có cùng hiệu lực cho mọi API type.

### 3.3 Modal bot: Spend Tier Policy

| Điều khiển | Dữ liệu / ý nghĩa |
|---|---|
| Add Tier | Thêm tier theo nguồn/server |
| Imported keys contribute to spend | Cờ tích lũy key nhập |
| Runtime Strategy | `exclusive` hoặc `combine_selected_types` |
| Allowed Combined Benefits | Chọn `percent_off`, `fixed_off`, `cashback`, `tier_price` |
| Presets | Cashback Only; Fixed + Cashback; Percent + Cashback; Tier Price + Cashback |
| Summary | Thông báo các loại đang được cộng; báo không áp dụng khi exclusive |
| Tier Name | Tên bậc |
| Minimum Spend (VND) | `min_spend_vnd`, tổng chi tiêu trên chính server đó |
| Tier Status / Pause / Resume | `is_active` |
| Remove Tier | Xóa tier khỏi bản cấu hình đang soạn |
| Add Benefit | Thêm quyền lợi trong tier |
| Benefit Type | 4 loại nói trên |
| Value | % hoặc VND tùy loại; với tier price còn có fallback backend |
| Cashback Mode | `percent` hoặc `fixed` |
| Price Per $1 | `config.price_per_dollar` cho tier price |
| Benefit Status | `is_active` riêng của quyền lợi |
| Remove Benefit | Xóa quyền lợi; builder tự thêm quyền lợi giảm 5% nếu xóa hết |
| Open Advanced JSON | `discount_tiers_json`: cấu trúc tier và mảng benefits |

Builder không cung cấp điều khiển sắp xếp thứ tự quyền lợi dù backend có thể phụ thuộc thứ tự mảng. Preset chỉ chọn loại được cộng dồn, không tự tạo toàn bộ quyền lợi cho tier.

### 3.4 Modal bot: giá, lịch sử và trạng thái

- Pricing Version History: Version, Effective From, Price / $1, Quota / $1, Quota Multiplier.
- Pricing Defaults: `price_per_unit`, `quota_per_unit`, `dollar_per_unit`, `quota_multiple`.
- Default Group, Preview Groups, kết quả group preview.
- State Enabled/Paused, Cancel/đóng, Save Changes.
- DB phiên bản giá còn có `rounding_mode`, `rounding_step`, `min_payable_amount`, tên, hiệu lực và trạng thái. Hai modal không có trình chỉnh đầy đủ các mục này.

## 4. Công thức thực tế

Ký hiệu: P = `price_per_unit` VND; D = `dollar_per_unit`; Q = `quota_per_unit`; M = hệ số quota **bot**; x = USD khách mua; q = quota upstream; B = giá gốc; A = phải trả; C = cashback.

### 4.1 Bot: quy đổi USD, quota, VND

```text
Tỷ giá bán VND/USD = P / D
Quota cấp cho 1 USD = Q / D × M
Quota cấp cho x USD = int(x × Q / D × M)
USD từ quota q = q × D / Q / M
Giá gốc từ x USD = max(0, làm_tròn(x × P / D))
Giá gốc từ quota q = quy_đổi_VND(quy_đổi_USD(q))
```

`int` bỏ phần lẻ; với quota dương tương đương làm tròn xuống. `_round_value` hỗ trợ floor/ceil/round theo bước. `round` của Python làm tròn hòa về số chẵn: 2,5 → 2; 3,5 → 4. Mặc định bước 1 VND. Phép tính hiện dùng float.

Runtime có các fallback: Q tối thiểu 1; D và M tối thiểu 0,0001 trong helper; mặc định D = 10, M = 1 khi thiếu. Một số caller dùng `or` nên giá trị 0 bị thay bằng mặc định. Đây không phải validation dữ liệu đầu vào hợp lệ.

**API1 đang mở:** P=4.100, D=1, Q=500.000, M=0,5 → 1 USD = 4.100 VND và 250.000 quota. Mua 10 USD → 41.000 VND, 2.500.000 quota trước ưu đãi. Đây là kết quả số học từ bộ trường UI, chưa phải giao dịch thực tế.

Nhãn “Price / $1” chỉ đúng khi D=1. Nếu P=31.000 và D=10 thì tỷ giá thật là 3.100 VND/USD. Tương tự, nhãn “Quota / $1” bỏ qua cả D và M.

### 4.2 Thứ tự lấy giá/quota cho sản phẩm API

1. Có `custom_dollar`: tính giá và quota từ USD nhập theo phiên bản giá.
2. Nếu không, có `custom_quota`: tính USD và giá từ quota.
3. Nếu dùng product: lấy `quota_amount`, `dollar_amount`, `price_vnd` của product.
4. Chỉ suy ra USD nếu USD <= 0 và quota > 0; chỉ suy ra quota nếu quota <= 0 và USD > 0.
5. `price_vnd > 0` của product được ưu tiên hơn công thức giá server. Chỉ khi giá product <= 0 mới suy ra từ USD/quota.
6. Nếu cả quota và USD product đều dương nhưng không khớp, resolver giữ cả hai; không tự chuẩn hóa lại.

Hệ quả: đổi giá server không tự cập nhật giá cố định của toàn bộ gói. Cần hiển thị rõ gói dùng giá riêng, không mô tả mọi gói là tự kế thừa giá server.

### 4.3 Chọn tier và người được hưởng

- Tổng chi tiêu là theo `(user_id, server_id)`, không phải toàn bộ shop.
- Chọn tier active có `min_spend_vnd <= current_spend`, lấy ngưỡng cao nhất.
- Khi trùng ngưỡng, ưu tiên `sort_order DESC`, rồi `id DESC`.
- Chỉ đọc benefits active của tier đã chọn, theo ID tăng dần; không cộng benefits của tất cả tier thấp hơn.
- Đọc chi tiêu trước đơn hiện tại; đơn đạt ngưỡng mới không tự nâng tier ngay trong chính lần báo giá đó.
- Admin và user có `disable_discounts` bỏ qua ưu đãi. Không nhập user ID thì policy mặc định cho phép discounts.

### 4.4 Bốn loại quyền lợi

| Loại | Công thức |
|---|---|
| Percent Off | giảm = min(B, max(0, round(B × value / 100))); A = B − giảm |
| Fixed Discount | giảm = min(B, max(0, int(value))); A = B − giảm |
| Cashback % | C = max(0, round(B × value / 100)); không giảm A lúc trả |
| Cashback cố định | C = max(0, int(value)); không giảm A lúc trả |
| Tier Price | giá riêng = max(0, round(x × giá_VND_mỗi_USD)); giảm được ghi nhận = max(0, B − giá riêng) |

Tier price ưu tiên `config.price_per_dollar`; nếu không có dùng `benefit.value`; sau đó mới đến cặp `config.price_per_unit` / `config.dollar_per_unit`. Với nhánh còn quota có fallback đổi theo phiên bản đã override. Các nhánh `round` trực tiếp của tier price không dùng đầy đủ rounding_step/mode như helper giá cơ sở.

Cashback hiện không bị chặn tối đa theo A/B. Giá trị 200% được helper tính ra 200% thật; không chỉ là lời nhắc UI 0–100.

### 4.5 Chế độ áp dụng ưu đãi

**Exclusive:** đánh giá từng benefit độc lập trên B; chọn benefit có `A − C` nhỏ nhất, chỉ khi thấp hơn giá trị tốt nhất trước đó. Trường hợp bằng nhau giữ lựa chọn trước; không mặc định ưu tiên giảm tiền ngay. Ví dụ B=100.000, giảm 10% và cashback 20% → thu đủ 100.000, hoàn 20.000, thay vì thu 90.000.

**Combine Selected Types:** lọc theo danh sách loại được cho phép. Nếu có tier price, chỉ dùng tier price đầu tiên rồi chỉ giữ cashback; percent/fixed bị bỏ. Nếu không có tier price, duyệt các benefit theo thứ tự lưu:

- Percent/fixed lần lượt giảm trên số phải trả hiện tại.
- Cashback % tính trên số phải trả tại thời điểm gặp cashback; các cashback được cộng.
- Vì thế giảm 10% → cashback 10% trên B=100.000 cho C=9.000; đảo thứ tự cashback → giảm thì C=10.000. A cả hai là 90.000.
- Tier price cao hơn B không làm tăng tiền thu ở quote cuối: discount bị chặn dưới 0, sau đó A = B − discount.

### 4.6 Số lượng, giới hạn và snapshot đơn hàng

- Gói nhiều sản phẩm: quote một sản phẩm trước, rồi nhân giá gốc, phải trả, giảm, cashback, spend credit, quota, USD với số lượng. Giảm cố định vì thế được nhân theo số lượng, không phải chỉ giảm một lần cho cả đơn.
- Mua key mới yêu cầu tối thiểu 10 USD; topup tối thiểu 1 USD trong các caller được đọc.
- Luồng nhập USD áp tối thiểu 1.000 VND sau ưu đãi; QR chỉ hiện từ 10 USD, dưới đó dùng ví.
- `min_payable_amount` được lưu ở phiên bản nhưng resolver không đọc nó; luồng product được đọc không có clamp 1.000 VND tương tự. Không nên coi giới hạn đó là chính sách tập trung hiện có.
- Đơn ghi `base_amount`, `discount_amount`, `cashback_amount`, `spend_credit_amount`, `pricing_version_id`, `applied_tier_id`, pricing/promotion snapshot.
- Luồng nhập USD ghi `custom_quota` đã quote. Luồng product đã đọc không ghi quota quote vào `custom_quota`; phần cấp key/topup dùng `order.custom_quota` hoặc `product.quota_amount` hiện tại. Vì vậy cần khóa quota đơn hàng để thay đổi gói trong lúc đơn chờ không làm lệch hàng giao. Đây là rủi ro từ đường mã local, chưa thử giao dịch production.

### 4.7 Tích lũy chi tiêu

```text
Chi tiêu cộng khi hoàn tất đơn API = spend_credit_amount (fallback amount)
Chi tiêu sau cộng/đảo = max(0, chi tiêu trước + bút toán)
Hoàn đơn đã ghi nhận = bút toán âm đảo phần chi tiêu đó
```

Spend credit thông thường là tiền phải trả, không trừ cashback. Các ghi nhận có khóa chống lặp theo nguồn/tham chiếu.

Với key nhập và cờ tích lũy được bật:

```text
Tổng quota quan sát = max(0, remain_quota + used_quota)
Quota mới được ghi nhận = max(0, tổng quan sát − tổng đã ghi nhận)
Chi tiêu cộng = vnd_from_quota(quota mới, phiên bản giá)
```

Có khóa chủ sở hữu key, kiểm tra payload, chống cộng lại cùng tổng, chặn khi topup đang đối soát; quota do nền tảng cấp được cập nhật baseline để không cộng lặp. Giá trị này là giá trị quy đổi để xét tier, không phải bằng chứng khách đã trả tiền mua key bên ngoài tại shop.

### 4.8 Các hệ số Portal phải phân biệt với bot

Ký hiệu Mp = `service_sources.quota_multiple`, Rb = `balance_rate`, r = model ratio, c = completion ratio, g = group ratio, k = cache ratio.

```text
Giá input / 1M token = 2 × g × r / Mp
Giá output / 1M token = 2 × g × r × c / Mp
Giá cached input / 1M = 2 × g × r × k / Mp (nếu có k)
Giá fixed/request = model_price × g × hệ_số_profile / Mp
```

Các giá được làm tròn 6 chữ số; variant/group snapshot cũng được scale. Nhánh Yunwu có hệ số từng model và đơn vị request/image/video/audio/second riêng, trong `apps/portal/app/yunwu_pricing.py`; không chuyển bảng hiệu chuẩn đó thành hệ số bán USD bot.

Log estimate ưu tiên bảng giá normalized: `prompt_tokens/1M × input_price + completion_tokens/1M × output_price`; fixed/request-scaled dùng request price. Fallback raw: `g × r × (prompt + completion × c)/(500000 × Mp)`; nếu fixed thì `g × model_price/Mp`; nếu chỉ có quota thì `q/(500000 × Mp)`. Đây là ước tính hiển thị, không phải phép quyết toán đầy đủ mọi cơ chế billing/cache upstream.

Balance Portal từ billing API: `limit = hard_limit_usd/Rb`; `usage = total_usage/100/Rb`; `balance = max(0, limit − usage)`. Fallback token: số dư/đã dùng/tổng = quota tương ứng `/ (500000 × Rb)`.

Một số hiển thị, cảnh báo và backup của bot dùng `q/(500000 × M)` thay vì helper tổng quát `q × D/(Q × M)`. Hai công thức chỉ trùng khi `Q/D = 500000`. API1 đang mở đáp ứng điều kiện này; cấu hình khác có thể lệch giữa báo giá và số dư/cảnh báo.

## 5. Các vấn đề cần giải quyết

### A. Có UI chỉnh sửa nhưng backend cấm lưu nguồn managed — đã xác nhận mã và UI

`apps/shopbot/admin/routers/servers.py:599`: edit, toggle, delete và lưu group đều chặn `control_plane_source_id`. Tuy nhiên modal vẫn hiện ô sửa, Add Tier và Save Changes. Người dùng không biết thao tác nào thật sự có hiệu lực.

### B. Tier bị bỏ lửng giữa hai nơi — đã xác nhận mã

Central DB/profile chưa chứa danh sách tier/benefits, snapshot bot không mang tier. Admin chỉ giữ chế độ stack và allowed types dưới dạng field ẩn. Nơi có tier editor là bot, nhưng nguồn managed lại không lưu được tại đó. Chỉ ẩn modal bot sẽ làm thiếu chức năng; phải chuyển cả dữ liệu và trình soạn tier.

### C. Revision đồng bộ không đảm bảo phiên bản giá đang dùng — rủi ro cao từ mã local

`control_plane_sync.apply_snapshot` update `api_servers`, không tạo/sync `server_pricing_versions`. `quote_api_order` và key valuation ưu tiên phiên bản active có sẵn, chỉ sync nếu không có phiên bản. Có thể xảy ra: bảng server/UI đã có giá mới, quote/định giá key vẫn dùng giá cũ. Chưa đổi giá production để tái hiện; không kết luận API1 hiện đang bị lệch.

### D. Trạng thái re-enable chưa hội tụ — đã xác nhận đường mã

Snapshot chỉ gồm source enabled và có profile. Nguồn managed biến mất thì bot bị set `is_active=0`. Khi xuất hiện lại, `_server_values` giữ trạng thái cũ, nên có thể vẫn tắt; toggle tại bot lại bị chặn. Cần định nghĩa trạng thái bán hàng tại central và đồng bộ rõ ràng, tránh dùng cờ enabled chung cho mọi ý nghĩa.

### E. Đơn vị và các hệ số chưa thể hiện đúng vai trò

Price/unit, USD/unit, quota/unit, hệ số bot, hệ số pricing Portal, balance rate, group ratio là các khái niệm khác nhau. Hai cột bot mang nhãn “/$1” trong khi backend dùng P/D và Q/D×M. Không gộp các hệ số này thành một ô chung vì trông giống nhau về số.

### F. Giá gói có thể đứng ngoài thay đổi giá server

Product.price_vnd cố định được ưu tiên. Product.quota và USD cùng dương không được kiểm tra nhất quán. Quota fulfillment cần snapshot tại đơn. Chuyển UI mà không chỉ ra gói override sẽ tiếp tục khiến người quản trị tưởng đã đổi giá nhưng giá bán thực tế không đổi.

### G. Cộng dồn ưu đãi chưa có thứ tự cố định

Đã tái hiện cashback phụ thuộc thứ tự bằng helper thực tế. UI không có mô hình thứ tự rõ ràng. Cashback không có giới hạn giá trị theo tiền thu; mức %/ngưỡng/loại chưa được validation đầy đủ ở trust boundary của đường lưu đã đọc.

### H. Giá tối thiểu và làm tròn nằm rải rác

DB có min payable nhưng resolver bỏ qua; caller nhập USD tự áp clamp. Giá cơ sở theo mode/step nhưng nhiều quyền lợi dùng round trực tiếp. Chính sách tối thiểu phải phân biệt QR/ngân hàng với ví, hiển thị rõ trước khi lưu.

### I. Lưu cấu hình chưa là một thao tác nguyên tử đầy đủ

Route admin lưu source rồi profile qua các hàm commit riêng; mỗi thao tác bump revision. Chưa có bảo đảm một revision thể hiện toàn bộ thay đổi source + giá + tier như một cấu hình duy nhất. Luồng lưu legacy bot cũng update server, sync version, replace tiers thành các bước riêng.

### J. Còn nguồn legacy và cấu hình Portal mở rộng

Trang bot đang có 4 dòng không mang nhãn centrally managed. Sync chỉ quản lý nguồn có link, không tự xóa tất cả legacy. Bên admin còn Pricing API Sources cùng chỉnh registry nguồn và các trường pricing/group/model visibility. Hợp nhất cần inventory và map chính xác, giữ ID đơn hàng và server lịch sử.

## 6. Một giải pháp thống nhất được đề xuất

**Chỉ một nơi ghi cấu hình: Platform Control → API Sources → chi tiết nguồn.** Dùng trang chi tiết thay modal dài. Bot là consumer cấu hình và màn quan sát trạng thái thực thi.

### Danh sách nguồn

Mỗi dòng: Source ID, tên, trạng thái bán bot, **VND/1 USD thực tế**, **quota cấp/1 USD thực tế**, số tier, số gói override, revision mong muốn/đã áp dụng, phiên bản giá bot đang dùng, lỗi gần nhất. Mở một nguồn là đi tới chi tiết đầy đủ.

### Trang chi tiết gồm 5 phần

1. **Kết nối:** upstream/public URL, adapter, auth, endpoint, multi-group, manual group, ID lookup, backup. Giữ bí mật theo cơ chế chỉ ghi mới, không render giá trị token có sẵn.
2. **Giá bán bot:** hiển thị và chỉnh VND/1 USD; thông số quota/unit, USD/unit và M giữ trong phần nâng cao, hiển thị ngay quota cấp/1 USD. Kèm rounding/minimum cùng ý nghĩa chính xác; không tự đổi bộ dữ liệu cũ để ép D=1 nếu chưa đối chiếu toàn bộ product và caller.
3. **Ưu đãi và chi tiêu:** chuyển tier builder hiện có về đây, đầy đủ active, threshold, benefit, mode, allowed types, cashback mode/amount, giá tier, tích lũy key nhập. Ẩn phần chọn stack khi exclusive. Tier price loại trừ percent/fixed; cashback chạy sau toàn bộ giảm giá theo quy tắc cố định được ghi rõ.
4. **Gói và Portal:** danh sách gói đang liên kết, giá kế thừa hay giá riêng, USD/quota/group; khối Portal riêng cho Mp, balance rate, catalog/group/model visibility và các endpoint. Có thể chia tab Bot/Portal trong cùng trang, dùng chung một source registry.
5. **Kiểm tra và lịch sử:** nhập USD + chi tiêu hiện có hoặc chọn khách để xem quote; hiện từng bước giá gốc, tier, giảm, phải trả, cashback, quota giao, spend credit, group, version. Bên cạnh có bản đang chạy/bản vừa lưu, thời điểm ACK và trạng thái lỗi.

Ví dụ xem trước API1 không ưu đãi: “10 USD → 41.000 VND → 2.500.000 quota”. Preview phải gọi cùng bộ tính giá runtime, không viết công thức JS thứ hai.

### Quy tắc backend cần đi cùng UI

- Dùng lại registry, `shopbot_source_profiles`, snapshot checksum/revision, pricing resolver và ledger hiện có; không thêm service quản lý giá mới.
- Thêm lưu trữ central cho tiers/benefits và đưa toàn bộ policy vào snapshot có version.
- Lưu source/profile/tiers trong một transaction, bump một revision sau khi hợp lệ.
- Apply bot trong một transaction: cập nhật server + policy + tạo pricing version mới nếu bộ giá đổi + đánh dấu applied. Chỉ ACK sau khi commit thành công toàn bộ.
- Revision ACK cần xác minh cả pricing version và policy hash đang được runtime sử dụng. Có heartbeat/thời điểm ACK, không chỉ chữ healthy.
- Chỉ đọc quote từ bản giá/policy đã áp dụng nhất quán; snapshot đủ dữ liệu ở đơn để đổi cấu hình không làm đổi quota/giá đơn cũ.
- Tách cờ nguồn hoạt động, bật bán bot và public Portal; enable lại phải hội tụ theo central.
- Quy định cố định thứ tự cộng dồn và làm tròn; validation server-side cho số hữu hạn, P/D/Q/M hợp lệ, tỷ lệ %, ngưỡng, loại benefit, cấu hình stack và quota giới hạn API. Chính sách cashback cao hơn số thu phải có quy định rõ, không ngầm cho phép vì thiếu validation.
- Giá gói: giữ giá cố định cũ khi migrate, đánh dấu override; nếu muốn kế thừa cần thao tác rõ ràng, không chuyển hàng loạt âm thầm.
- Chuẩn hóa helper chuyển quota/USD cho quote, số dư, cảnh báo và backup theo calibration thực tế; giữ hệ số Portal và balance tách tên/ý nghĩa.
- Bot `/servers` đổi thành xem cấu hình thực tế, group preview, version và link “Chỉnh tại Platform Control”. Không để nút sửa/lưu không có hiệu lực cho nguồn managed.

### Lộ trình tối thiểu hoàn chỉnh

1. Inventory/mapping toàn bộ 6 server bot, 2 source central, product, tiers và phiên bản giá; đối chiếu bản đang chạy. Giữ ID legacy và lịch sử, không xóa vì đang paused.
2. Bổ sung central policy + transaction + apply tạo pricing version; kiểm tra re-enable, ACK, lỗi đồng bộ và retry.
3. Đưa tier builder và preview về trang chi tiết nguồn; bổ sung giá thực tế và cảnh báo gói override.
4. Đối chiếu các quote mẫu trước/sau; sau khi mọi nguồn được map và chức năng central đầy đủ mới bỏ đường chỉnh legacy bot và đường ghi registry trùng.

Không đưa thêm nhiều chế độ override/multi-master giữa admin và bot: chúng sẽ giữ nguyên sự khó theo dõi hiện tại. Không hợp nhất ba hệ số bằng cách tự động chép giá trị giữa chúng.

## 7. Kiểm chứng đã thực hiện

- Chạy `python verification/verify_discount_ledger.py` trong `apps/shopbot`: **PASS**, dùng database tạm do script tạo. Bao gồm quote giá gốc, ghi nhận chi tiêu một lần, tier theo server, admin bypass, nhập key không cộng trùng, chủ sở hữu, platform baseline, phiên bản giá, promotion sản phẩm thường, user tắt discount và audit ledger.
- Chạy các hàm thuần trích trực tiếp từ AST của resolver: **PASS** cho bộ API1, ưu tiên giá product, exclusive theo net cost, cashback phụ thuộc thứ tự, cashback 200% và round hòa về số chẵn. Không import cấu hình hoặc gọi API cho phép kiểm tra này.
- Đã xem UI, không submit thay đổi và không tạo đơn production.
- Các kiểm chứng hiện có không chứng minh central sync cập nhật pricing version; việc test sync hiện thiếu được phân biệt với ca test cập nhật server chủ động gọi `sync_server_pricing_version`.

## 8. Tệp mã tham chiếu chính

- `apps/platform-control/templates/dashboard.html`: modal nguồn, các field profile ẩn.
- `apps/platform-control/app/app.py:671`: route lưu nguồn + Shopbot profile.
- `apps/platform-control/db/queries.py:169`: snapshot nguồn cho bot.
- `apps/platform-control/db/database.py:324`: schema Shopbot profile central.
- `apps/platform-control/app/pricing_admin.py:285`: đường sửa registry qua Pricing API Sources.
- `apps/shopbot/admin/templates/_server_edit_modal.html`: modal bot.
- `apps/shopbot/admin/templates/servers.html:566`: tier builder và stack picker.
- `apps/shopbot/admin/routers/servers.py:599`: chặn sửa managed; các action group/toggle/delete cùng chính sách.
- `apps/shopbot/bot/services/control_plane_sync.py:34`: mapping source sang server; `:112`: apply snapshot.
- `apps/shopbot/db/queries/pricing.py:104`: sync version; `:215`: chọn tier.
- `apps/shopbot/bot/services/pricing_resolver.py:62`: quy đổi/làm tròn; `:117`: ưu tiên giá; `:187`: benefit; `:330`: quote API.
- `apps/shopbot/bot/handlers/flow_api_key.py:785`: luồng nhập USD và clamp tối thiểu.
- `apps/shopbot/bot/handlers/catalog.py:185`: nhân quote theo số lượng; `:590`: tạo đơn gói.
- `apps/shopbot/bot/services/key_valuation.py`: tích lũy key nhập và baseline.
- `apps/shopbot/bot/services/spend_ledger.py`: chi tiêu và đảo chi tiêu.
- `apps/shopbot/bot/services/payment_poller.py:258`: cấp key; `:486`: topup và nguồn quota giao.
- `apps/shopbot/bot/utils/formatting.py:30`, `key_alert_poller.py`, `key_backup_poller.py`: quy đổi dùng mốc 500.000.
- `apps/portal/app/adapters/base.py:88`, `newapi.py:441`, `app/cache.py:62`: chuẩn hóa giá model và hệ số Portal.
- `apps/portal/app/log_pricing.py:142`: ước tính log.
- `apps/portal/app/routers/public_balance.py:60`: quy đổi số dư.
- `apps/portal/app/yunwu_pricing.py`: calibration/đơn vị riêng Yunwu.

Giới hạn: chưa đọc DB/commit production, chưa kiểm tra toàn bộ giá trị của từng source/product trên website, chưa thử save/checkout. Những điểm rủi ro runtime cần xác minh trên staging trước triển khai; tài liệu này là rà soát và thiết kế, chưa thay đổi ứng dụng.
