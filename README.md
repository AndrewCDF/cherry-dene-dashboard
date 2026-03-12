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

## Deployment Notes

- Office Pi runs `dashboard_server.py`
- Each shed Pi runs `shed_controller_server.py`
- Pico 2 connects to the shed Pi over USB
- Per-shed controller config comes from `pi_templates/controller_config.template.json`
- Office-to-shed mapping comes from `pi_templates/controllers.template.json`
