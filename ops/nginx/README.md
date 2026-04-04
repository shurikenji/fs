# Ghi chú Nginx

Monorepo này không cố quản lý toàn bộ nginx config bằng deploy script.

Lý do:

- nginx hiện là lớp ingress production đang chạy ổn
- thay đổi nginx thường cần review thủ công kỹ hơn deploy code app
- `proxy-gateway` còn có flow tạo config động riêng

Khuyến nghị:

- giữ nginx config production ngoài Git checkout runtime
- nếu muốn chuẩn hóa dần, lưu sample config hoặc snippet tại thư mục này
- chỉ reload nginx sau khi bạn đã kiểm tra config:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

