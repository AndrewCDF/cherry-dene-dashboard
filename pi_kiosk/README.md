# Raspberry Pi 5 Startup Setup

## Shed controller install

- `shed_controller_server.py`: local Flask controller UI on the Pi
- `pi_kiosk/shed-controller.service`: runs the Flask app at boot
- `pi_kiosk/kiosk.sh`: launches Chromium in fullscreen kiosk mode
- `pi_kiosk/shed-kiosk.desktop`: autostarts the browser into the touch UI

## Shed expected hardware

- Raspberry Pi 5
- Raspberry Pi OS with desktop
- 7 inch LCD touch screen
- Pico 2 connected over USB

## Shed serial protocol from the Pico 2

The controller expects one JSON object per line over USB serial, for example:

```json
{"temp_c": 21.4, "rh_pct": 64.1, "water_lpm": 3.22, "feed_kg": 1840, "light_lux": 320, "pressure_pa": 101233, "status": "Sensors OK", "alarms": []}
```

## Shed first run

Fastest option:

```bash
cd ~/cherry-dene-dashboard
bash ./scripts/install_shed_controller_pi.sh ~/cherry-dene-dashboard andrewcdf 3 http://192.168.1.19:8090
```

This installs packages, writes the shed config, creates the service, and sets up `labwc` kiosk autostart.
It also grants the controller user passwordless access to `shutdown` and `reboot` so the Settings power buttons work cleanly.

1. Copy this project to your Pi home folder, for example `/home/andrewcdf/cherry-dene-dashboard`
2. Install Python dependencies:

```bash
sudo apt update
sudo apt install -y python3-flask python3-serial chromium unclutter onboard
```

3. Start the controller once:

```bash
cd /home/andrewcdf/cherry-dene-dashboard
python3 shed_controller_server.py
```

This creates `controller_data/controller_config.json`.

4. Edit `controller_data/controller_config.json` for your shed:

```json
{
  "shed_no": 3,
  "dashboard_url": "http://192.168.1.10:8090",
  "listen_port": 8091,
  "serial_port": "/dev/ttyACM0",
  "serial_baudrate": 115200,
  "serial_timeout": 1.0,
  "serial_enabled": true,
  "sync_on_sensor_update": false,
  "touch_refresh_seconds": 10
}
```

5. Install the service and kiosk startup:

```bash
cd /home/andrewcdf/cherry-dene-dashboard
sudo bash ./pi_kiosk/install_pi_kiosk.sh /home/andrewcdf/cherry-dene-dashboard andrewcdf
```

If your Pi is using `labwc` / Wayland, add this autostart entry:

```bash
mkdir -p $HOME/.config/labwc
nano $HOME/.config/labwc/autostart
```

Add:

```bash
bash /home/andrewcdf/cherry-dene-dashboard/pi_kiosk/kiosk.sh http://127.0.0.1:8091 &
```

## Shed notes

- The Flask app listens on the configured `listen_port`, default `8091`
- The Chromium kiosk opens `http://127.0.0.1:8091`
- The kiosk script waits a few seconds before launching Chromium so the desktop and Flask app can come up cleanly
- The kiosk script no longer forces `onboard` open at startup
- The kiosk script is tolerant of Wayland/labwc sessions where `xset` may fail
- Numeric/text fields can still request the on-screen keyboard when the Pi desktop auto-show virtual keyboard setting is enabled
- The controller Settings page includes `Shutdown` and `Reboot` buttons; these rely on the installer's sudoers entry
- If your Pico appears on another port, update `serial_port`
- If the dashboard must allocate crop IDs for controller-started crops, keep the updated `dashboard_server.py` running on the farm side

## Office dashboard boot service

If the office Pi should run the dashboard on boot but not launch a kiosk browser, install only the systemd service:

```bash
cd /home/pi/cherry-dene-dashboard
sudo ./pi_kiosk/install_office_service.sh /home/pi/cherry-dene-dashboard
```

This installs:

- `pi_kiosk/office-dashboard.service`

Office notes:

- The office dashboard runs in the background at boot
- No Chromium kiosk is started
- PCs and the smart TV should open `http://OFFICE_PI_IP:8090` over the network
