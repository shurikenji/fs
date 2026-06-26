# Giải Pháp Tổng Thể Cho Các Vấn Đề Key Backup

## Summary

Hoàn thiện phần Key Backup sau bản triển khai đầu tiên bằng cách: thêm cấu hình web còn thiếu, giữ riêng interval của backup và alert, chuẩn hóa cách hiển thị/lưu key có `sk-`, và cải thiện search để tìm được cả key full lẫn key masked.

Không cần đổi schema vì các setting và bảng backup đã tồn tại.

## Key Changes

- Trong Bot Settings, tab `Scanner & Alerts`, thêm section `Key Backup Snapshots` gồm:
  - checkbox `key_backup_enabled`
  - input `key_backup_interval_min`
  - input `key_backup_retention_days`
- Cập nhật settings save flow:
  - thêm `key_backup_interval_min`, `key_backup_retention_days` vào danh sách editable
  - lưu `key_backup_enabled=false` khi checkbox bị bỏ chọn
- Giữ `key_alert_poll_interval_min` và `key_backup_interval_min` tách riêng:
  - Alert interval: chu kỳ đánh giá/gửi Telegram cho key đã bán
  - Backup interval: chu kỳ fetch toàn bộ token upstream để tạo snapshot
  - Alert vẫn dùng backup-first, API fallback như hiện tại

## Key Normalization & Search

- Chuẩn hóa `_normalize_key_fields` để mọi key hiển thị/lưu trong backup đều có dạng `sk-...`:
  - server trả full key `abc` -> `key_value=sk-abc`, `key_masked=sk-...`
  - server trả masked key `TPhU**********AdnC` -> `key_value=None`, `key_masked=sk-TPhU**********AdnC`
  - server trả full key đã có `sk-` thì giữ nguyên
- Dùng một helper chung cho key backup search/match:
  - strip `sk-` khi so sánh nội bộ
  - exact/substring match cho key full, token name, group, token id
  - prefix+suffix match khi keyword là full key nhưng backup item là masked key
- Cập nhật admin key backup search để nhập một phần key, full key, hoặc key không có `sk-` đều tìm được item phù hợp.

## Test Plan

- Thêm/cập nhật verification cho settings:
  - render trang settings có các field backup mới
  - submit checkbox enabled/disabled lưu đúng `true/false`
  - interval và retention được save vào DB
- Cập nhật `verify_key_backup.py`:
  - full key không có `sk-` được lưu thành `sk-...`
  - masked key không có `sk-` được hiển thị thành `sk-...`
  - search full key match được masked backup item bằng prefix+suffix
  - search substring vẫn match token name/key/group/token id
- Chạy:
  - `python apps/shopbot/verification/verify_key_backup.py`
  - `python apps/shopbot/verification/verify_phase4_admin.py`
  - `python apps/shopbot/verification/verify_key_alert_poller.py`

## Assumptions

- Không gộp alert interval và backup interval.
- Không migrate dữ liệu backup cũ; các snapshot mới sau deploy sẽ được normalize chuẩn.
- `implementation_plan.md` được thay bằng bản tiếng Việt rõ ràng, không giữ phần mojibake cũ.
