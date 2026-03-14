#!/bin/bash
set -eu

APP_DIR="${1:-$HOME/cherry-dene-dashboard}"
USER_NAME="${2:-$(id -un)}"
SHED_NO="${3:-1}"
DASHBOARD_URL="${4:-http://192.168.1.19:8090}"
SYNC_TOKEN="${5:-}"

APP_DIR="$(cd "$APP_DIR" && pwd)"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"

if [ -z "$USER_HOME" ]; then
  echo "Could not determine home directory for user: $USER_NAME" >&2
  exit 1
fi

echo "Installing shed controller for:"
echo "  app dir       : $APP_DIR"
echo "  user          : $USER_NAME"
echo "  user home     : $USER_HOME"
echo "  shed number   : $SHED_NO"
echo "  dashboard url : $DASHBOARD_URL"

sudo apt update
sudo apt install -y python3-flask python3-serial chromium unclutter onboard

mkdir -p "$APP_DIR/controller_data"
mkdir -p "$USER_HOME/.config/autostart"
mkdir -p "$USER_HOME/.config/labwc"

cat > "$APP_DIR/controller_data/controller_config.json" <<EOF
{
  "shed_no": $SHED_NO,
  "dashboard_url": "$DASHBOARD_URL",
  "sync_token": "$SYNC_TOKEN",
  "listen_port": 8091,
  "serial_port": "/dev/ttyACM0",
  "serial_baudrate": 115200,
  "serial_timeout": 1.0,
  "serial_enabled": true,
  "sync_on_sensor_update": true,
  "touch_refresh_seconds": 10,
  "temp_low_c": 18.0,
  "temp_high_c": 24.0,
  "water_low_lpm": 0.1,
  "feed_low_kg": 2000.0,
  "cross_auger_enabled": true,
  "auger_left_enabled": true,
  "auger_right_enabled": true,
  "cross_auger_label": "Cross Auger",
  "auger_left_label": "Auger Left",
  "auger_right_label": "Auger Right"
}
EOF

cat > /tmp/shed-controller.service <<EOF
[Unit]
Description=Shed Controller Flask App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $APP_DIR/shed_controller_server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo install -m 644 /tmp/shed-controller.service /etc/systemd/system/shed-controller.service
rm -f /tmp/shed-controller.service

cat > "$USER_HOME/.config/labwc/autostart" <<EOF
bash $APP_DIR/pi_kiosk/kiosk.sh http://127.0.0.1:8091 &
EOF

cat > "$USER_HOME/.config/autostart/shed-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Shed Controller Kiosk
Exec=$APP_DIR/pi_kiosk/kiosk.sh http://127.0.0.1:8091
X-GNOME-Autostart-enabled=true
EOF

chmod +x "$APP_DIR/pi_kiosk/kiosk.sh"
sudo chown -R "$USER_NAME:$USER_NAME" "$APP_DIR"
sudo chown -R "$USER_NAME:$USER_NAME" "$USER_HOME/.config"

if command -v gsettings >/dev/null 2>&1; then
  su - "$USER_NAME" -c "gsettings set org.onboard auto-show enabled true" >/dev/null 2>&1 || true
fi

sudo systemctl daemon-reload
sudo systemctl enable shed-controller.service
sudo systemctl restart shed-controller.service

echo
echo "Shed controller install complete."
echo "Local URL: http://127.0.0.1:8091"
echo "Service: shed-controller.service"
echo "Reboot recommended to test kiosk startup."
