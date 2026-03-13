#!/usr/bin/env python3
import json
import os
import sys


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def main():
    if len(sys.argv) < 4:
        print("Usage: install_shed_from_farm_setup.py <farm_setup.json> <shed_no> <output_config.json>")
        return 1

    farm_setup_path = sys.argv[1]
    shed_no = str(int(sys.argv[2]))
    output_path = sys.argv[3]

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_path = os.path.join(base_dir, "pi_templates", "controller_config.template.json")

    farm = load_json(farm_setup_path)
    template = load_json(template_path)

    sheds = farm.get("sheds", {})
    if shed_no not in sheds:
        print("Shed %s not found in %s" % (shed_no, farm_setup_path))
        return 2

    office = farm.get("office", {})
    shed = sheds[shed_no]

    cfg = dict(template)
    cfg["shed_no"] = int(shed_no)
    cfg["dashboard_url"] = office.get("dashboard_url", cfg.get("dashboard_url"))
    cfg["listen_port"] = int(shed.get("controller_port", cfg.get("listen_port", 8091)))
    cfg["serial_port"] = shed.get("serial_port", cfg.get("serial_port"))
    cfg["touch_refresh_seconds"] = int(shed.get("touch_refresh_seconds", cfg.get("touch_refresh_seconds", 1)))
    cfg["temp_low_c"] = float(shed.get("temp_low_c", cfg.get("temp_low_c", 18.0)))
    cfg["temp_high_c"] = float(shed.get("temp_high_c", cfg.get("temp_high_c", 24.0)))
    cfg["water_low_lpm"] = float(shed.get("water_low_lpm", cfg.get("water_low_lpm", 0.1)))
    cfg["feed_low_kg"] = float(shed.get("feed_low_kg", cfg.get("feed_low_kg", 2000.0)))
    cfg["cross_auger_enabled"] = bool(shed.get("cross_auger_enabled", cfg.get("cross_auger_enabled", True)))
    cfg["auger_left_enabled"] = bool(shed.get("auger_left_enabled", cfg.get("auger_left_enabled", True)))
    cfg["auger_right_enabled"] = bool(shed.get("auger_right_enabled", cfg.get("auger_right_enabled", True)))
    cfg["cross_auger_label"] = str(shed.get("cross_auger_label", cfg.get("cross_auger_label", "Cross Auger")))
    cfg["auger_left_label"] = str(shed.get("auger_left_label", cfg.get("auger_left_label", "Auger Left")))
    cfg["auger_right_label"] = str(shed.get("auger_right_label", cfg.get("auger_right_label", "Auger Right")))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")

    print("Wrote shed %s config to %s" % (shed_no, output_path))
    print("Controller URL: http://%s:%s" % (shed.get("controller_ip", "0.0.0.0"), cfg["listen_port"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
