#!/bin/bash

# ========================================
# PROXY GATEWAY - BACKUP SCRIPT
# ========================================

BACKUP_DIR="$HOME/proxy-gateway/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="backup_${DATE}"
TEMP_DIR="/tmp/${BACKUP_NAME}"

echo "========================================="
echo "  BACKUP - ${DATE}"
echo "========================================="

# Tạo thư mục temp
mkdir -p "${TEMP_DIR}"

# 1. Backup database
echo "[1/4] Backing up database..."
cp ~/proxy-gateway/admin-panel/data/admin.db "${TEMP_DIR}/" 2>/dev/null || echo "  No database found"

# 2. Backup nginx configs (dùng sudo cp rồi chown)
echo "[2/4] Backing up nginx configs..."
sudo cp -r /etc/nginx/sites-available "${TEMP_DIR}/nginx-sites" 2>/dev/null
sudo cp /etc/nginx/nginx.conf "${TEMP_DIR}/" 2>/dev/null
sudo cp -r /etc/nginx/snippets "${TEMP_DIR}/nginx-snippets" 2>/dev/null

# Chown để user có quyền
sudo chown -R $USER:$USER "${TEMP_DIR}"

# 3. Backup PM2 ecosystem
echo "[3/4] Backing up PM2 config..."
cp ~/proxy-gateway/proxy-service/ecosystem.config.js "${TEMP_DIR}/" 2>/dev/null

# 4. Backup SSL cert info
echo "[4/4] Backing up SSL info..."
sudo certbot certificates > "${TEMP_DIR}/ssl-certificates.txt" 2>/dev/null

# Tạo thư mục backup nếu chưa có
mkdir -p "${BACKUP_DIR}"

# Nén backup
echo "Compressing..."
cd /tmp
tar -czf "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" "${BACKUP_NAME}"

# Xóa temp
rm -rf "${TEMP_DIR}"

# Xóa backups cũ hơn 7 ngày
echo "Cleaning old backups..."
find "${BACKUP_DIR}" -name "backup_*.tar.gz" -mtime +7 -delete

# Kết quả
BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1)
echo ""
echo "========================================="
echo "✓ Backup completed!"
echo "  File: ${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
echo "  Size: ${BACKUP_SIZE}"
echo "========================================="
