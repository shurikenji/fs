                        +----------------------------------+
                          |          User / Admin            |
                          +----------------------------------+
                                |                     |
                                | public              | admin
                                v                     v
                     +------------------+    +------------------------+
                     |   pricing-hub    |    |   platform-control     |
                     |  public portal   |    |   admin shell / CP     |
                     |   :8080 ARM VPS  |    |   :8090 ARM VPS        |
                     +------------------+    +------------------------+
                              |                         |        |
                              | runtime cache           |        |
                              | + public APIs           |        |
                              v                         |        |
                    +-----------------------+           |        |
                    | pricing-hub DB        |           |        |
                    | data/hub.db           |           |        |
                    +-----------------------+           |        |
                                                        |        |
                                  +---------------------+        +------------------+
                                  |                                         |
                                  v                                         v
                        +-------------------+                    +-------------------+
                        | proxy-operator    |                    | shopbot           |
                        | :8091 ARM VPS     |                    | riêng VPS Ubuntu  |
                        +-------------------+                    | bot + admin + DB  |
                                  |                              +-------------------+
                                  |
                                  v
                        +-------------------+
                        | proxy-gateway /   |
                        | proxy-service     |
                        | gpt1..gpt5 sv1..2 |
                        +-------------------+
Các phần chính

platform-control
Vai trò: admin shell trung tâm, control plane.
Chạy trên ARM VPS, local config mặc định là :8090 trong config.py.
Đây là nơi quản lý:
proxy runtime metadata
service sources
portal modules
pricing admin parity mới
linked launch sang shopbot
DB riêng: data/platform_control.db
Gọi sang:
proxy-operator qua PROXY_OPERATOR_URL
pricing-hub qua PRICING_HUB_URL
shopbot qua signed launch token
pricing-hub
Vai trò: public portal/runtime cho pricing, balance, keys, logs, status.
Chạy trên ARM VPS, local config mặc định :8080 trong config.py.
Đây không còn là admin source-of-truth nữa, mà là runtime/execution layer.
Giữ:
pricing cache
groups cache
translations
public routes/API
key/log/balance tooling
DB riêng: data/hub.db
Đồng bộ state từ platform-control qua internal bridge token.
proxy-gateway / proxy-service
Vai trò: phục vụ traffic proxy khách hàng.
Chạy trên ARM VPS.
Đang có các endpoint sống:
gpt1..gpt5
sv1..sv2
Trong repo proxy-gateway hiện có:
proxy-service: runtime proxy thực tế
proxy-operator: control runtime mới
admin-panel: admin Node cũ, hiện đã dừng
proxy-operator
Vai trò: apply desired state xuống proxy runtime.
Chạy trên ARM VPS :8091.
Được platform-control gọi để:
sync runtime
thao tác nginx/cert/proxy state
Đây là lớp vận hành proxy, không phải UI cho user.
shopbot
Vai trò: commerce runtime riêng, gồm Telegram bot + admin + DB.
Chạy trên VPS Ubuntu riêng.
DB riêng: shopbot.db
Tách hẳn khỏi control plane và portal.
platform-control chỉ launch sang admin của shopbot bằng SSO token bridge, xác nhận trong admin_launch.py.
Ranh giới dữ liệu

platform-control DB:
source of truth cho admin metadata, visibility, runtime settings
pricing-hub DB:
source of truth cho runtime cache/public-facing derived data
shopbot DB:
source of truth cho order, wallet, customer, fulfillment
Proxy runtime:
state triển khai chạy qua proxy-operator + proxy-service
Luồng chính

Admin vào platform-control
platform-control sửa source/settings/visibility
platform-control push/import sang pricing-hub
pricing-hub cập nhật runtime cache/public behavior
platform-control sync proxy qua proxy-operator
platform-control launch sang shopbot khi cần admin commerce
Phần còn legacy/chuyển tiếp

balance-checker cũ vẫn còn chạy trên VPS Oracle free-tier, chưa thay hoàn toàn.
admin-panel cũ trong proxy-gateway/admin-panel vẫn còn code nhưng runtime đã dừng, không còn là admin chính.
Kiến trúc theo domain/runtime

text

admin.shupremium.com
  -> platform-control
  -> linked admin sang shopbot

shupremium.com
  -> pricing-hub public portal/runtime

gpt1..gpt5 / sv1..sv2
  -> proxy-service runtime

bot.shupremium.com
  -> shopbot admin/runtime trên VPS riêng