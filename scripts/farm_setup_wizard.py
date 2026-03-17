#!/usr/bin/env python3
import json
import os
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception as exc:
    raise SystemExit("Tkinter is required for the farm setup wizard: %s" % exc)


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = BASE_DIR / "pi_templates"
DEFAULT_OUTPUT_ROOT = BASE_DIR / "generated_farm_setups"


def load_json(path):
    with open(path, "r") as handle:
        return json.load(handle)


FARM_TEMPLATE = load_json(TEMPLATE_DIR / "farm_setup.template.json")
CONTROLLER_TEMPLATE = load_json(TEMPLATE_DIR / "controller_config.template.json")
BOREHOLE_CONTROLLER_TEMPLATE = {
    "dashboard_url": "http://127.0.0.1:8090",
    "sync_token": "",
    "mode_switch_pin": "1234",
    "listen_port": 8092,
    "touch_refresh_seconds": 1,
    "water_low_lpm": 0.1,
    "water_pulses_per_litre": 450.0,
    "backup_keep": 6,
}
SYSTEM_TYPE_LABELS = {
    "dashboard": "Office Dashboard",
    "shed": "Shed Controller",
    "water": "Water Controller",
    "other": "Custom Bundle",
}
DEPLOYMENT_MODE_LABELS = {
    "commissioning": "Commissioning",
    "live": "Live",
}
SERVICE_MODE_LABELS = {
    "kiosk": "Kiosk + Service",
    "service_only": "Service Only",
}


def slugify(text):
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    return cleaned or "farm"


def default_farm_id():
    return str(FARM_TEMPLATE.get("farm_id") or slugify(FARM_TEMPLATE.get("farm_name", "farm"))).strip()


def parse_shed_numbers(raw_text):
    out = []
    for part in str(raw_text or "").replace(" ", "").split(","):
        if not part:
            continue
        out.append(str(int(part)))
    deduped = []
    for shed_no in out:
        if shed_no not in deduped:
            deduped.append(shed_no)
    return deduped


def parse_host_number(raw_value):
    host = int(str(raw_value or "").strip())
    if host < 1 or host > 254:
        raise ValueError("Controller IP start host must be between 1 and 254.")
    return host


def normalise_ip_base(raw_value, fallback_ip=""):
    value = str(raw_value or "").strip()
    if value:
        value = value.rstrip(".")
        parts = value.split(".")
        if len(parts) != 3 or any(not part.isdigit() for part in parts):
            raise ValueError("Controller IP base must look like 192.168.1")
        return value

    fallback = str(fallback_ip or "").strip()
    parts = fallback.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return ".".join(parts[:3])
    return ""


def suggest_controller_ip(base_ip, start_host, shed_no):
    base_ip = str(base_ip or "").strip().rstrip(".")
    if not base_ip:
        return ""
    return "%s.%s" % (base_ip, int(start_host) + int(shed_no) - 1)


def commissioning_mode_enabled(deployment_mode):
    return str(deployment_mode or "").strip().lower() == "commissioning"


def serial_enabled_for_shed(shed_payload):
    keys = [
        "temp_sensor_enabled",
        "water_meter_enabled",
        "feed_bin_enabled",
        "cross_auger_enabled",
        "auger_left_enabled",
        "auger_right_enabled",
    ]
    return any(bool(shed_payload.get(key)) for key in keys)


def format_equipment_list(payload):
    equipment = []
    if payload.get("temp_sensor_enabled"):
        equipment.append("Temp")
    if payload.get("water_meter_enabled"):
        equipment.append("Flow")
    if payload.get("feed_bin_enabled"):
        equipment.append("Feed")
    if payload.get("cross_auger_enabled"):
        equipment.append("Cross")
    if payload.get("auger_left_enabled"):
        equipment.append("Left")
    if payload.get("auger_right_enabled"):
        equipment.append("Right")
    return equipment or ["None"]


def build_farm_setup_payload(form_data):
    farm = deepcopy(FARM_TEMPLATE)
    farm["farm_id"] = form_data["farm_id"]
    farm["farm_name"] = form_data["farm_name"]
    farm["deployment_mode"] = form_data["deployment_mode"]
    farm["commissioning_mode"] = commissioning_mode_enabled(form_data["deployment_mode"])
    farm["controller_service_mode"] = form_data["controller_service_mode"]
    farm["mode_switch_pin"] = str(form_data["mode_switch_pin"]).strip()
    farm["planning"] = {
        "controller_ip_base": form_data["controller_ip_base"],
        "controller_ip_start": int(form_data["controller_ip_start"]),
    }

    farm["office"]["dashboard_ip"] = form_data["dashboard_ip"]
    farm["office"]["dashboard_port"] = int(form_data["dashboard_port"])
    farm["office"]["dashboard_url"] = "http://%s:%s" % (
        form_data["dashboard_ip"],
        int(form_data["dashboard_port"]),
    )
    farm["office"]["farm_id"] = form_data["farm_id"]
    farm["office"]["farm_name"] = form_data["farm_name"]

    farm["sheds"] = {}
    for shed in form_data["sheds"]:
        shed_no = str(int(shed["shed_no"]))
        shed_payload = {
            "farm_id": form_data["farm_id"],
            "farm_name": form_data["farm_name"],
            "controller_ip": shed["controller_ip"],
            "controller_port": 8091,
            "serial_port": "/dev/ttyACM0",
            "touch_refresh_seconds": 1,
            "temp_low_c": 18.0,
            "temp_high_c": 24.0,
            "water_low_lpm": 0.1,
            "feed_low_kg": 2000.0,
            "temp_sensor_enabled": bool(shed["temp_sensor_enabled"]),
            "water_meter_enabled": bool(shed["water_meter_enabled"]),
            "feed_bin_enabled": bool(shed["feed_bin_enabled"]),
            "cross_auger_enabled": bool(shed["cross_auger_enabled"]),
            "auger_left_enabled": bool(shed["auger_left_enabled"]),
            "auger_right_enabled": bool(shed["auger_right_enabled"]),
            "cross_auger_label": "Cross Auger",
            "auger_left_label": "Auger Left",
            "auger_right_label": "Auger Right",
            "serial_enabled": False,
            "deployment_mode": form_data["deployment_mode"],
            "commissioning_mode": commissioning_mode_enabled(form_data["deployment_mode"]),
            "service_mode": form_data["controller_service_mode"],
            "mode_switch_pin": str(form_data["mode_switch_pin"]).strip(),
        }
        shed_payload["serial_enabled"] = serial_enabled_for_shed(shed_payload)
        farm["sheds"][shed_no] = shed_payload

    farm["borehole"]["enabled"] = bool(form_data["borehole_enabled"])
    farm["borehole"]["controller_ip"] = form_data["borehole_ip"]
    farm["borehole"]["service_mode"] = form_data["controller_service_mode"]
    farm["borehole"]["deployment_mode"] = form_data["deployment_mode"]
    farm["borehole"]["commissioning_mode"] = commissioning_mode_enabled(form_data["deployment_mode"])
    farm["borehole"]["mode_switch_pin"] = str(form_data["mode_switch_pin"]).strip()
    farm["borehole"]["farm_id"] = form_data["farm_id"]
    farm["borehole"]["farm_name"] = form_data["farm_name"]
    return farm


def build_office_controllers_payload(farm_setup):
    controllers = {}
    for shed_no, shed in sorted(farm_setup["sheds"].items(), key=lambda item: int(item[0])):
        controllers[shed_no] = {
            "sync_url": "http://%s:%s" % (shed["controller_ip"], int(shed.get("controller_port", 8091))),
            "sync_token": "",
            "label": "Shed %s" % shed_no,
        }
    borehole = farm_setup.get("borehole", {})
    if borehole.get("enabled") and str(borehole.get("controller_ip", "")).strip():
        controllers["borehole"] = {
            "sync_url": "http://%s:%s" % (borehole["controller_ip"], int(borehole.get("controller_port", 8092))),
            "sync_token": "",
            "label": "Bore Hole",
        }
    return controllers


def build_controller_config_payload(farm_setup, shed_no):
    shed = farm_setup["sheds"][str(int(shed_no))]
    cfg = deepcopy(CONTROLLER_TEMPLATE)
    cfg["farm_id"] = str(farm_setup.get("farm_id", shed.get("farm_id", "")) or "")
    cfg["farm_name"] = str(farm_setup.get("farm_name", shed.get("farm_name", "")) or "")
    cfg["shed_no"] = int(shed_no)
    cfg["dashboard_url"] = farm_setup["office"]["dashboard_url"]
    cfg["sync_token"] = ""
    cfg["mode_switch_pin"] = str(farm_setup.get("mode_switch_pin", shed.get("mode_switch_pin", "1234")) or "1234")
    cfg["listen_port"] = int(shed.get("controller_port", 8091))
    cfg["serial_port"] = shed.get("serial_port", "/dev/ttyACM0")
    cfg["serial_enabled"] = bool(shed.get("serial_enabled", True))
    cfg["touch_refresh_seconds"] = int(shed.get("touch_refresh_seconds", 1))
    cfg["temp_low_c"] = float(shed.get("temp_low_c", 18.0))
    cfg["temp_high_c"] = float(shed.get("temp_high_c", 24.0))
    cfg["water_low_lpm"] = float(shed.get("water_low_lpm", 0.1))
    cfg["feed_low_kg"] = float(shed.get("feed_low_kg", 2000.0))
    cfg["cross_auger_enabled"] = bool(shed.get("cross_auger_enabled", True))
    cfg["auger_left_enabled"] = bool(shed.get("auger_left_enabled", True))
    cfg["auger_right_enabled"] = bool(shed.get("auger_right_enabled", True))
    cfg["cross_auger_label"] = str(shed.get("cross_auger_label", "Cross Auger"))
    cfg["auger_left_label"] = str(shed.get("auger_left_label", "Auger Left"))
    cfg["auger_right_label"] = str(shed.get("auger_right_label", "Auger Right"))
    cfg["deployment_mode"] = farm_setup.get("deployment_mode", "commissioning")
    cfg["commissioning_mode"] = bool(farm_setup.get("commissioning_mode", True))
    cfg["service_mode"] = shed.get("service_mode", "kiosk")
    cfg["temp_sensor_enabled"] = bool(shed.get("temp_sensor_enabled", True))
    cfg["water_meter_enabled"] = bool(shed.get("water_meter_enabled", True))
    cfg["feed_bin_enabled"] = bool(shed.get("feed_bin_enabled", False))
    return cfg


def build_borehole_controller_config_payload(farm_setup):
    borehole = farm_setup.get("borehole", {})
    cfg = deepcopy(BOREHOLE_CONTROLLER_TEMPLATE)
    cfg["farm_id"] = str(farm_setup.get("farm_id", borehole.get("farm_id", "")) or "")
    cfg["farm_name"] = str(farm_setup.get("farm_name", borehole.get("farm_name", "")) or "")
    cfg["dashboard_url"] = farm_setup["office"]["dashboard_url"]
    cfg["sync_token"] = ""
    cfg["mode_switch_pin"] = str(farm_setup.get("mode_switch_pin", borehole.get("mode_switch_pin", "1234")) or "1234")
    cfg["deployment_mode"] = farm_setup.get("deployment_mode", "commissioning")
    cfg["commissioning_mode"] = bool(farm_setup.get("commissioning_mode", True))
    cfg["service_mode"] = borehole.get("service_mode", "kiosk")
    return cfg


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def write_shell_script(path, text):
    write_text(path, text)
    os.chmod(path, 0o755)


def build_office_config_payload(farm_setup):
    return {
        "farm_id": str(farm_setup.get("farm_id", "") or ""),
        "farm_name": str(farm_setup.get("farm_name", "") or ""),
    }


def build_setup_sheet(farm_setup, system_type):
    lines = [
        "Cherry Dene Setup Sheet",
        "",
        "Bundle type: %s" % SYSTEM_TYPE_LABELS.get(system_type, system_type),
        "Farm ID: %s" % farm_setup.get("farm_id", "--"),
        "Farm: %s" % farm_setup["farm_name"],
        "Office dashboard: %s" % farm_setup["office"]["dashboard_url"],
        "Deployment mode: %s" % DEPLOYMENT_MODE_LABELS.get(farm_setup.get("deployment_mode"), farm_setup.get("deployment_mode", "")),
        "Controller runtime: %s" % SERVICE_MODE_LABELS.get(farm_setup.get("controller_service_mode"), farm_setup.get("controller_service_mode", "")),
        "Mode PIN: %s" % str(farm_setup.get("mode_switch_pin", "1234")),
        "Sync token: (blank)",
        "",
        "Office Pi",
        "- IP: %s" % farm_setup["office"]["dashboard_ip"],
        "- Port: %s" % farm_setup["office"]["dashboard_port"],
    ]

    if farm_setup["sheds"]:
        lines.extend(["", "Shed controllers"])
        for shed_no, shed in sorted(farm_setup["sheds"].items(), key=lambda item: int(item[0])):
            lines.extend([
                "- Shed %s -> %s | Equipment: %s | Serial: %s" % (
                    shed_no,
                    shed["controller_ip"],
                    ", ".join(format_equipment_list(shed)),
                    "on" if shed.get("serial_enabled") else "off",
                )
            ])

    borehole = farm_setup.get("borehole", {})
    if borehole.get("enabled") and str(borehole.get("controller_ip", "")).strip():
        lines.extend([
            "",
            "Water controller",
            "- Bore hole -> %s" % borehole["controller_ip"],
        ])

    lines.extend([
        "",
        "Generated at: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
    ])
    return "\n".join(lines)


def build_install_notes(farm_setup, output_dir):
    lines = [
        "Cherry Dene Farm Setup Export",
        "",
        "This bundle is set up for:",
        "- Farm ID: %s" % farm_setup.get("farm_id", "--"),
        "- Farm Name: %s" % farm_setup.get("farm_name", "--"),
        "- Deployment mode: %s" % DEPLOYMENT_MODE_LABELS.get(farm_setup.get("deployment_mode"), farm_setup.get("deployment_mode", "")),
        "- Controller runtime: %s" % SERVICE_MODE_LABELS.get(farm_setup.get("controller_service_mode"), farm_setup.get("controller_service_mode", "")),
        "- Mode PIN: %s" % str(farm_setup.get("mode_switch_pin", "1234")),
        "- Sync tokens: always blank",
        "",
        "Included files",
        "- SETUP-SHEET.txt",
        "- office/install_commands.sh",
        "- office/office_config.json",
        "- one install_commands.sh per shed or water controller",
        "",
        "Copy the whole bundle to the target machine if you want to run the generated install scripts directly.",
        "Those scripts expect the repo to exist at ~/cherry-dene-dashboard.",
        "",
        "Bundle root",
        str(output_dir),
        "",
    ]
    return "\n".join(lines)


def build_shed_install_notes(form_data, farm_setup, bundle_dir):
    shed_no = str(form_data["sheds"][0]["shed_no"])
    shed = farm_setup["sheds"][shed_no]
    return "\n".join([
        "Cherry Dene Shed Controller Export",
        "",
        "Farm ID: %s" % farm_setup.get("farm_id", "--"),
        "Farm: %s" % farm_setup["farm_name"],
        "Office dashboard: %s" % farm_setup["office"]["dashboard_url"],
        "Shed: %s" % shed_no,
        "Deployment mode: %s" % DEPLOYMENT_MODE_LABELS.get(farm_setup.get("deployment_mode"), farm_setup.get("deployment_mode", "")),
        "Controller runtime: %s" % SERVICE_MODE_LABELS.get(farm_setup.get("controller_service_mode"), farm_setup.get("controller_service_mode", "")),
        "Mode PIN: %s" % str(farm_setup.get("mode_switch_pin", "1234")),
        "Equipment: %s" % ", ".join(format_equipment_list(shed)),
        "",
        "Files",
        "- shed/controller_config.json",
        "- shed/install_commands.sh",
        "- office/controllers.fragment.json",
        "",
        "Bundle root",
        str(bundle_dir),
        "",
    ])


def build_water_install_notes(form_data, farm_setup, bundle_dir):
    return "\n".join([
        "Cherry Dene Water Controller Export",
        "",
        "Farm ID: %s" % farm_setup.get("farm_id", "--"),
        "Farm: %s" % farm_setup["farm_name"],
        "Office dashboard: %s" % farm_setup["office"]["dashboard_url"],
        "Water controller IP: %s" % form_data["borehole_ip"],
        "Deployment mode: %s" % DEPLOYMENT_MODE_LABELS.get(farm_setup.get("deployment_mode"), farm_setup.get("deployment_mode", "")),
        "Controller runtime: %s" % SERVICE_MODE_LABELS.get(farm_setup.get("controller_service_mode"), farm_setup.get("controller_service_mode", "")),
        "Mode PIN: %s" % str(farm_setup.get("mode_switch_pin", "1234")),
        "",
        "Files",
        "- water/controller_config.json",
        "- water/install_commands.sh",
        "- office/controllers.fragment.json",
        "",
        "Bundle root",
        str(bundle_dir),
        "",
    ])


def build_office_install_script():
    return """#!/bin/bash
set -eu

APP_DIR="${1:-$HOME/cherry-dene-dashboard}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$APP_DIR" ]; then
  echo "Repo not found at $APP_DIR"
  echo "Clone cherry-dene-dashboard first, then rerun this script."
  exit 1
fi

mkdir -p "$APP_DIR/data"
cp "$SCRIPT_DIR/controllers.json" "$APP_DIR/data/controllers.json"
cp "$SCRIPT_DIR/office_config.json" "$APP_DIR/data/office_config.json"
sudo bash "$APP_DIR/pi_kiosk/install_office_service.sh" "$APP_DIR"
sudo systemctl restart office-dashboard.service

echo
echo "Office dashboard updated from bundle."
echo "Controllers file copied from: $SCRIPT_DIR/controllers.json"
echo "Office identity copied from: $SCRIPT_DIR/office_config.json"
"""


def build_shed_install_script(farm_setup, shed_no):
    shed_no = str(int(shed_no))
    cfg = farm_setup["sheds"][shed_no]
    return """#!/bin/bash
set -eu

APP_DIR="${1:-$HOME/cherry-dene-dashboard}"
USER_NAME="${2:-$(id -un)}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$APP_DIR" ]; then
  echo "Repo not found at $APP_DIR"
  echo "Clone cherry-dene-dashboard first, then rerun this script."
  exit 1
fi

bash "$APP_DIR/scripts/install_shed_controller_pi.sh" "$APP_DIR" "$USER_NAME" "%(shed_no)s" "%(dashboard_url)s" "" "%(service_mode)s" "%(deployment_mode)s" "%(mode_switch_pin)s"
mkdir -p "$APP_DIR/controller_data"
cp "$SCRIPT_DIR/controller_config.json" "$APP_DIR/controller_data/controller_config.json"
sudo systemctl restart shed-controller.service

echo
echo "Shed %(shed_no)s controller updated from bundle."
echo "Config copied from: $SCRIPT_DIR/controller_config.json"
    """ % {
        "shed_no": shed_no,
        "dashboard_url": farm_setup["office"]["dashboard_url"],
        "service_mode": cfg.get("service_mode", "kiosk"),
        "deployment_mode": cfg.get("deployment_mode", "commissioning"),
        "mode_switch_pin": str(cfg.get("mode_switch_pin", farm_setup.get("mode_switch_pin", "1234")) or "1234"),
    }


def build_water_install_script(farm_setup):
    return """#!/bin/bash
set -eu

APP_DIR="${1:-$HOME/cherry-dene-dashboard}"
USER_NAME="${2:-$(id -un)}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$APP_DIR" ]; then
  echo "Repo not found at $APP_DIR"
  echo "Clone cherry-dene-dashboard first, then rerun this script."
  exit 1
fi

bash "$APP_DIR/scripts/install_borehole_controller_pi.sh" "$APP_DIR" "$USER_NAME" "%(dashboard_url)s" "" "%(service_mode)s" "%(deployment_mode)s" "%(mode_switch_pin)s"
mkdir -p "$APP_DIR/borehole_controller_data"
cp "$SCRIPT_DIR/controller_config.json" "$APP_DIR/borehole_controller_data/controller_config.json"
sudo systemctl restart borehole-controller.service

echo
echo "Water controller updated from bundle."
echo "Config copied from: $SCRIPT_DIR/controller_config.json"
    """ % {
        "dashboard_url": farm_setup["office"]["dashboard_url"],
        "service_mode": farm_setup.get("borehole", {}).get("service_mode", farm_setup.get("controller_service_mode", "kiosk")),
        "deployment_mode": farm_setup.get("borehole", {}).get("deployment_mode", farm_setup.get("deployment_mode", "commissioning")),
        "mode_switch_pin": str(farm_setup.get("borehole", {}).get("mode_switch_pin", farm_setup.get("mode_switch_pin", "1234")) or "1234"),
    }


def build_bundle(form_data, output_root):
    system_type = form_data["system_type"]
    farm_setup = build_farm_setup_payload(form_data)
    office_controllers = build_office_controllers_payload(farm_setup)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_dir = Path(output_root) / ("%s_%s_%s" % (slugify(farm_setup["farm_name"]), system_type, timestamp))
    bundle_dir.mkdir(parents=True, exist_ok=True)

    write_json(bundle_dir / "farm_setup.json", farm_setup)
    write_text(bundle_dir / "SETUP-SHEET.txt", build_setup_sheet(farm_setup, system_type))

    if system_type in ["dashboard", "other"]:
        write_json(bundle_dir / "office" / "controllers.json", office_controllers)
        write_json(bundle_dir / "office" / "office_config.json", build_office_config_payload(farm_setup))
        write_shell_script(bundle_dir / "office" / "install_commands.sh", build_office_install_script())
        for shed_no in sorted(farm_setup["sheds"].keys(), key=lambda value: int(value)):
            cfg = build_controller_config_payload(farm_setup, shed_no)
            shed_dir = bundle_dir / "sheds" / ("shed_%s" % shed_no)
            write_json(shed_dir / "controller_config.json", cfg)
            write_shell_script(shed_dir / "install_commands.sh", build_shed_install_script(farm_setup, shed_no))
        if "borehole" in office_controllers:
            water_dir = bundle_dir / "water"
            write_json(water_dir / "controller_config.json", build_borehole_controller_config_payload(farm_setup))
            write_shell_script(water_dir / "install_commands.sh", build_water_install_script(farm_setup))
        notes = build_install_notes(farm_setup, bundle_dir)
    elif system_type == "shed":
        shed_no = form_data["sheds"][0]["shed_no"]
        cfg = build_controller_config_payload(farm_setup, shed_no)
        write_json(bundle_dir / "shed" / "controller_config.json", cfg)
        write_shell_script(bundle_dir / "shed" / "install_commands.sh", build_shed_install_script(farm_setup, shed_no))
        office_fragment = {shed_no: office_controllers[shed_no]}
        write_json(bundle_dir / "office" / "controllers.fragment.json", office_fragment)
        notes = build_shed_install_notes(form_data, farm_setup, bundle_dir)
    elif system_type == "water":
        write_json(bundle_dir / "water" / "controller_config.json", build_borehole_controller_config_payload(farm_setup))
        write_shell_script(bundle_dir / "water" / "install_commands.sh", build_water_install_script(farm_setup))
        office_fragment = {}
        if "borehole" in office_controllers:
            office_fragment["borehole"] = office_controllers["borehole"]
        write_json(bundle_dir / "office" / "controllers.fragment.json", office_fragment)
        notes = build_water_install_notes(form_data, farm_setup, bundle_dir)
    else:
        raise ValueError("Unknown system type: %s" % system_type)

    write_text(bundle_dir / "README.txt", notes)
    return bundle_dir


class ShedRow:
    def __init__(self, parent, shed_no, suggested_ip):
        self.frame = ttk.Frame(parent)
        self.shed_no = str(int(shed_no))
        ttk.Label(self.frame, text="Shed %s" % self.shed_no, width=10).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)

        self.ip_var = tk.StringVar(value=suggested_ip)
        self.temp_var = tk.BooleanVar(value=True)
        self.flow_var = tk.BooleanVar(value=True)
        self.feed_var = tk.BooleanVar(value=False)
        self.cross_var = tk.BooleanVar(value=False)
        self.left_var = tk.BooleanVar(value=True)
        self.right_var = tk.BooleanVar(value=False)

        ttk.Entry(self.frame, textvariable=self.ip_var, width=18).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Checkbutton(self.frame, text="Temp", variable=self.temp_var).grid(row=0, column=2, padx=6, pady=4)
        ttk.Checkbutton(self.frame, text="Flow", variable=self.flow_var).grid(row=0, column=3, padx=6, pady=4)
        ttk.Checkbutton(self.frame, text="Feed", variable=self.feed_var).grid(row=0, column=4, padx=6, pady=4)
        ttk.Checkbutton(self.frame, text="Cross", variable=self.cross_var).grid(row=0, column=5, padx=6, pady=4)
        ttk.Checkbutton(self.frame, text="Left", variable=self.left_var).grid(row=0, column=6, padx=6, pady=4)
        ttk.Checkbutton(self.frame, text="Right", variable=self.right_var).grid(row=0, column=7, padx=6, pady=4)
        self.frame.columnconfigure(1, weight=1)

    def to_payload(self):
        return {
            "shed_no": self.shed_no,
            "controller_ip": self.ip_var.get().strip(),
            "temp_sensor_enabled": bool(self.temp_var.get()),
            "water_meter_enabled": bool(self.flow_var.get()),
            "feed_bin_enabled": bool(self.feed_var.get()),
            "cross_auger_enabled": bool(self.cross_var.get()),
            "auger_left_enabled": bool(self.left_var.get()),
            "auger_right_enabled": bool(self.right_var.get()),
        }


class FarmSetupWizard:
    def __init__(self, root):
        self.root = root
        self.root.title("Cherry Dene Farm Setup Wizard")
        self.root.geometry("1200x820")
        self.root.minsize(1040, 760)

        default_ip = FARM_TEMPLATE["office"].get("dashboard_ip", "192.168.1.10")
        default_base = ".".join(default_ip.split(".")[:3]) if default_ip.count(".") == 3 else "192.168.1"

        self.system_type_var = tk.StringVar(value="dashboard")
        self.deployment_mode_var = tk.StringVar(value="commissioning")
        self.controller_service_mode_var = tk.StringVar(value="kiosk")
        self.mode_switch_pin_var = tk.StringVar(value="1234")
        self.farm_id_var = tk.StringVar(value=default_farm_id())
        self.farm_name_var = tk.StringVar(value=FARM_TEMPLATE.get("farm_name", ""))
        self.dashboard_ip_var = tk.StringVar(value=default_ip)
        self.dashboard_port_var = tk.StringVar(value=str(FARM_TEMPLATE["office"].get("dashboard_port", 8090)))
        self.controller_ip_base_var = tk.StringVar(value=default_base)
        self.controller_ip_start_var = tk.StringVar(value="101")
        self.shed_numbers_var = tk.StringVar(value="1,2,3")
        self.output_root_var = tk.StringVar(value=str(DEFAULT_OUTPUT_ROOT))
        self.borehole_enabled_var = tk.BooleanVar(value=bool(FARM_TEMPLATE.get("borehole", {}).get("enabled", True)))
        self.borehole_ip_var = tk.StringVar(value=FARM_TEMPLATE.get("borehole", {}).get("controller_ip", "192.168.1.120"))
        self.shed_rows = []

        self._build_ui()
        self.rebuild_shed_rows()
        self.apply_system_type()

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        self.header_label = ttk.Label(
            outer,
            text="Build a ready-to-copy deployment bundle for a new farm.",
            font=("Helvetica", 15, "bold"),
        )
        self.header_label.pack(anchor="w", pady=(0, 12))

        top = ttk.LabelFrame(outer, text="Farm Details", padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="System Type").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.system_type_combo = ttk.Combobox(
            top,
            state="readonly",
            textvariable=self.system_type_var,
            values=["dashboard", "shed", "water", "other"],
            width=16,
        )
        self.system_type_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        self.system_type_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_system_type())

        ttk.Label(top, text="Mode").grid(row=0, column=2, sticky="w", padx=6, pady=6)
        self.deployment_mode_combo = ttk.Combobox(
            top,
            state="readonly",
            textvariable=self.deployment_mode_var,
            values=["commissioning", "live"],
            width=16,
        )
        self.deployment_mode_combo.grid(row=0, column=3, sticky="ew", padx=6, pady=6)

        ttk.Label(top, text="Controller Runtime").grid(row=0, column=4, sticky="w", padx=6, pady=6)
        self.controller_service_mode_combo = ttk.Combobox(
            top,
            state="readonly",
            textvariable=self.controller_service_mode_var,
            values=["kiosk", "service_only"],
            width=18,
        )
        self.controller_service_mode_combo.grid(row=0, column=5, sticky="ew", padx=6, pady=6)

        ttk.Label(top, text="Farm Name").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.farm_name_var, width=36).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        ttk.Label(top, text="Farm ID").grid(row=1, column=2, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.farm_id_var, width=18).grid(row=1, column=3, sticky="ew", padx=6, pady=6)
        ttk.Label(top, text="Dashboard IP").grid(row=1, column=4, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.dashboard_ip_var, width=18).grid(row=1, column=5, sticky="ew", padx=6, pady=6)

        ttk.Label(top, text="Dashboard Port").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.dashboard_port_var, width=8).grid(row=2, column=1, sticky="ew", padx=6, pady=6)
        ttk.Label(top, text="Controller IP Base").grid(row=2, column=2, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.controller_ip_base_var, width=18).grid(row=2, column=3, sticky="ew", padx=6, pady=6)
        ttk.Label(top, text="Start Host").grid(row=2, column=4, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.controller_ip_start_var, width=8).grid(row=2, column=5, sticky="ew", padx=6, pady=6)

        ttk.Label(top, text="Mode PIN").grid(row=3, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.mode_switch_pin_var, width=12).grid(row=3, column=1, sticky="ew", padx=6, pady=6)
        self.shed_numbers_label = ttk.Label(top, text="Shed Numbers")
        self.shed_numbers_label.grid(row=3, column=2, sticky="w", padx=6, pady=6)
        self.shed_numbers_entry = ttk.Entry(top, textvariable=self.shed_numbers_var, width=18)
        self.shed_numbers_entry.grid(row=3, column=3, sticky="ew", padx=6, pady=6)

        self.build_rows_button = ttk.Button(top, text="Build Shed Rows", command=self.rebuild_shed_rows)
        self.build_rows_button.grid(row=3, column=4, columnspan=2, sticky="ew", padx=6, pady=6)

        self.borehole_check = ttk.Checkbutton(top, text="Include Bore Hole", variable=self.borehole_enabled_var)
        self.borehole_check.grid(row=4, column=0, sticky="w", padx=6, pady=6)
        self.borehole_ip_label = ttk.Label(top, text="Bore Hole IP")
        self.borehole_ip_label.grid(row=4, column=2, sticky="w", padx=6, pady=6)
        self.borehole_ip_entry = ttk.Entry(top, textvariable=self.borehole_ip_var, width=18)
        self.borehole_ip_entry.grid(row=4, column=3, sticky="ew", padx=6, pady=6)

        ttk.Label(top, text="Output Folder").grid(row=5, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.output_root_var).grid(row=5, column=1, columnspan=4, sticky="ew", padx=6, pady=6)
        ttk.Button(top, text="Choose...", command=self.choose_output_root).grid(row=5, column=5, sticky="ew", padx=6, pady=6)

        for column in range(6):
            top.columnconfigure(column, weight=1 if column in [1, 3, 5] else 0)

        self.shed_box = ttk.LabelFrame(outer, text="Shed Controllers", padding=12)
        self.shed_box.pack(fill="both", expand=True, pady=(14, 0))

        headings = ttk.Frame(self.shed_box)
        headings.pack(fill="x")
        columns = [
            ("Shed", 10),
            ("Controller IP", 18),
            ("Temp", 8),
            ("Flow", 8),
            ("Feed", 8),
            ("Cross", 8),
            ("Left", 8),
            ("Right", 8),
        ]
        for index, (label, width) in enumerate(columns):
            ttk.Label(headings, text=label, width=width).grid(row=0, column=index, sticky="w", padx=6 if index else (0, 6))

        self.shed_rows_frame = ttk.Frame(self.shed_box)
        self.shed_rows_frame.pack(fill="both", expand=True, pady=(8, 0))

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(14, 0))
        ttk.Button(footer, text="Generate Setup Bundle", command=self.generate).pack(side="right")

    def choose_output_root(self):
        selected = filedialog.askdirectory(initialdir=self.output_root_var.get() or str(BASE_DIR))
        if selected:
            self.output_root_var.set(selected)

    def rebuild_shed_rows(self):
        for child in self.shed_rows_frame.winfo_children():
            child.destroy()
        self.shed_rows = []

        try:
            shed_numbers = parse_shed_numbers(self.shed_numbers_var.get())
            base_ip = normalise_ip_base(self.controller_ip_base_var.get(), self.dashboard_ip_var.get())
            start_host = parse_host_number(self.controller_ip_start_var.get())
        except Exception as exc:
            messagebox.showerror("Invalid shed settings", str(exc))
            return

        self.controller_ip_base_var.set(base_ip)
        for row_index, shed_no in enumerate(shed_numbers):
            row = ShedRow(
                self.shed_rows_frame,
                shed_no,
                suggest_controller_ip(base_ip, start_host, shed_no),
            )
            row.frame.grid(row=row_index, column=0, sticky="ew")
            self.shed_rows.append(row)
        self.shed_rows_frame.columnconfigure(0, weight=1)

    def apply_system_type(self):
        system_type = self.system_type_var.get().strip() or "dashboard"
        self.header_label.config(
            text="Build a ready-to-copy %s setup bundle." % SYSTEM_TYPE_LABELS.get(system_type, "setup")
        )

        show_sheds = system_type in ["dashboard", "shed", "other"]
        show_borehole = system_type in ["dashboard", "water", "other"]

        if system_type == "shed":
            self.shed_numbers_label.config(text="Shed Number")
            if "," in self.shed_numbers_var.get():
                self.shed_numbers_var.set(self.shed_numbers_var.get().split(",")[0].strip())
        else:
            self.shed_numbers_label.config(text="Shed Numbers")

        if show_sheds:
            if not self.shed_box.winfo_manager():
                self.shed_box.pack(fill="both", expand=True, pady=(14, 0))
            self.rebuild_shed_rows()
        elif self.shed_box.winfo_manager():
            self.shed_box.pack_forget()

        if system_type == "water":
            self.borehole_enabled_var.set(True)
        elif system_type == "shed":
            self.borehole_enabled_var.set(False)

        for widget in [self.borehole_check, self.borehole_ip_label, self.borehole_ip_entry]:
            if show_borehole:
                widget.grid()
            else:
                widget.grid_remove()

        self.borehole_check.configure(state="normal" if system_type in ["dashboard", "other"] else "disabled")

    def validate(self):
        farm_id = slugify(self.farm_id_var.get().strip())
        if not self.farm_name_var.get().strip():
            raise ValueError("Farm name is required.")
        if not farm_id:
            raise ValueError("Farm ID is required.")
        if not self.dashboard_ip_var.get().strip():
            raise ValueError("Dashboard IP is required.")

        system_type = self.system_type_var.get().strip() or "dashboard"
        deployment_mode = self.deployment_mode_var.get().strip() or "commissioning"
        controller_service_mode = self.controller_service_mode_var.get().strip() or "kiosk"
        if deployment_mode not in DEPLOYMENT_MODE_LABELS:
            raise ValueError("Pick commissioning or live mode.")
        if controller_service_mode not in SERVICE_MODE_LABELS:
            raise ValueError("Pick kiosk or service_only runtime.")
        mode_switch_pin = str(self.mode_switch_pin_var.get()).strip()
        if not mode_switch_pin or not mode_switch_pin.isdigit() or len(mode_switch_pin) < 4:
            raise ValueError("Mode PIN must be at least 4 digits.")

        dashboard_port = int(self.dashboard_port_var.get().strip())
        controller_ip_base = normalise_ip_base(self.controller_ip_base_var.get(), self.dashboard_ip_var.get())
        controller_ip_start = parse_host_number(self.controller_ip_start_var.get())

        sheds = []
        if system_type in ["dashboard", "shed", "other"]:
            if not self.shed_rows:
                raise ValueError("Add at least one shed.")
            for row in self.shed_rows:
                payload = row.to_payload()
                if not payload["controller_ip"]:
                    raise ValueError("Shed %s needs a controller IP." % payload["shed_no"])
                sheds.append(payload)
            if system_type == "shed" and len(sheds) != 1:
                raise ValueError("Shed controller mode expects exactly one shed.")

        if system_type == "water" and not self.borehole_ip_var.get().strip():
            raise ValueError("Water controller mode needs a bore hole IP.")

        return {
            "system_type": system_type,
            "deployment_mode": deployment_mode,
            "controller_service_mode": controller_service_mode,
            "mode_switch_pin": mode_switch_pin,
            "farm_id": farm_id,
            "farm_name": self.farm_name_var.get().strip(),
            "dashboard_ip": self.dashboard_ip_var.get().strip(),
            "dashboard_port": dashboard_port,
            "controller_ip_base": controller_ip_base,
            "controller_ip_start": controller_ip_start,
            "borehole_enabled": bool(self.borehole_enabled_var.get()) if system_type in ["dashboard", "other"] else bool(system_type == "water"),
            "borehole_ip": self.borehole_ip_var.get().strip(),
            "sheds": sheds,
        }

    def generate(self):
        try:
            form_data = self.validate()
            bundle_dir = build_bundle(form_data, self.output_root_var.get().strip() or str(DEFAULT_OUTPUT_ROOT))
        except Exception as exc:
            messagebox.showerror("Could not build setup bundle", str(exc))
            return

        messagebox.showinfo(
            "Setup bundle created",
            "Created:\n%s\n\nThis bundle includes setup sheets, config files, and install command files for the selected %s."
            % (bundle_dir, SYSTEM_TYPE_LABELS.get(form_data["system_type"], "setup")),
        )


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    FarmSetupWizard(root)
    root.mainloop()


if __name__ == "__main__":
    raise SystemExit(main())
