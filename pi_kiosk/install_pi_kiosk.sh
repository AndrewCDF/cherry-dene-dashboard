#!/bin/bash
set -eu

APP_DIR="${1:-/home/pi/shed-controller}"
USER_NAME="${2:-pi}"

mkdir -p "/home/$USER_NAME/.config/autostart"
mkdir -p "/home/$USER_NAME/.config/lxsession/LXDE-pi"

install -m 755 "$APP_DIR/pi_kiosk/kiosk.sh" "$APP_DIR/pi_kiosk/kiosk.sh"
install -m 644 "$APP_DIR/pi_kiosk/shed-kiosk.desktop" "/home/$USER_NAME/.config/autostart/shed-kiosk.desktop"
install -m 644 "$APP_DIR/pi_kiosk/shed-controller.service" "/etc/systemd/system/shed-controller.service"

if command -v gsettings >/dev/null 2>&1; then
  su - "$USER_NAME" -c "gsettings set org.onboard auto-show enabled true" >/dev/null 2>&1 || true
fi

systemctl daemon-reload
systemctl enable shed-controller.service
systemctl restart shed-controller.service

echo "Installed kiosk autostart, shed-controller.service, and Onboard auto-show if available"
