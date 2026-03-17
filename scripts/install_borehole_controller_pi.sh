#!/bin/bash
set -eu

APP_DIR="${1:-$HOME/cherry-dene-dashboard}"
USER_NAME="${2:-$(id -un)}"
DASHBOARD_URL="${3:-http://192.168.1.19:8090}"
SYNC_TOKEN="${4:-}"
SERVICE_MODE="${5:-kiosk}"

APP_DIR="$(cd "$APP_DIR" && pwd)"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"

if [ -z "$USER_HOME" ]; then
  echo "Could not determine home directory for user: $USER_NAME" >&2
  exit 1
fi

echo "Installing borehole controller for:"
echo "  app dir       : $APP_DIR"
echo "  user          : $USER_NAME"
echo "  user home     : $USER_HOME"
echo "  dashboard url : $DASHBOARD_URL"
echo "  service mode  : $SERVICE_MODE"

sudo apt update
sudo apt install -y python3-flask python3-serial

if [ "$SERVICE_MODE" = "kiosk" ]; then
  sudo apt install -y chromium unclutter onboard
elif [ "$SERVICE_MODE" != "service_only" ]; then
  echo "Unknown service mode: $SERVICE_MODE" >&2
  exit 1
fi

mkdir -p "$APP_DIR/borehole_controller_data"

cat > "$APP_DIR/borehole_controller_data/controller_config.json" <<EOF
{
  "dashboard_url": "$DASHBOARD_URL",
  "sync_token": "$SYNC_TOKEN",
  "listen_port": 8092,
  "touch_refresh_seconds": 1,
  "water_low_lpm": 0.1,
  "water_pulses_per_litre": 450.0,
  "backup_keep": 6
}
EOF

cat > /tmp/borehole-controller.service <<EOF
[Unit]
Description=Borehole Controller Flask App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $APP_DIR/borehole_controller_server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo install -m 644 /tmp/borehole-controller.service /etc/systemd/system/borehole-controller.service
rm -f /tmp/borehole-controller.service

cat > /tmp/cherry-dene-borehole-power <<EOF
$USER_NAME ALL=(root) NOPASSWD: /sbin/shutdown, /usr/sbin/shutdown, /sbin/reboot, /usr/sbin/reboot, /bin/systemctl restart borehole-controller.service, /usr/bin/systemctl restart borehole-controller.service
EOF

sudo install -m 440 /tmp/cherry-dene-borehole-power /etc/sudoers.d/cherry-dene-borehole-power
rm -f /tmp/cherry-dene-borehole-power

if [ "$SERVICE_MODE" = "kiosk" ]; then
  mkdir -p "$USER_HOME/.config/autostart"
  mkdir -p "$USER_HOME/.config/labwc"

  cat > "$USER_HOME/.config/labwc/autostart" <<EOF
bash $APP_DIR/pi_kiosk/kiosk.sh http://127.0.0.1:8092 &
EOF

  cat > "$USER_HOME/.config/autostart/borehole-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Borehole Controller Kiosk
Exec=$APP_DIR/pi_kiosk/kiosk.sh http://127.0.0.1:8092
X-GNOME-Autostart-enabled=true
EOF

  chmod +x "$APP_DIR/pi_kiosk/kiosk.sh"
else
  rm -f "$USER_HOME/.config/autostart/borehole-kiosk.desktop" "$USER_HOME/.config/labwc/autostart"
fi

sudo chown -R "$USER_NAME:$USER_NAME" "$APP_DIR"
if [ -d "$USER_HOME/.config" ]; then
  sudo chown -R "$USER_NAME:$USER_NAME" "$USER_HOME/.config"
fi

if command -v gsettings >/dev/null 2>&1; then
  su - "$USER_NAME" -c "gsettings set org.onboard auto-show enabled true" >/dev/null 2>&1 || true
fi

sudo systemctl daemon-reload
sudo systemctl enable borehole-controller.service
sudo systemctl restart borehole-controller.service

echo
echo "Borehole controller install complete."
echo "Local URL: http://127.0.0.1:8092"
echo "Service: borehole-controller.service"
if [ "$SERVICE_MODE" = "kiosk" ]; then
  echo "Reboot recommended to test kiosk startup."
else
  echo "Controller set up as a background service only."
fi
