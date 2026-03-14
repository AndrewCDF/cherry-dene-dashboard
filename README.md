# Cherry Dene Dashboard

Office and shed dashboard system for Cherry Dene Farm.

## Included

- `dashboard_server.py`
  Office dashboard Flask app
- `shed_controller_server.py`
  Shed controller Flask app
- `pico_firmware/main.py`
  Pico 2 firmware starter
- `pi_kiosk/`
  Raspberry Pi kiosk and service files
- `pi_templates/`
  Deployment config templates
- `ios/CherryDeneMobile/`
  SwiftUI iPhone/iPad app with Xcode project, native alarm tab, and embedded dashboard views

## Local Run

Office dashboard:

```bash
python3 dashboard_server.py
```

Shed controller:

```bash
python3 shed_controller_server.py
```

## Expected Local Data

These are created locally and should not be committed:

- `data/`
- `controller_data/`

Office backup notes:

- the office dashboard now creates automatic hourly backup ZIPs
- it keeps the newest 6 backups
- default location is `data/backups/`
- to move backups to an SSD later, create `data/office_config.json` with:
  - `{"backup_dir": "/mnt/your-ssd/cherry-dene-backups"}`
- shed controllers also keep automatic hourly local backups and now keep the newest 6
- the office settings page shows the latest synced shed backup status for each controller

## Deployment Notes

- Office Pi runs `dashboard_server.py`
- Office Pi can boot the dashboard as a background service with `pi_kiosk/install_office_service.sh`
- Each shed Pi runs `shed_controller_server.py`
- Each shed Pi can boot into kiosk mode with `pi_kiosk/install_pi_kiosk.sh`
- Pico 2 connects to the shed Pi over USB
- Per-shed controller config comes from `pi_templates/controller_config.template.json`
- Office-to-shed mapping comes from `pi_templates/controllers.template.json`
