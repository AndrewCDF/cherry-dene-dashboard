#!/bin/bash
set -eu

APP_DIR="${1:-/home/pi/cherry-dene-dashboard}"

install -m 644 "$APP_DIR/pi_kiosk/office-dashboard.service" "/etc/systemd/system/office-dashboard.service"
systemctl daemon-reload
systemctl enable office-dashboard.service
systemctl restart office-dashboard.service

echo "Installed and started office-dashboard.service"
