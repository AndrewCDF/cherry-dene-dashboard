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
CONTROLLERS_TEMPLATE = load_json(TEMPLATE_DIR / "controllers.template.json")


def slugify(text):
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    return cleaned or "farm"


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


def build_farm_setup_payload(form_data):
    farm = deepcopy(FARM_TEMPLATE)
    farm["farm_name"] = form_data["farm_name"]
    farm["office"]["dashboard_ip"] = form_data["dashboard_ip"]
    farm["office"]["dashboard_port"] = int(form_data["dashboard_port"])
    farm["office"]["dashboard_url"] = "http://%s:%s" % (
        form_data["dashboard_ip"],
        int(form_data["dashboard_port"]),
    )

    farm["sheds"] = {}
    for shed in form_data["sheds"]:
        shed_no = str(int(shed["shed_no"]))
        farm["sheds"][shed_no] = {
            "controller_ip": shed["controller_ip"],
            "controller_port": 8091,
            "serial_port": "/dev/ttyACM0",
            "touch_refresh_seconds": 1,
            "temp_low_c": 18.0,
            "temp_high_c": 24.0,
            "water_low_lpm": 0.1,
            "feed_low_kg": 2000.0,
            "cross_auger_enabled": bool(shed["cross_auger_enabled"]),
            "auger_left_enabled": bool(shed["auger_left_enabled"]),
            "auger_right_enabled": bool(shed["auger_right_enabled"]),
            "cross_auger_label": "Cross Auger",
            "auger_left_label": "Auger Left",
            "auger_right_label": "Auger Right",
        }

    farm["borehole"]["enabled"] = bool(form_data["borehole_enabled"])
    farm["borehole"]["controller_ip"] = form_data["borehole_ip"]
    return farm


def build_office_controllers_payload(farm_setup, sync_token):
    controllers = {}
    for shed_no, shed in sorted(farm_setup["sheds"].items(), key=lambda item: int(item[0])):
        controllers[shed_no] = {
            "sync_url": "http://%s:%s" % (shed["controller_ip"], int(shed.get("controller_port", 8091))),
            "sync_token": sync_token,
        }
    borehole = farm_setup.get("borehole", {})
    if borehole.get("enabled") and str(borehole.get("controller_ip", "")).strip():
        controllers["borehole"] = {
            "sync_url": "http://%s:%s" % (borehole["controller_ip"], int(borehole.get("controller_port", 8092))),
            "sync_token": sync_token,
            "label": "Bore Hole",
        }
    return controllers


def build_controller_config_payload(farm_setup, shed_no, sync_token):
    shed = farm_setup["sheds"][str(int(shed_no))]
    cfg = deepcopy(CONTROLLER_TEMPLATE)
    cfg["shed_no"] = int(shed_no)
    cfg["dashboard_url"] = farm_setup["office"]["dashboard_url"]
    cfg["sync_token"] = sync_token
    cfg["listen_port"] = int(shed.get("controller_port", 8091))
    cfg["serial_port"] = shed.get("serial_port", "/dev/ttyACM0")
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


def build_install_notes(farm_setup, sync_token, output_dir):
    office_path = output_dir / "office" / "controllers.json"
    lines = [
        "Cherry Dene Farm Setup Export",
        "",
        "Farm: %s" % farm_setup["farm_name"],
        "Office dashboard: %s" % farm_setup["office"]["dashboard_url"],
        "Sync token: %s" % (sync_token or "(blank)"),
        "",
        "Office Pi",
        "1. Copy office/controllers.json into ~/cherry-dene-dashboard/data/controllers.json",
        "2. Restart office-dashboard.service",
        "",
        "Office file:",
        str(office_path),
        "",
        "Shed controllers",
    ]

    for shed_no, shed in sorted(farm_setup["sheds"].items(), key=lambda item: int(item[0])):
        cfg_path = output_dir / "sheds" / ("shed_%s" % shed_no) / "controller_config.json"
        lines.extend([
            "",
            "Shed %s" % shed_no,
            "- Controller IP: %s" % shed["controller_ip"],
            "- Copy file to: ~/cherry-dene-dashboard/controller_data/controller_config.json",
            "- Config file: %s" % cfg_path,
            "- Restart: sudo systemctl restart shed-controller.service",
        ])

    borehole = farm_setup.get("borehole", {})
    if borehole.get("enabled") and str(borehole.get("controller_ip", "")).strip():
        lines.extend([
            "",
            "Bore hole",
            "- Controller IP: %s" % borehole["controller_ip"],
            "- Put the borehole entry from office/controllers.json onto the office Pi as well.",
        ])

    lines.extend([
        "",
        "Generated at: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
    ])
    return "\n".join(lines)


def build_bundle(form_data, output_root):
    farm_setup = build_farm_setup_payload(form_data)
    sync_token = str(form_data["sync_token"]).strip()
    office_controllers = build_office_controllers_payload(farm_setup, sync_token)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_dir = Path(output_root) / ("%s_%s" % (slugify(farm_setup["farm_name"]), timestamp))
    bundle_dir.mkdir(parents=True, exist_ok=True)

    write_json(bundle_dir / "farm_setup.json", farm_setup)
    write_json(bundle_dir / "office" / "controllers.json", office_controllers)

    for shed_no in sorted(farm_setup["sheds"].keys(), key=lambda value: int(value)):
        cfg = build_controller_config_payload(farm_setup, shed_no, sync_token)
        write_json(bundle_dir / "sheds" / ("shed_%s" % shed_no) / "controller_config.json", cfg)

    notes = build_install_notes(farm_setup, sync_token, bundle_dir)
    write_text(bundle_dir / "README.txt", notes)
    return bundle_dir


class ShedRow:
    def __init__(self, parent, shed_no, office_ip):
        self.frame = ttk.Frame(parent)
        self.shed_no = str(int(shed_no))
        ttk.Label(self.frame, text="Shed %s" % self.shed_no, width=10).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)

        suggested_ip = ""
        try:
            office_parts = office_ip.split(".")
            if len(office_parts) == 4:
                suggested_ip = ".".join(office_parts[:3] + [str(100 + int(self.shed_no))])
        except Exception:
            suggested_ip = ""

        self.ip_var = tk.StringVar(value=suggested_ip)
        self.cross_var = tk.BooleanVar(value=False)
        self.left_var = tk.BooleanVar(value=True)
        self.right_var = tk.BooleanVar(value=False)

        ttk.Entry(self.frame, textvariable=self.ip_var, width=18).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Checkbutton(self.frame, text="Cross", variable=self.cross_var).grid(row=0, column=2, padx=6, pady=4)
        ttk.Checkbutton(self.frame, text="Left", variable=self.left_var).grid(row=0, column=3, padx=6, pady=4)
        ttk.Checkbutton(self.frame, text="Right", variable=self.right_var).grid(row=0, column=4, padx=6, pady=4)
        self.frame.columnconfigure(1, weight=1)

    def to_payload(self):
        return {
            "shed_no": self.shed_no,
            "controller_ip": self.ip_var.get().strip(),
            "cross_auger_enabled": bool(self.cross_var.get()),
            "auger_left_enabled": bool(self.left_var.get()),
            "auger_right_enabled": bool(self.right_var.get()),
        }


class FarmSetupWizard:
    def __init__(self, root):
        self.root = root
        self.root.title("Cherry Dene Farm Setup Wizard")
        self.root.geometry("980x760")
        self.root.minsize(900, 700)

        self.farm_name_var = tk.StringVar(value=FARM_TEMPLATE.get("farm_name", ""))
        self.dashboard_ip_var = tk.StringVar(value=FARM_TEMPLATE["office"].get("dashboard_ip", "192.168.1.10"))
        self.dashboard_port_var = tk.StringVar(value=str(FARM_TEMPLATE["office"].get("dashboard_port", 8090)))
        self.sync_token_var = tk.StringVar(value="")
        self.shed_numbers_var = tk.StringVar(value="1,2,3")
        self.output_root_var = tk.StringVar(value=str(DEFAULT_OUTPUT_ROOT))
        self.borehole_enabled_var = tk.BooleanVar(value=bool(FARM_TEMPLATE.get("borehole", {}).get("enabled", True)))
        self.borehole_ip_var = tk.StringVar(value=FARM_TEMPLATE.get("borehole", {}).get("controller_ip", "192.168.1.120"))
        self.shed_rows = []

        self._build_ui()
        self.rebuild_shed_rows()

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Label(
            outer,
            text="Build a ready-to-copy office and shed config bundle for a new farm.",
            font=("Helvetica", 15, "bold"),
        )
        header.pack(anchor="w", pady=(0, 12))

        top = ttk.LabelFrame(outer, text="Farm Details", padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="Farm Name").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.farm_name_var, width=36).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Label(top, text="Dashboard IP").grid(row=0, column=2, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.dashboard_ip_var, width=18).grid(row=0, column=3, sticky="ew", padx=6, pady=6)
        ttk.Label(top, text="Dashboard Port").grid(row=0, column=4, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.dashboard_port_var, width=8).grid(row=0, column=5, sticky="ew", padx=6, pady=6)

        ttk.Label(top, text="Sync Token").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.sync_token_var, width=36).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        ttk.Label(top, text="Shed Numbers").grid(row=1, column=2, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.shed_numbers_var, width=18).grid(row=1, column=3, sticky="ew", padx=6, pady=6)
        ttk.Button(top, text="Build Shed Rows", command=self.rebuild_shed_rows).grid(row=1, column=4, columnspan=2, sticky="ew", padx=6, pady=6)

        ttk.Checkbutton(top, text="Include Bore Hole", variable=self.borehole_enabled_var).grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(top, text="Bore Hole IP").grid(row=2, column=2, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.borehole_ip_var, width=18).grid(row=2, column=3, sticky="ew", padx=6, pady=6)

        ttk.Label(top, text="Output Folder").grid(row=3, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.output_root_var).grid(row=3, column=1, columnspan=4, sticky="ew", padx=6, pady=6)
        ttk.Button(top, text="Choose…", command=self.choose_output_root).grid(row=3, column=5, sticky="ew", padx=6, pady=6)

        for column in range(6):
            top.columnconfigure(column, weight=1 if column in [1, 3, 4] else 0)

        shed_box = ttk.LabelFrame(outer, text="Shed Controllers", padding=12)
        shed_box.pack(fill="both", expand=True, pady=(14, 0))

        headings = ttk.Frame(shed_box)
        headings.pack(fill="x")
        ttk.Label(headings, text="Shed", width=10).grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(headings, text="Controller IP", width=18).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(headings, text="Cross", width=8).grid(row=0, column=2, sticky="w", padx=6)
        ttk.Label(headings, text="Left", width=8).grid(row=0, column=3, sticky="w", padx=6)
        ttk.Label(headings, text="Right", width=8).grid(row=0, column=4, sticky="w", padx=6)

        self.shed_rows_frame = ttk.Frame(shed_box)
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
        except Exception:
            messagebox.showerror("Invalid shed list", "Use a comma-separated list like 1,2,3,4.")
            return

        office_ip = self.dashboard_ip_var.get().strip()
        for row_index, shed_no in enumerate(shed_numbers):
            row = ShedRow(self.shed_rows_frame, shed_no, office_ip)
            row.frame.grid(row=row_index, column=0, sticky="ew")
            self.shed_rows.append(row)
        self.shed_rows_frame.columnconfigure(0, weight=1)

    def validate(self):
        if not self.farm_name_var.get().strip():
            raise ValueError("Farm name is required.")
        if not self.dashboard_ip_var.get().strip():
            raise ValueError("Dashboard IP is required.")
        int(self.dashboard_port_var.get().strip())
        if not self.shed_rows:
            raise ValueError("Add at least one shed.")
        sheds = []
        for row in self.shed_rows:
            payload = row.to_payload()
            if not payload["controller_ip"]:
                raise ValueError("Shed %s needs a controller IP." % payload["shed_no"])
            sheds.append(payload)
        return {
            "farm_name": self.farm_name_var.get().strip(),
            "dashboard_ip": self.dashboard_ip_var.get().strip(),
            "dashboard_port": int(self.dashboard_port_var.get().strip()),
            "sync_token": self.sync_token_var.get().strip(),
            "borehole_enabled": bool(self.borehole_enabled_var.get()),
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
            "Created:\n%s\n\nThis folder now contains the office controllers.json, per-shed controller_config.json files, and a README."
            % bundle_dir,
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
