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

mkdir -p "${TEMP_DIR}"

echo "[1/4] Backing up operator runtime config..."
cp ~/proxy-gateway/proxy-operator/.env "${TEMP_DIR}/proxy-operator.env" 2>/dev/null || echo "  No operator env found"

echo "[2/4] Backing up nginx configs..."
sudo cp -r /etc/nginx/sites-available "${TEMP_DIR}/nginx-sites" 2>/dev/null
sudo cp /etc/nginx/nginx.conf "${TEMP_DIR}/" 2>/dev/null
sudo cp -r /etc/nginx/snippets "${TEMP_DIR}/nginx-snippets" 2>/dev/null

sudo chown -R $USER:$USER "${TEMP_DIR}"

echo "[3/4] Backing up PM2 config..."
cp ~/proxy-gateway/proxy-service/ecosystem.config.js "${TEMP_DIR}/" 2>/dev/null

echo "[4/4] Backing up SSL info..."
sudo certbot certificates > "${TEMP_DIR}/ssl-certificates.txt" 2>/dev/null

mkdir -p "${BACKUP_DIR}"

echo "Compressing..."
cd /tmp
tar -czf "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" "${BACKUP_NAME}"

rm -rf "${TEMP_DIR}"

echo "Cleaning old backups..."
find "${BACKUP_DIR}" -name "backup_*.tar.gz" -mtime +7 -delete

BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1)
echo ""
echo "========================================="
echo "OK: Backup completed"
echo "  File: ${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
echo "  Size: ${BACKUP_SIZE}"
echo "========================================="
