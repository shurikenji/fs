#!/bin/bash

# ========================================
# ADMIN IP SYNC - Cập nhật IP Allowlist
# ========================================
# Sử dụng: 
#   ./admin-ip-sync.sh              # Thêm IP hiện tại
#   ./admin-ip-sync.sh 1.2.3.4      # Thêm IP cụ thể
#   ./admin-ip-sync.sh --list       # Xem danh sách IP
#   ./admin-ip-sync.sh --clear      # Xóa tất cả, cho phép all
#   ./admin-ip-sync.sh --remove IP  # Xóa một IP

ALLOWLIST_FILE="/etc/nginx/snippets/admin-allowlist.conf"
BACKUP_FILE="/etc/nginx/snippets/admin-allowlist.conf.bak"

# Màu sắc
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Lấy IP public hiện tại
get_current_ip() {
    curl -s ifconfig.me 2>/dev/null || curl -s icanhazip.com 2>/dev/null || echo ""
}

# Hiển thị danh sách IP
show_list() {
    echo -e "${YELLOW}=== Danh sách IP được phép ===${NC}"
    if [ -f "$ALLOWLIST_FILE" ]; then
        cat "$ALLOWLIST_FILE"
    else
        echo "File không tồn tại"
    fi
    echo ""
}

# Thêm IP vào allowlist
add_ip() {
    local IP=$1
    
    if [ -z "$IP" ]; then
        echo -e "${RED}Lỗi: Không có IP${NC}"
        return 1
    fi
    
    # Validate IP format (basic)
    if ! [[ $IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo -e "${RED}Lỗi: IP không hợp lệ: $IP${NC}"
        return 1
    fi
    
    # Backup
    sudo cp "$ALLOWLIST_FILE" "$BACKUP_FILE" 2>/dev/null
    
    # Kiểm tra IP đã tồn tại chưa
    if grep -q "allow $IP;" "$ALLOWLIST_FILE" 2>/dev/null; then
        echo -e "${YELLOW}IP $IP đã có trong danh sách${NC}"
        return 0
    fi
    
    # Đọc file hiện tại (bỏ dòng allow all và deny all)
    local CURRENT_IPS=$(grep "^allow " "$ALLOWLIST_FILE" 2>/dev/null | grep -v "allow all;")
    
    # Tạo file mới
    {
        echo "# Admin IP Allowlist - Updated $(date '+%Y-%m-%d %H:%M:%S')"
        echo "# IPs được phép truy cập Admin Panel"
        echo ""
        if [ -n "$CURRENT_IPS" ]; then
            echo "$CURRENT_IPS"
        fi
        echo "allow $IP;"
        echo ""
        echo "# Chặn tất cả IP khác"
        echo "deny all;"
    } | sudo tee "$ALLOWLIST_FILE" > /dev/null
    
    # Test nginx config
    if sudo nginx -t 2>/dev/null; then
        sudo nginx -s reload
        echo -e "${GREEN}✓ Đã thêm IP: $IP${NC}"
        echo -e "${GREEN}✓ Nginx đã reload${NC}"
    else
        echo -e "${RED}Lỗi nginx config, đang restore backup...${NC}"
        sudo cp "$BACKUP_FILE" "$ALLOWLIST_FILE"
        sudo nginx -s reload
        return 1
    fi
}

# Xóa một IP
remove_ip() {
    local IP=$1
    
    if [ -z "$IP" ]; then
        echo -e "${RED}Lỗi: Cần chỉ định IP để xóa${NC}"
        return 1
    fi
    
    # Backup
    sudo cp "$ALLOWLIST_FILE" "$BACKUP_FILE" 2>/dev/null
    
    # Xóa dòng chứa IP
    sudo sed -i "/allow $IP;/d" "$ALLOWLIST_FILE"
    
    # Kiểm tra còn IP nào không
    if ! grep -q "^allow [0-9]" "$ALLOWLIST_FILE"; then
        # Không còn IP nào, cho phép all
        {
            echo "# Admin IP Allowlist - Updated $(date '+%Y-%m-%d %H:%M:%S')"
            echo "# Chưa cấu hình - cho phép tất cả"
            echo "allow all;"
        } | sudo tee "$ALLOWLIST_FILE" > /dev/null
        echo -e "${YELLOW}Không còn IP nào, đã mở cho tất cả${NC}"
    fi
    
    sudo nginx -t && sudo nginx -s reload
    echo -e "${GREEN}✓ Đã xóa IP: $IP${NC}"
}

# Xóa tất cả, cho phép all
clear_all() {
    sudo tee "$ALLOWLIST_FILE" > /dev/null << 'INNEREOF'
# Admin IP Allowlist - Cleared
# Cho phép tất cả IP (không khuyến nghị cho production)
allow all;
INNEREOF
    
    sudo nginx -t && sudo nginx -s reload
    echo -e "${GREEN}✓ Đã xóa tất cả IP restrictions${NC}"
    echo -e "${YELLOW}⚠ Admin Panel hiện cho phép tất cả IP truy cập${NC}"
}

# Main
case "$1" in
    --list|-l)
        show_list
        ;;
    --clear|-c)
        clear_all
        ;;
    --remove|-r)
        remove_ip "$2"
        ;;
    --help|-h)
        echo "Admin IP Sync - Quản lý IP Allowlist cho Admin Panel"
        echo ""
        echo "Sử dụng:"
        echo "  $0              Thêm IP hiện tại của bạn"
        echo "  $0 1.2.3.4      Thêm IP cụ thể"
        echo "  $0 --list       Xem danh sách IP"
        echo "  $0 --remove IP  Xóa một IP"
        echo "  $0 --clear      Xóa tất cả, cho phép all"
        echo "  $0 --help       Hiển thị help"
        ;;
    "")
        # Không có tham số - thêm IP hiện tại
        CURRENT_IP=$(get_current_ip)
        if [ -z "$CURRENT_IP" ]; then
            echo -e "${RED}Không thể lấy IP hiện tại${NC}"
            exit 1
        fi
        echo -e "IP hiện tại của bạn: ${YELLOW}$CURRENT_IP${NC}"
        add_ip "$CURRENT_IP"
        ;;
    *)
        # Có tham số - coi như IP
        add_ip "$1"
        ;;
esac
