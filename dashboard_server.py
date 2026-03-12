from flask import Flask, render_template_string, abort, url_for, request, redirect, jsonify, Response, send_file
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta

app = Flask(__name__)

DATA_DIR = "data"
SHED_NUMBERS = [1, 2, 3, 4, 6, 7, 8, 9, 10]
OFFICE_BACKUP_KEEP_COUNT = 48


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "backups"), exist_ok=True)


def read_json_file(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def write_json_file_atomic(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def append_json_line(path, payload):
    with open(path, "a") as f:
        f.write(json.dumps(payload))
        f.write("\n")


def read_all_json_lines(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return []

    out = []
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        return []
    return out


def append_named_json_line(filename, payload):
    append_json_line(os.path.join(DATA_DIR, filename), payload)


def backups_dir():
    ensure_data_dir()
    return os.path.join(DATA_DIR, "backups")


def list_office_backup_files():
    base = backups_dir()
    out = []
    try:
        names = sorted(os.listdir(base), reverse=True)
    except Exception:
        return out
    i = 0
    while i < len(names):
        path = os.path.join(base, names[i])
        if os.path.isfile(path) and names[i].endswith(".zip"):
            out.append(path)
        i += 1
    return out


def create_office_backup_zip(label="manual"):
    ensure_data_dir()
    stamp = datetime.fromtimestamp(int(time.time())).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(backups_dir(), "office_%s_%s.zip" % (label, stamp))
    names = sorted(os.listdir(DATA_DIR))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        i = 0
        while i < len(names):
            name = names[i]
            src = os.path.join(DATA_DIR, name)
            if os.path.isfile(src) and name != os.path.basename(path):
                zf.write(src, arcname=name)
            i += 1
    backups = list_office_backup_files()
    i = OFFICE_BACKUP_KEEP_COUNT
    while i < len(backups):
        try:
            os.remove(backups[i])
        except Exception:
            pass
        i += 1
    return path


def latest_live_by_shed():
    data = read_json_file(os.path.join(DATA_DIR, "live_latest.json"), {})
    return data if isinstance(data, dict) else {}


def latest_borehole_live():
    data = read_json_file(os.path.join(DATA_DIR, "borehole_live_latest.json"), {})
    return data if isinstance(data, dict) else {}


def load_farm_crop():
    data = read_json_file(os.path.join(DATA_DIR, "farm_crop.json"), {})
    return data if isinstance(data, dict) else {}


def load_controller_config():
    data = read_json_file(os.path.join(DATA_DIR, "controllers.json"), {})
    return data if isinstance(data, dict) else {}


def load_controller_meta():
    data = read_json_file(os.path.join(DATA_DIR, "controller_meta.json"), {})
    return data if isinstance(data, dict) else {}


def save_farm_crop(data):
    path = os.path.join(DATA_DIR, "farm_crop.json")
    write_json_file_atomic(path, data)


def save_controller_meta(data):
    path = os.path.join(DATA_DIR, "controller_meta.json")
    write_json_file_atomic(path, data)


def log_event(source, event_type, message, shed_no=None, detail=None):
    payload = {
        "ts": int(time.time()),
        "source": str(source or "").strip() or "system",
        "event_type": str(event_type or "").strip() or "event",
        "message": str(message or "").strip(),
        "detail": str(detail or "").strip(),
    }
    if shed_no in SHED_NUMBERS:
        payload["shed_no"] = int(shed_no)
        payload["shed"] = shed_name_from_number(int(shed_no))
    append_named_json_line("events.ndjson", payload)


def get_recent_events(limit=200):
    rows = read_all_json_lines("events.ndjson")
    rows.sort(key=lambda r: int(r.get("ts", 0)), reverse=True)
    if limit is not None:
        rows = rows[:limit]
    i = 0
    while i < len(rows):
        try:
            rows[i]["ts_label"] = datetime.fromtimestamp(int(rows[i].get("ts"))).strftime("%d %b %Y %H:%M:%S")
        except Exception:
            rows[i]["ts_label"] = "--"
        i += 1
    return rows


def clean_controller_meta(meta):
    if not isinstance(meta, dict):
        meta = {}

    out = {
        "temp_c": meta.get("temp_c"),
        "rh_pct": meta.get("rh_pct"),
        "water_lpm": meta.get("water_lpm"),
        "feed_kg": meta.get("feed_kg"),
        "last_sensor_ts": meta.get("last_sensor_ts"),
        "device_status": meta.get("device_status"),
        "pico_connected": bool(meta.get("pico_connected", False)),
        "received_ts": int(time.time()),
        "controller_sync_version": meta.get("controller_sync_version"),
        "controller_state_updated_ts": meta.get("controller_state_updated_ts"),
        "last_seen_office_sync_version": meta.get("last_seen_office_sync_version"),
        "controller_alarms": [],
        "augers": {},
    }

    controller_alarms = meta.get("controller_alarms", [])
    if isinstance(controller_alarms, list):
        i = 0
        while i < len(controller_alarms):
            item = controller_alarms[i]
            if isinstance(item, dict):
                message = str(item.get("message", "")).strip()
                alarm_key = str(item.get("alarm_key", "")).strip()
                if message:
                    out["controller_alarms"].append({
                        "alarm_key": alarm_key or "controller_alarm",
                        "message": message,
                    })
            elif item not in [None, ""]:
                out["controller_alarms"].append({
                    "alarm_key": "controller_alarm",
                    "message": str(item),
                })
            i += 1

    augers = meta.get("augers", {})
    if isinstance(augers, dict):
        for key in ["cross_auger", "auger_left", "auger_right"]:
            rec = augers.get(key, {})
            if not isinstance(rec, dict):
                continue
            out["augers"][key] = {
                "label": str(rec.get("label", key.replace("_", " ").title())),
                "on": bool(rec.get("on", False)),
                "started_ts": rec.get("started_ts"),
                "overrun": bool(rec.get("overrun", False)),
            }

    return out


def save_controller_meta_for_shed(shed_no, meta):
    all_meta = load_controller_meta()
    all_meta[str(int(shed_no))] = clean_controller_meta(meta)
    save_controller_meta(all_meta)


def controller_alarms_for_shed(controller_meta_map, shed_no):
    meta = controller_meta_map.get(str(int(shed_no)), {})
    alarms = meta.get("controller_alarms", []) if isinstance(meta, dict) else []
    return alarms if isinstance(alarms, list) else []


def effective_live_for_shed(live_map, controller_meta_map, shed_no):
    shed_name = shed_name_from_number(shed_no)
    live = dict(live_map.get(shed_name, {}))
    meta = controller_meta_map.get(str(int(shed_no)), {})
    if not isinstance(meta, dict):
        return live

    merged = dict(live)
    for key in ["temp_c", "rh_pct", "water_lpm", "feed_kg"]:
        if meta.get(key) is not None:
            merged[key] = meta.get(key)

    if meta.get("last_sensor_ts") is not None:
        merged["ts"] = meta.get("last_sensor_ts")

    return merged


def active_crop_record_for_shed(shed_name):
    state = load_shed_entries_state()
    entries = ensure_shed_entry_bucket(state, shed_name)

    best = None
    for key in entries:
        rec = entries.get(key, {})
        try:
            bird_count = int(rec.get("bird_count", 0) or 0)
        except Exception:
            bird_count = 0

        try:
            crop_active = 1 if int(rec.get("crop_active", 0) or 0) == 1 else 0
        except Exception:
            crop_active = 0

        try:
            crop_id = int(rec.get("crop_id"))
        except Exception:
            crop_id = None

        if bird_count <= 0 or crop_active != 1 or crop_id is None:
            continue

        placement_epoch = rec.get("placement_epoch")
        rank = crop_id
        if best is None or rank > best["rank"]:
            best = {
                "rank": rank,
                "crop_id": crop_id,
                "placement_epoch": placement_epoch,
                "crop_active": crop_active,
            }

    if best is None:
        return {}

    return {
        "crop_id": best["crop_id"],
        "placement_epoch": best["placement_epoch"],
        "crop_active": best["crop_active"],
    }


def current_active_crop_id_from_state(state):
    highest = None

    for shed_name in state:
        entries = ensure_shed_entry_bucket(state, shed_name)
        for key in entries:
            rec = entries.get(key, {})
            try:
                bird_count = int(rec.get("bird_count", 0) or 0)
            except Exception:
                bird_count = 0

            try:
                crop_active = 1 if int(rec.get("crop_active", 0) or 0) == 1 else 0
            except Exception:
                crop_active = 0

            try:
                crop_id = int(rec.get("crop_id"))
            except Exception:
                crop_id = None

            if bird_count <= 0 or crop_active != 1 or crop_id is None:
                continue

            if highest is None or crop_id > highest:
                highest = crop_id

    return highest


def allocate_next_crop_id(state):
    ensure_data_dir()
    farm_crop = load_farm_crop()

    try:
        last_crop_id = int(farm_crop.get("last_crop_id"))
    except Exception:
        last_crop_id = 0

    active_crop_id = current_active_crop_id_from_state(state)
    if active_crop_id is not None and active_crop_id > last_crop_id:
        last_crop_id = active_crop_id

    next_crop_id = last_crop_id + 1
    farm_crop["last_crop_id"] = next_crop_id
    farm_crop["current_crop_id"] = next_crop_id
    save_farm_crop(farm_crop)
    return next_crop_id


def crop_id_for_new_start(state):
    ensure_data_dir()
    farm_crop = load_farm_crop()

    try:
        current_crop_id = int(farm_crop.get("current_crop_id"))
    except Exception:
        current_crop_id = None

    if current_crop_id is not None and current_crop_id > 0:
        return current_crop_id

    active_crop_id = current_active_crop_id_from_state(state)
    if active_crop_id is not None and active_crop_id > 0:
        farm_crop["current_crop_id"] = active_crop_id
        try:
            last_crop_id = int(farm_crop.get("last_crop_id"))
        except Exception:
            last_crop_id = 0
        if active_crop_id > last_crop_id:
            farm_crop["last_crop_id"] = active_crop_id
        save_farm_crop(farm_crop)
        return active_crop_id

    return allocate_next_crop_id(state)


def refresh_farm_crop_current_id(state):
    ensure_data_dir()
    farm_crop = load_farm_crop()
    current_crop_id = current_active_crop_id_from_state(state)

    if current_crop_id is None:
        farm_crop["current_crop_id"] = None
    else:
        farm_crop["current_crop_id"] = current_crop_id
        try:
            last_crop_id = int(farm_crop.get("last_crop_id"))
        except Exception:
            last_crop_id = 0
        if current_crop_id > last_crop_id:
            farm_crop["last_crop_id"] = current_crop_id

    save_farm_crop(farm_crop)


def log_crop_event(shed_name, rec, crop_active):
    ensure_data_dir()
    try:
        crop_id = int(rec.get("crop_id"))
    except Exception:
        return

    placement_epoch = rec.get("placement_epoch")
    try:
        bird_count = int(rec.get("bird_count", 0) or 0)
    except Exception:
        bird_count = 0

    payload = {
        "ts": int(time.time()),
        "shed": shed_name,
        "crop_id": crop_id,
        "crop_active": 1 if crop_active else 0,
        "placement_epoch": placement_epoch,
        "bird_count": bird_count,
    }
    append_named_json_line("crop.ndjson", payload)


def log_mortality_event(shed_name, dest_shed, crop_id, bird_loss, note=""):
    payload = {
        "ts": int(time.time()),
        "shed": shed_name,
        "dest_shed": int(dest_shed),
        "crop_id": int(crop_id),
        "bird_loss": int(bird_loss),
        "note": str(note or "").strip(),
    }
    append_named_json_line("mortality.ndjson", payload)


def get_mortality_history_for_shed(shed_name, crop_id=None):
    entries = read_all_json_lines("mortality.ndjson")
    rows = []
    i = 0
    while i < len(entries):
        rec = entries[i]
        if str(rec.get("shed")) != str(shed_name):
            i += 1
            continue
        if crop_id is not None:
            try:
                if int(rec.get("crop_id")) != int(crop_id):
                    i += 1
                    continue
            except Exception:
                i += 1
                continue
        rows.append(rec)
        i += 1
    rows.sort(key=lambda r: int(r.get("ts", 0)))
    return rows


def mortality_total_for_shed_crop(shed_name, crop_id=None):
    rows = get_mortality_history_for_shed(shed_name, crop_id=crop_id)
    total = 0
    i = 0
    while i < len(rows):
        try:
            total += int(rows[i].get("bird_loss", 0) or 0)
        except Exception:
            pass
        i += 1
    return total


def mortality_payload_for_shed(shed_no):
    shed_name = shed_name_from_number(shed_no)
    state = load_shed_entries_state()
    entries = ensure_shed_entry_bucket(state, shed_name)
    target_rows = []
    i = 0
    while i < len(SHED_NUMBERS):
        dest_shed = SHED_NUMBERS[i]
        rec = clean_entry_record(entries.get(str(dest_shed), {}))
        if rec["crop_active"] == 1 and rec["bird_count"] > 0:
            target_rows.append({
                "dest_shed": dest_shed,
                "bird_count": rec["bird_count"],
                "crop_id": rec.get("crop_id"),
            })
        i += 1

    active_crop_id = get_active_crop_id_for_shed(shed_name)
    crop_filter = active_crop_id if active_crop_id not in [None, ""] else None
    history_rows = get_mortality_history_for_shed(shed_name, crop_id=crop_filter)
    i = 0
    while i < len(history_rows):
        try:
            history_rows[i]["ts_label"] = datetime.fromtimestamp(int(history_rows[i].get("ts"))).strftime("%d %b %Y %H:%M")
        except Exception:
            history_rows[i]["ts_label"] = "--"
        i += 1

    active_entries = active_entries_for_tile(entries)
    return {
        "shed_no": shed_no,
        "shed_name": shed_name,
        "active_crop_id": active_crop_id,
        "target_rows": target_rows,
        "history_rows": list(reversed(history_rows)),
        "mortality_total": mortality_total_for_shed_crop(shed_name, crop_filter),
        "active_birds": total_birds_from_active_entries(active_entries),
    }


def apply_mortality_to_shed(shed_no, dest_shed, bird_loss, note="", updated_by="dashboard"):
    if shed_no not in SHED_NUMBERS or dest_shed not in SHED_NUMBERS:
        return False, "Invalid mortality entry"
    if bird_loss <= 0:
        return False, "Invalid mortality entry"

    shed_name = shed_name_from_number(shed_no)
    state = load_shed_entries_state()
    entries = ensure_shed_entry_bucket(state, shed_name)
    rec = clean_entry_record(entries.get(str(dest_shed), {}))
    if rec["bird_count"] <= 0 or rec["crop_active"] != 1:
        return False, "No active birds in that entry"
    if bird_loss > rec["bird_count"]:
        return False, "Mortality exceeds birds in entry"

    crop_id = rec.get("crop_id")
    rec["bird_count"] = max(0, rec["bird_count"] - bird_loss)
    rec["updated_ts"] = int(time.time())
    rec["updated_by"] = str(updated_by or "dashboard")
    if rec["bird_count"] <= 0:
        log_crop_event(shed_name, rec, False)
        if str(dest_shed) in entries:
            del entries[str(dest_shed)]
    else:
        entries[str(dest_shed)] = rec

    log_mortality_event(shed_name, dest_shed, crop_id, bird_loss, note=note)
    log_event("office", "mortality_recorded", "Mortality recorded", shed_no=shed_no, detail="Entry Shed %d Loss %d" % (dest_shed, bird_loss))
    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)
    push_shed_state_to_controller(shed_no)
    return True, "Mortality recorded"


def normalize_pens(pens):
    out = []
    if not isinstance(pens, list):
        return out

    i = 0
    while i < len(pens):
        rec = pens[i]
        if not isinstance(rec, dict):
            i += 1
            continue

        name = str(rec.get("name", "")).strip()
        if not name:
            name = "Pen %d" % (len(out) + 1)

        try:
            bird_count = int(rec.get("bird_count", 0) or 0)
        except Exception:
            bird_count = 0

        if bird_count > 0:
            out.append({
                "name": name,
                "bird_count": bird_count,
            })
        i += 1

    return out


def clean_entry_record(rec):
    if not isinstance(rec, dict):
        rec = {}

    try:
        bird_count = int(rec.get("bird_count", 0) or 0)
    except Exception:
        bird_count = 0

    try:
        crop_active = 1 if int(rec.get("crop_active", 0) or 0) == 1 else 0
    except Exception:
        crop_active = 0

    try:
        placement_epoch = rec.get("placement_epoch")
        if placement_epoch not in [None, ""]:
            placement_epoch = int(placement_epoch)
        else:
            placement_epoch = None
    except Exception:
        placement_epoch = None

    try:
        crop_id = rec.get("crop_id")
        if crop_id not in [None, ""]:
            crop_id = int(crop_id)
        else:
            crop_id = None
    except Exception:
        crop_id = None

    try:
        updated_ts = rec.get("updated_ts")
        if updated_ts not in [None, ""]:
            updated_ts = int(updated_ts)
        else:
            updated_ts = None
    except Exception:
        updated_ts = None

    updated_by = str(rec.get("updated_by", "dashboard") or "dashboard")
    pens = normalize_pens(rec.get("pens", []))

    if pens:
        bird_count = 0
        i = 0
        while i < len(pens):
            bird_count += pens[i]["bird_count"]
            i += 1

    if bird_count <= 0:
        bird_count = 0
        crop_active = 0
        placement_epoch = None
        crop_id = None
        pens = []

    return {
        "bird_count": bird_count,
        "crop_active": crop_active,
        "placement_epoch": placement_epoch,
        "crop_id": crop_id,
        "updated_ts": updated_ts,
        "updated_by": updated_by,
        "pens": pens,
    }


def controller_url_for_shed(shed_no):
    config = load_controller_config()
    keys = [str(shed_no), shed_name_from_number(shed_no)]

    for key in keys:
        rec = config.get(key)
        if isinstance(rec, dict):
            url = rec.get("sync_url")
        else:
            url = rec
        if url:
            return str(url).rstrip("/")

    return None


def shed_sync_version_for_entries(entries):
    latest_ts = 0
    for key in entries:
        rec = clean_entry_record(entries.get(key, {}))
        try:
            latest_ts = max(latest_ts, int(rec.get("updated_ts") or 0))
        except Exception:
            pass
    return latest_ts


def shed_sync_payload(shed_no):
    state = load_shed_entries_state()
    shed_name = shed_name_from_number(shed_no)
    entries = ensure_shed_entry_bucket(state, shed_name)
    payload_entries = {}

    for key in entries:
        payload_entries[str(key)] = clean_entry_record(entries.get(key, {}))

    crop = active_crop_record_for_shed(shed_name)
    try:
        active_crop_id = int(crop.get("crop_id"))
    except Exception:
        active_crop_id = None

    days = get_daily_history_for_shed(shed_name, max_days=40, crop_id=active_crop_id)
    yesterday_water = None
    yesterday_feed = None
    if len(days) >= 1:
        yesterday_water = days[-1].get("water")
        yesterday_feed = days[-1].get("feed")

    sync_version = shed_sync_version_for_entries(entries)

    return {
        "shed_no": shed_no,
        "shed": shed_name,
        "entries": payload_entries,
        "current_crop_id": get_active_crop_id_for_shed(shed_name),
        "sync_version": sync_version,
        "source_updated_ts": sync_version,
        "summary": {
            "water_7to7": yesterday_water,
            "feed_7to7": yesterday_feed,
            "mortality_total": mortality_total_for_shed_crop(shed_name, active_crop_id if active_crop_id is not None else None),
        },
        "generated_ts": int(time.time()),
    }


def push_shed_state_to_controller(shed_no):
    base_url = controller_url_for_shed(shed_no)
    if not base_url:
        return False, "No controller sync URL configured"

    payload = shed_sync_payload(shed_no)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/api/dashboard-sync",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            if 200 <= int(resp.status) < 300:
                return True, "Pushed"
            log_event("office", "controller_push_failed", "Controller returned HTTP %d" % int(resp.status), shed_no=shed_no, detail=base_url)
            return False, "Controller returned HTTP %d" % int(resp.status)
    except urllib.error.URLError as exc:
        log_event("office", "controller_push_failed", "Controller push failed", shed_no=shed_no, detail=str(exc))
        return False, str(exc)
    except Exception as exc:
        log_event("office", "controller_push_failed", "Controller push failed", shed_no=shed_no, detail=str(exc))
        return False, str(exc)


def apply_external_shed_entries(shed_no, incoming_entries, source):
    state = load_shed_entries_state()
    shed_name = shed_name_from_number(shed_no)
    entries = ensure_shed_entry_bucket(state, shed_name)
    now_ts = int(time.time())
    changed = False

    cleaned_incoming = {}
    if isinstance(incoming_entries, dict):
        for key in incoming_entries:
            try:
                dest_shed = int(key)
            except Exception:
                continue
            if dest_shed not in SHED_NUMBERS:
                continue

            rec = clean_entry_record(incoming_entries.get(key, {}))
            if rec["updated_ts"] is None:
                rec["updated_ts"] = now_ts
            rec["updated_by"] = source
            if rec["bird_count"] > 0 and rec["crop_active"] == 1 and rec["crop_id"] is None:
                rec["crop_id"] = crop_id_for_new_start(state)
            cleaned_incoming[str(dest_shed)] = rec

    existing_keys = list(entries.keys())
    for key in existing_keys:
        if key not in cleaned_incoming:
            prev = clean_entry_record(entries.get(key, {}))
            if prev["bird_count"] > 0 or prev["crop_id"] is not None:
                log_crop_event(shed_name, prev, False)
                changed = True
            del entries[key]

    for key in cleaned_incoming:
        prev = clean_entry_record(entries.get(key, {}))
        new_rec = cleaned_incoming[key]

        if prev == new_rec:
            continue

        entries[key] = new_rec
        changed = True

        prev_active = prev["bird_count"] > 0 and prev["crop_active"] == 1 and prev["crop_id"] is not None
        new_active = new_rec["bird_count"] > 0 and new_rec["crop_active"] == 1 and new_rec["crop_id"] is not None

        if prev_active and (not new_active or prev["crop_id"] != new_rec["crop_id"]):
            log_crop_event(shed_name, prev, False)
        if new_active:
            log_crop_event(shed_name, new_rec, True)

    if not changed:
        return False

    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)
    log_event("office", "shed_sync_received", "Updated from %s" % source, shed_no=shed_no)
    return True


def fmt_value(v, fmt=None):
    if v is None:
        return "--"
    try:
        if fmt == "f0":
            return f"{float(v):,.0f}"
        if fmt == "f1":
            return f"{float(v):,.1f}"
        if fmt == "f2":
            return f"{float(v):,.2f}"
        if fmt == "f3":
            return f"{float(v):,.3f}"
        if fmt == "i":
            return f"{int(v):,d}"
        return str(v)
    except Exception:
        return "--"


def custom_day_key(dt_obj):
    if dt_obj.hour < 7:
        dt_obj = dt_obj - timedelta(days=1)
    return dt_obj.strftime("%Y-%m-%d")


def shed_name_from_number(shed_no):
    return "Shed %d" % int(shed_no)


def active_alarms_by_shed():
    payloads = read_all_json_lines("alarm.ndjson")
    latest = {}

    i = 0
    while i < len(payloads):
        p = payloads[i]
        shed = p.get("shed")
        key = p.get("alarm_key")
        if not shed or not key:
            i += 1
            continue

        try:
            ts = int(p.get("ts", 0))
        except Exception:
            ts = 0

        group_key = (shed, key)
        prev = latest.get(group_key)
        if prev is None or ts >= prev["ts"]:
            latest[group_key] = {
                "ts": ts,
                "active": bool(p.get("active", False)),
                "alarm_key": key,
                "message": p.get("message", ""),
            }
        i += 1

    result = {}
    for group_key in latest:
        shed = group_key[0]
        rec = latest[group_key]
        if rec.get("active"):
            if shed not in result:
                result[shed] = []
            result[shed].append(rec)

    return result


def active_borehole_alarms():
    payloads = read_all_json_lines("borehole_alarm.ndjson")
    latest = {}

    i = 0
    while i < len(payloads):
        p = payloads[i]
        key = p.get("alarm_key")
        if not key:
            i += 1
            continue

        try:
            ts = int(p.get("ts", 0))
        except Exception:
            ts = 0

        prev = latest.get(key)
        if prev is None or ts >= prev["ts"]:
            latest[key] = {
                "ts": ts,
                "active": bool(p.get("active", False)),
                "alarm_key": key,
                "message": p.get("message", ""),
            }
        i += 1

    result = []
    for key in latest:
        rec = latest[key]
        if rec.get("active"):
            result.append(rec)
    return result


def average_last_n(values, n):
    nums = []
    i = max(0, len(values) - n)
    while i < len(values):
        try:
            v = float(values[i])
            if v > 0:
                nums.append(v)
        except Exception:
            pass
        i += 1

    if not nums:
        return None
    return sum(nums) / len(nums)


def estimate_runout_from_average(feed_kg, avg_daily_feed_kg):
    try:
        feed_kg = float(feed_kg)
        avg_daily_feed_kg = float(avg_daily_feed_kg)
    except Exception:
        return "--"

    if feed_kg <= 0 or avg_daily_feed_kg <= 0:
        return "--"

    try:
        days_left = feed_kg / avg_daily_feed_kg
        runout_dt = datetime.now() + timedelta(days=days_left)
        return runout_dt.strftime("%d %b %H:%M")
    except Exception:
        return "--"


def latest_crop_by_shed():
    entries = read_all_json_lines("crop.ndjson")
    result = {}
    latest_ts = {}

    i = 0
    while i < len(entries):
        rec = entries[i]
        shed = rec.get("shed")
        if not shed:
            i += 1
            continue

        try:
            ts = int(rec.get("ts", 0))
        except Exception:
            ts = 0

        prev_ts = latest_ts.get(shed)
        if prev_ts is None or ts >= prev_ts:
            latest_ts[shed] = ts
            result[shed] = rec
        i += 1

    return result


def add_running_totals(rows):
    out = []
    running_water = 0.0
    running_feed = 0.0

    i = 0
    while i < len(rows):
        r = dict(rows[i])

        try:
            w = float(r.get("water")) if r.get("water") is not None else 0.0
        except Exception:
            w = 0.0

        try:
            f = float(r.get("feed")) if r.get("feed") is not None else 0.0
        except Exception:
            f = 0.0

        running_water += w
        running_feed += f

        r["running_water"] = running_water
        r["running_feed"] = running_feed
        out.append(r)
        i += 1

    return out


def add_running_water_totals(rows):
    out = []
    running_water = 0.0

    i = 0
    while i < len(rows):
        r = dict(rows[i])

        try:
            w = float(r.get("water")) if r.get("water") is not None else 0.0
        except Exception:
            w = 0.0

        running_water += w
        r["running_water"] = running_water
        out.append(r)
        i += 1

    return out


def get_hourly_history_for_shed(shed_name, max_points=168, crop_id=None):
    entries = read_all_json_lines("hourly.ndjson")
    rows = []

    i = 0
    while i < len(entries):
        p = entries[i]
        if p.get("shed") != shed_name:
            i += 1
            continue

        if crop_id is not None:
            try:
                rec_crop_id = int(p.get("crop_id"))
            except Exception:
                i += 1
                continue
            if rec_crop_id != int(crop_id):
                i += 1
                continue

        try:
            hour_epoch = int(p.get("hour_epoch"))
        except Exception:
            i += 1
            continue

        try:
            dt_obj = datetime.fromtimestamp(hour_epoch)
            label = dt_obj.strftime("%d %b %H:%M")
        except Exception:
            i += 1
            continue

        try:
            water_val = float(p.get("water_hour_liters")) if p.get("water_hour_liters") is not None else None
        except Exception:
            water_val = None

        try:
            feed_val = float(p.get("feed_hour_kg")) if p.get("feed_hour_kg") is not None else None
        except Exception:
            feed_val = None

        rows.append({
            "epoch": hour_epoch,
            "label": label,
            "water": water_val,
            "feed": feed_val,
            "crop_id": p.get("crop_id"),
        })
        i += 1

    rows.sort(key=lambda x: x["epoch"])
    if max_points and len(rows) > max_points:
        rows = rows[-max_points:]
    return rows


def get_daily_history_for_shed(shed_name, max_days=40, crop_id=None):
    hourly_rows = get_hourly_history_for_shed(shed_name, max_points=0, crop_id=crop_id)

    day_totals = {}
    latest_epoch = None

    i = 0
    while i < len(hourly_rows):
        row = hourly_rows[i]
        try:
            hour_epoch = int(row.get("epoch"))
            dt_obj = datetime.fromtimestamp(hour_epoch)
        except Exception:
            i += 1
            continue

        day_key = custom_day_key(dt_obj)

        if latest_epoch is None or hour_epoch > latest_epoch:
            latest_epoch = hour_epoch

        if day_key not in day_totals:
            day_totals[day_key] = {"water": 0.0, "feed": 0.0}

        try:
            if row.get("water") is not None:
                day_totals[day_key]["water"] += float(row.get("water"))
        except Exception:
            pass

        try:
            if row.get("feed") is not None:
                day_totals[day_key]["feed"] += float(row.get("feed"))
        except Exception:
            pass

        i += 1

    active_key = None
    if latest_epoch is not None:
        try:
            active_key = custom_day_key(datetime.fromtimestamp(latest_epoch))
        except Exception:
            active_key = None

    keys = sorted(day_totals.keys())
    rows = []

    j = 0
    while j < len(keys):
        day_key = keys[j]
        if day_key != active_key:
            try:
                dt_obj = datetime.strptime(day_key, "%Y-%m-%d")
                label = dt_obj.strftime("%d %b")
            except Exception:
                label = day_key

            rows.append({
                "key": day_key,
                "label": label,
                "water": day_totals[day_key]["water"],
                "feed": day_totals[day_key]["feed"],
            })
        j += 1

    if max_days and len(rows) > max_days:
        rows = rows[-max_days:]

    return rows


def get_recent_crops_for_shed(shed_name, max_crops=6):
    entries = read_all_json_lines("hourly.ndjson")
    crop_map = {}

    i = 0
    while i < len(entries):
        p = entries[i]
        if p.get("shed") != shed_name:
            i += 1
            continue

        try:
            crop_id = int(p.get("crop_id"))
            hour_epoch = int(p.get("hour_epoch"))
        except Exception:
            i += 1
            continue

        rec = crop_map.get(crop_id)
        if rec is None:
            crop_map[crop_id] = {
                "crop_id": crop_id,
                "first_epoch": hour_epoch,
                "last_epoch": hour_epoch,
            }
        else:
            if hour_epoch < rec["first_epoch"]:
                rec["first_epoch"] = hour_epoch
            if hour_epoch > rec["last_epoch"]:
                rec["last_epoch"] = hour_epoch

        i += 1

    rows = []
    for crop_id in crop_map:
        rec = crop_map[crop_id]
        try:
            start_label = datetime.fromtimestamp(rec["first_epoch"]).strftime("%d %b %Y")
        except Exception:
            start_label = "--"

        try:
            end_label = datetime.fromtimestamp(rec["last_epoch"]).strftime("%d %b %Y")
        except Exception:
            end_label = "--"

        rows.append({
            "crop_id": rec["crop_id"],
            "first_epoch": rec["first_epoch"],
            "last_epoch": rec["last_epoch"],
            "start_label": start_label,
            "end_label": end_label,
        })

    rows.sort(key=lambda x: x["last_epoch"], reverse=True)
    if max_crops and len(rows) > max_crops:
        rows = rows[:max_crops]
    return rows


def get_active_crop_id_for_shed(shed_name):
    crop = active_crop_record_for_shed(shed_name)
    if not crop:
        crop_map = latest_crop_by_shed()
        crop = crop_map.get(shed_name, {})
    try:
        return int(crop.get("crop_id"))
    except Exception:
        return None


def get_borehole_hourly_history(max_points=168):
    entries = read_all_json_lines("borehole_hourly.ndjson")
    rows = []

    i = 0
    while i < len(entries):
        p = entries[i]

        try:
            hour_epoch = int(p.get("hour_epoch"))
        except Exception:
            i += 1
            continue

        try:
            dt_obj = datetime.fromtimestamp(hour_epoch)
            label = dt_obj.strftime("%d %b %H:%M")
        except Exception:
            i += 1
            continue

        try:
            water_val = float(p.get("water_hour_liters")) if p.get("water_hour_liters") is not None else None
        except Exception:
            water_val = None

        rows.append({
            "epoch": hour_epoch,
            "label": label,
            "water": water_val,
        })
        i += 1

    rows.sort(key=lambda x: x["epoch"])
    if max_points and len(rows) > max_points:
        rows = rows[-max_points:]
    return rows


def get_borehole_daily_history(max_days=40):
    hourly_rows = get_borehole_hourly_history(max_points=0)

    day_totals = {}
    latest_epoch = None

    i = 0
    while i < len(hourly_rows):
        row = hourly_rows[i]
        try:
            hour_epoch = int(row.get("epoch"))
            dt_obj = datetime.fromtimestamp(hour_epoch)
        except Exception:
            i += 1
            continue

        day_key = custom_day_key(dt_obj)

        if latest_epoch is None or hour_epoch > latest_epoch:
            latest_epoch = hour_epoch

        if day_key not in day_totals:
            day_totals[day_key] = {"water": 0.0}

        try:
            if row.get("water") is not None:
                day_totals[day_key]["water"] += float(row.get("water"))
        except Exception:
            pass

        i += 1

    active_key = None
    if latest_epoch is not None:
        try:
            active_key = custom_day_key(datetime.fromtimestamp(latest_epoch))
        except Exception:
            active_key = None

    keys = sorted(day_totals.keys())
    rows = []

    j = 0
    while j < len(keys):
        day_key = keys[j]
        if day_key != active_key:
            try:
                dt_obj = datetime.strptime(day_key, "%Y-%m-%d")
                label = dt_obj.strftime("%d %b")
            except Exception:
                label = day_key

            rows.append({
                "key": day_key,
                "label": label,
                "water": day_totals[day_key]["water"],
            })
        j += 1

    if max_days and len(rows) > max_days:
        rows = rows[-max_days:]

    return rows


def load_shed_entries_state():
    path = os.path.join(DATA_DIR, "shed_entries.json")
    raw = read_json_file(path, {})
    if not isinstance(raw, dict):
        raw = {}

    result = {}
    for shed_no in SHED_NUMBERS:
        shed_name = shed_name_from_number(shed_no)
        shed_rec = raw.get(shed_name, {})
        if not isinstance(shed_rec, dict):
            shed_rec = {}

        entries = shed_rec.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}

        clean_entries = {}
        for key in entries:
            try:
                dest_shed = int(key)
            except Exception:
                continue
            clean_entries[str(dest_shed)] = clean_entry_record(entries.get(key, {}))

        result[shed_name] = {"entries": clean_entries}

    return result


def save_shed_entries_state(state):
    path = os.path.join(DATA_DIR, "shed_entries.json")
    write_json_file_atomic(path, state)


def ensure_shed_entry_bucket(state, shed_name):
    if shed_name not in state or not isinstance(state.get(shed_name), dict):
        state[shed_name] = {"entries": {}}
    if "entries" not in state[shed_name] or not isinstance(state[shed_name].get("entries"), dict):
        state[shed_name]["entries"] = {}
    return state[shed_name]["entries"]


def active_entries_for_tile(entries):
    out = {}
    for key in entries:
        rec = entries.get(key, {})
        try:
            bird_count = int(rec.get("bird_count", 0) or 0)
        except Exception:
            bird_count = 0
        try:
            crop_active = int(rec.get("crop_active", 0) or 0)
        except Exception:
            crop_active = 0

        if bird_count > 0 and crop_active == 1:
            out[str(key)] = bird_count
    return out


def total_birds_from_active_entries(entries):
    total = 0
    for key in entries:
        try:
            total += int(entries[key])
        except Exception:
            pass
    return total


def has_any_active_entry(entries):
    for key in entries:
        rec = entries.get(key, {})
        try:
            bird_count = int(rec.get("bird_count", 0) or 0)
        except Exception:
            bird_count = 0
        try:
            crop_active = int(rec.get("crop_active", 0) or 0)
        except Exception:
            crop_active = 0

        if bird_count > 0 and crop_active == 1:
            return True
    return False


def entry_summary_text(current_shed_no, active_entries):
    keys = []
    for key in active_entries:
        try:
            keys.append(int(key))
        except Exception:
            pass
    keys.sort()

    if len(keys) == 1 and keys[0] == int(current_shed_no):
        return ""

    parts = []
    i = 0
    while i < len(keys):
        shed_no = keys[i]
        try:
            bird_count = int(active_entries.get(str(shed_no), 0))
        except Exception:
            bird_count = 0

        if bird_count > 0:
            parts.append("Shed %d: %s" % (shed_no, fmt_value(bird_count, "i")))
        i += 1

    if not parts:
        return ""

    return " - ".join(parts)


def build_detail_entry_rows(current_shed_no, entries):
    rows = []
    i = 0
    while i < len(SHED_NUMBERS):
        dest_shed = SHED_NUMBERS[i]
        rec = entries.get(str(dest_shed), {})

        try:
            bird_count = int(rec.get("bird_count", 0) or 0)
        except Exception:
            bird_count = 0

        try:
            crop_active = 1 if int(rec.get("crop_active", 0) or 0) == 1 else 0
        except Exception:
            crop_active = 0

        placement_epoch = rec.get("placement_epoch")
        placement_str = "--"
        if placement_epoch is not None:
            try:
                placement_str = datetime.fromtimestamp(int(placement_epoch)).strftime("%d %b %Y %H:%M")
            except Exception:
                placement_str = "--"

        can_move = (dest_shed != current_shed_no) and crop_active == 1 and bird_count > 0
        pens = normalize_pens(rec.get("pens", []))
        pens_parts = []
        p = 0
        while p < len(pens):
            pens_parts.append("%s: %s" % (pens[p]["name"], fmt_value(pens[p]["bird_count"], "i")))
            p += 1

        rows.append({
            "dest_shed": dest_shed,
            "bird_count": bird_count,
            "crop_active": crop_active,
            "placement_epoch": placement_epoch,
            "placement_str": placement_str,
            "crop_id": rec.get("crop_id"),
            "pens_text": ", ".join(pens_parts),
            "can_move": can_move,
        })
        i += 1
    return rows


def build_borehole_row():
    live = latest_borehole_live()
    alarms = active_borehole_alarms()
    days = get_borehole_daily_history(max_days=40)

    daily_water = None
    weekly_water = 0.0

    if len(days) >= 1:
        daily_water = days[-1].get("water")

    d = max(0, len(days) - 7)
    while d < len(days):
        try:
            if days[d].get("water") is not None:
                weekly_water += float(days[d].get("water"))
        except Exception:
            pass
        d += 1

    last_7_days = []
    start_idx = max(0, len(days) - 7)
    i = start_idx
    while i < len(days):
        last_7_days.append({
            "label": days[i].get("label"),
            "water": fmt_value(days[i].get("water"), "f0"),
        })
        i += 1

    water_lpm = live.get("water_lpm")
    updated_ts = live.get("ts")

    alarm_active = len(alarms) > 0
    alarm_key = alarms[0].get("alarm_key", "") if alarm_active else ""
    alarm_msg = alarms[0].get("message", "") if alarm_active else ""

    try:
        water_lpm_f = float(water_lpm) if water_lpm is not None else None
    except Exception:
        water_lpm_f = None

    water_glow = "flow-red" if (water_lpm_f is None or water_lpm_f < 0.1) else "flow-green"
    tile_state = "online" if bool(live) else "offline"

    if updated_ts:
        try:
            tt = datetime.fromtimestamp(int(updated_ts))
            updated_str = tt.strftime("%d %b %H:%M:%S")
        except Exception:
            updated_str = "--"
    else:
        updated_str = "--"

    return {
        "name": "Bore Hole",
        "has_data": bool(live) or bool(days),
        "tile_state": tile_state,
        "water_lpm": fmt_value(water_lpm, "f2"),
        "water_glow": water_glow,
        "daily_water": fmt_value(daily_water, "f0"),
        "weekly_water": fmt_value(weekly_water if weekly_water > 0 else None, "f0"),
        "last_7_days": last_7_days,
        "updated": updated_str,
        "alarm_active": alarm_active,
        "alarm_key": alarm_key,
        "alarm_msg": alarm_msg,
    }


def build_overall_summary():
    state = load_shed_entries_state()
    live_map = latest_live_by_shed()
    controller_meta_map = load_controller_meta()
    farm_crop = load_farm_crop()
    current_crop_id = farm_crop.get("current_crop_id")

    total_birds_remaining = 0
    total_birds_placed = 0
    total_water = 0.0
    total_feed = 0.0
    any_online = False

    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        shed_name = shed_name_from_number(shed_no)

        live = effective_live_for_shed(live_map, controller_meta_map, shed_no)
        entries = ensure_shed_entry_bucket(state, shed_name)
        active_entries = active_entries_for_tile(entries)

        if live or has_any_active_entry(entries):
            any_online = True

        birds_remaining = total_birds_from_active_entries(active_entries)
        total_birds_remaining += birds_remaining
        total_birds_placed += birds_remaining
        total_birds_placed += mortality_total_for_shed_crop(shed_name, current_crop_id if current_crop_id not in [None, ""] else None)

        crop = active_crop_record_for_shed(shed_name)
        try:
            active_crop_id = int(crop.get("crop_id"))
        except Exception:
            active_crop_id = None

        hourly_rows = get_hourly_history_for_shed(shed_name, max_points=0, crop_id=active_crop_id)

        h = 0
        while h < len(hourly_rows):
            try:
                if hourly_rows[h].get("water") is not None:
                    total_water += float(hourly_rows[h].get("water"))
            except Exception:
                pass

            try:
                if hourly_rows[h].get("feed") is not None:
                    total_feed += float(hourly_rows[h].get("feed"))
            except Exception:
                pass

            h += 1

        i += 1

    tile_state = "online" if any_online else "offline"

    return {
        "tile_state": tile_state,
        "birds_placed": fmt_value(total_birds_placed if total_birds_placed > 0 else None, "i"),
        "birds_remaining": fmt_value(total_birds_remaining if total_birds_remaining > 0 else None, "i"),
        "water": fmt_value(total_water if total_water > 0 else None, "f0"),
        "feed": fmt_value(total_feed if total_feed > 0 else None, "f1"),
        "farm_crop_id": fmt_value(farm_crop.get("current_crop_id"), "i"),
    }


def build_rows():
    ensure_data_dir()

    live_map = latest_live_by_shed()
    alarms_map = active_alarms_by_shed()
    controller_meta_map = load_controller_meta()
    state = load_shed_entries_state()
    farm_crop = load_farm_crop()
    current_farm_crop_id = farm_crop.get("current_crop_id")

    rows = []
    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        shed = shed_name_from_number(shed_no)
        live = effective_live_for_shed(live_map, controller_meta_map, shed_no)
        alarms = list(alarms_map.get(shed, []))
        controller_alarms = controller_alarms_for_shed(controller_meta_map, shed_no)
        if controller_alarms:
            alarms.extend(controller_alarms)
        crop = active_crop_record_for_shed(shed)
        entries = ensure_shed_entry_bucket(state, shed)
        active_entries = active_entries_for_tile(entries)
        has_active_entry = has_any_active_entry(entries)

        try:
            active_crop_id = int(crop.get("crop_id"))
        except Exception:
            active_crop_id = None

        days = get_daily_history_for_shed(shed, max_days=40, crop_id=active_crop_id)
        all_crop_hourly = get_hourly_history_for_shed(shed, max_points=0, crop_id=active_crop_id)

        total_water_to_date = 0.0
        total_feed_to_date = 0.0

        h = 0
        while h < len(all_crop_hourly):
            try:
                if all_crop_hourly[h].get("water") is not None:
                    total_water_to_date += float(all_crop_hourly[h].get("water"))
            except Exception:
                pass
            try:
                if all_crop_hourly[h].get("feed") is not None:
                    total_feed_to_date += float(all_crop_hourly[h].get("feed"))
            except Exception:
                pass
            h += 1

        birds = total_birds_from_active_entries(active_entries)
        allocation_text = entry_summary_text(shed_no, active_entries)

        crop_id = crop.get("crop_id")
        placement_epoch = crop.get("placement_epoch")
        crop_active = crop.get("crop_active")

        bird_age = None
        try:
            if placement_epoch is not None and int(crop_active) == 1:
                age_s = int(time.time()) - int(placement_epoch)
                if age_s < 0:
                    age_s = 0
                bird_age = age_s // 86400
        except Exception:
            bird_age = None

        yesterday_water = None
        yesterday_feed = None
        if len(days) >= 1:
            yesterday_water = days[-1].get("water")
            yesterday_feed = days[-1].get("feed")

        recent_feed_days = []
        d = 0
        while d < len(days):
            val = days[d].get("feed")
            if val is not None:
                recent_feed_days.append(val)
            d += 1

        avg_feed_day_kg = average_last_n(recent_feed_days, 3)

        l_per_bird_yday = None
        kg_per_bird_yday = None
        avg_feed_per_bird = None

        if birds > 0 and yesterday_water is not None:
            try:
                l_per_bird_yday = float(yesterday_water) / float(birds)
            except Exception:
                l_per_bird_yday = None

        if birds > 0 and yesterday_feed is not None:
            try:
                kg_per_bird_yday = float(yesterday_feed) / float(birds)
            except Exception:
                kg_per_bird_yday = None

        if birds > 0 and avg_feed_day_kg is not None:
            try:
                avg_feed_per_bird = float(avg_feed_day_kg) / float(birds)
            except Exception:
                avg_feed_per_bird = None

        temp_c = live.get("temp_c")
        rh_pct = live.get("rh_pct")
        feed_kg = live.get("feed_kg")
        updated_ts = live.get("ts")
        water_lpm = live.get("water_lpm")

        alarm_active = len(alarms) > 0
        alarm_key = alarms[0].get("alarm_key", "") if alarm_active else ""
        alarm_msg = alarms[0].get("message", "") if alarm_active else ""

        try:
            water_lpm_f = float(water_lpm) if water_lpm is not None else None
        except Exception:
            water_lpm_f = None

        water_glow = "flow-red" if (water_lpm_f is None or water_lpm_f < 0.1) else "flow-green"

        try:
            feed_val = float(feed_kg) if feed_kg is not None else None
        except Exception:
            feed_val = None

        if feed_val is None or feed_val < 2000:
            feed_glow = "feed-red"
        else:
            feed_glow = "feed-green"

        if bool(live) or has_active_entry:
            tile_state = "online"
        else:
            tile_state = "offline"

        if updated_ts:
            try:
                tt = datetime.fromtimestamp(int(updated_ts))
                updated_str = tt.strftime("%d %b %H:%M:%S")
            except Exception:
                updated_str = "--"
        else:
            updated_str = "--"

        runout_est = estimate_runout_from_average(feed_kg, avg_feed_day_kg)

        rows.append({
            "shed": shed,
            "shed_no": shed_no,
            "has_data": bool(live) or bool(days) or bool(crop) or bool(active_entries),
            "has_active_entry": has_active_entry,
            "tile_state": tile_state,
            "temp_c": fmt_value(temp_c, "f1"),
            "rh_pct": fmt_value(rh_pct, "f0"),
            "feed_kg": fmt_value(feed_kg, "f0"),
            "feed_glow": feed_glow,
            "water_lpm": fmt_value(water_lpm, "f2"),
            "water_glow": water_glow,
            "crop_id": fmt_value(crop_id),
            "farm_crop_id": fmt_value(current_farm_crop_id, "i"),
            "bird_count": fmt_value(birds if birds > 0 else None, "i"),
            "bird_age": fmt_value(bird_age, "i"),
            "water_7to7": fmt_value(yesterday_water, "f0"),
            "feed_7to7": fmt_value(yesterday_feed, "f1"),
            "l_per_bird": fmt_value(l_per_bird_yday, "f3"),
            "kg_per_bird": fmt_value(kg_per_bird_yday, "f3"),
            "avg_feed_per_bird": fmt_value(avg_feed_per_bird, "f3"),
            "runout_est": runout_est,
            "updated": updated_str,
            "alarm_active": alarm_active,
            "alarm_key": alarm_key,
            "alarm_msg": alarm_msg,
            "total_water_to_date": fmt_value(total_water_to_date, "f0"),
            "total_feed_to_date": fmt_value(total_feed_to_date, "f1"),
            "allocation_text": allocation_text,
            "mortality_total": fmt_value(mortality_total_for_shed_crop(shed, active_crop_id), "i"),
        })
        i += 1

    return rows


def build_dashboard_context():
    return {
        "sheds": build_rows(),
        "borehole": build_borehole_row(),
        "overall": build_overall_summary(),
    }


def build_dashboard_water_context():
    live_map = latest_live_by_shed()
    controller_meta_map = load_controller_meta()
    sheds = []

    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        live = effective_live_for_shed(live_map, controller_meta_map, shed_no)
        water_lpm = live.get("water_lpm")
        try:
            water_lpm_f = float(water_lpm) if water_lpm is not None else None
        except Exception:
            water_lpm_f = None

        sheds.append({
            "shed_no": shed_no,
            "water_lpm": fmt_value(water_lpm, "f2"),
            "water_glow": "flow-red" if (water_lpm_f is None or water_lpm_f < 0.1) else "flow-green",
        })
        i += 1

    borehole_live = latest_borehole_live()
    borehole_water = borehole_live.get("water_lpm")
    try:
        borehole_water_f = float(borehole_water) if borehole_water is not None else None
    except Exception:
        borehole_water_f = None

    return {
        "sheds": sheds,
        "borehole": {
            "water_lpm": fmt_value(borehole_water, "f2"),
            "water_glow": "flow-red" if (borehole_water_f is None or borehole_water_f < 0.1) else "flow-green",
        },
        "ts": int(time.time()),
    }


HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Cherry Dene Farm Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #e4e4e4;
        }
        .wrap {
            max-width: 1900px;
            margin: 0 auto;
            padding: 12px;
        }
        .topbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            gap: 12px;
            flex-wrap: wrap;
        }
        .topbar-left {
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }
        .top-links {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .top-link {
            color: #ededed;
            text-decoration: none;
            font-size: 13px;
            padding: 7px 10px;
            border: 1px solid #7c7c7c;
            border-radius: 10px;
            background: #6a6a6a;
        }
        h1 {
            margin: 0;
            font-size: 28px;
            color: #f0f0f0;
            text-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .datetime {
            font-size: 18px;
            font-weight: bold;
            color: #efefef;
            text-shadow:
                0 0 8px rgba(255,255,255,0.24),
                0 0 16px rgba(255,255,255,0.12);
            white-space: nowrap;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 10px;
        }
        .card-link {
            text-decoration: none;
            color: inherit;
            display: block;
        }
        .card {
            background: #737373;
            border: 2px solid #888;
            border-radius: 12px;
            padding: 10px;
            box-sizing: border-box;
            min-height: 455px;
            cursor: pointer;
            transition: transform 0.12s ease, border-color 0.12s ease, box-shadow 0.12s ease;
        }
        .card:hover {
            transform: translateY(-2px);
        }
        .card.alarm {
            border-color: #ff5b5b;
            background: #241619;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
        }
        .card.online {
            border-color: #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .card.offline {
            border-color: #4db6ff;
            box-shadow:
                0 0 10px rgba(77,182,255,0.95),
                0 0 20px rgba(77,182,255,0.65),
                0 0 34px rgba(77,182,255,0.35);
        }
        .card.nodata {
            opacity: 0.90;
        }
        .head {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 6px;
        }
        .head-left {
            display: flex;
            flex-direction: column;
            gap: 2px;
            align-items: flex-start;
        }
        .shed {
            font-size: 22px;
            font-weight: bold;
        }
        .birds-top {
            font-size: 14px;
            color: #d9d9d9;
        }
        .alloc-top {
            font-size: 13px;
            color: #d6d6d6;
            line-height: 1.25;
        }
        .badge-wrap {
            display: flex;
            flex-direction: column;
            gap: 4px;
            align-items: flex-end;
        }
        .badge {
            font-size: 11px;
            padding: 3px 7px;
            border-radius: 8px;
            border: 1px solid #8d8d8d;
            color: #f0f0f0;
            background: transparent;
        }
        .badge.alarm {
            border-color: #d55;
            color: #ff8a8a;
        }
        .badge.active {
            border-color: #35d07f;
            color: #b8ffd2;
        }
        .topline {
            display: flex;
            gap: 10px;
            margin-bottom: 8px;
            flex-wrap: wrap;
        }
        .mini {
            min-width: 70px;
        }
        .mini-label {
            font-size: 11px;
            color: #d0d0d0;
        }
        .mini-val {
            font-size: 20px;
            font-weight: bold;
            line-height: 1.1;
        }
        .big-pair {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 8px;
        }
        .big-one {
            display: grid;
            grid-template-columns: 1fr;
            gap: 8px;
            margin-bottom: 8px;
        }
        .section {
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #8b8b8b;
        }
        .metric-grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 6px 8px;
        }
        .metric-grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 6px 8px;
        }
        .metric {
            background: #686868;
            border: 1px solid #858585;
            border-radius: 8px;
            padding: 5px 7px;
        }
        .metric-label {
            font-size: 10px;
            color: #d2d2d2;
        }
        .metric-val {
            font-size: 16px;
            font-weight: bold;
            line-height: 1.1;
            margin-top: 2px;
        }
        .metric-big .metric-label {
            font-size: 12px;
        }
        .metric-big .metric-val {
            font-size: 34px;
        }
        .flow-green {
            border: 2px solid #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .flow-red {
            border: 2px solid #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
        }
        .feed-green {
            border: 2px solid #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .feed-red {
            border: 2px solid #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
        }
        .row {
            margin: 4px 0;
            font-size: 13px;
        }
        .label {
            display: inline-block;
            min-width: 92px;
            color: #d0d0d0;
        }
        .alarmbox {
            margin-top: 8px;
            padding: 8px;
            border-radius: 8px;
            border: 1px solid #6d2b2b;
            background: #30191c;
            font-size: 12px;
        }
        .bore-list {
            margin-top: 8px;
            font-size: 12px;
        }
        .bore-row {
            display: flex;
            justify-content: space-between;
            gap: 10px;
            padding: 3px 0;
            border-bottom: 1px solid #818181;
        }
        .bore-row:last-child {
            border-bottom: none;
        }
        .bore-date {
            color: #dadada;
        }
        .bore-val {
            font-weight: bold;
        }
        .summary-tile {
            margin-top: 12px;
            background: #737373;
            border: 2px solid #888;
            border-radius: 12px;
            padding: 14px;
        }
        .summary-tile.online {
            border-color: #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.45),
                0 0 34px rgba(53,208,127,0.22);
        }
        .summary-tile.offline {
            border-color: #4db6ff;
            box-shadow:
                0 0 10px rgba(77,182,255,0.95),
                0 0 20px rgba(77,182,255,0.45),
                0 0 34px rgba(77,182,255,0.22);
        }
        .summary-title {
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 10px;
        }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 10px;
        }
        .summary-box {
            background: #686868;
            border: 1px solid #858585;
            border-radius: 10px;
            padding: 10px 12px;
        }
        .summary-label {
            font-size: 12px;
            color: #d2d2d2;
        }
        .summary-val {
            font-size: 30px;
            font-weight: bold;
            margin-top: 4px;
            line-height: 1.1;
        }
        @media (max-width: 1700px) {
            .grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
        }
        @media (max-width: 1400px) {
            .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        }
        @media (max-width: 1000px) {
            .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 900px) {
            .summary-grid { grid-template-columns: 1fr 1fr; }
        }
        @media (max-width: 700px) {
            .grid { grid-template-columns: 1fr; }
            .datetime { font-size: 16px; }
            .summary-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <div class="topbar-left">
                <h1>Cherry Dene Farm Dashboard</h1>
                <div class="top-links">
                    <a class="top-link" href="{{ url_for('office_events_view') }}">Event Log</a>
                    <a class="top-link" href="{{ url_for('create_office_backup_view') }}">Create Backup</a>
                    <a class="top-link" href="{{ url_for('download_latest_office_backup_view') }}">Download Backup</a>
                </div>
            </div>
            <div id="topDateTime" class="datetime">--</div>
        </div>

        <div class="grid">
            {% for s in sheds %}
            <a class="card-link" href="{{ url_for('shed_detail', shed_no=s.shed_no) }}">
                <div id="shed-card-{{ s.shed_no }}" class="card {% if s.alarm_active %}alarm{% elif s.tile_state == 'online' %}online{% else %}offline{% endif %} {% if not s.has_data %}nodata{% endif %}">
                    <div class="head">
                        <div class="head-left">
                            <div class="shed">{{ s.shed }}</div>
                            <div class="birds-top">Birds: <span id="shed-birds-{{ s.shed_no }}">{{ s.bird_count }}</span> • Age: <span id="shed-age-{{ s.shed_no }}">{{ s.bird_age }}</span> • Crop: <span id="shed-farm-crop-{{ s.shed_no }}">{{ s.farm_crop_id }}</span></div>
                            {% if s.allocation_text %}
                            <div id="shed-alloc-{{ s.shed_no }}" class="alloc-top">{{ s.allocation_text }}</div>
                            {% endif %}
                            {% if not s.allocation_text %}
                            <div id="shed-alloc-{{ s.shed_no }}" class="alloc-top" style="display:none"></div>
                            {% endif %}
                        </div>

                        <div class="badge-wrap">
                            {% if s.alarm_active %}
                                <div class="badge alarm">ALARM</div>
                            {% elif s.has_active_entry and not s.has_data %}
                                <div class="badge active">ACTIVE</div>
                                <div class="badge">NO DATA</div>
                            {% elif s.tile_state == 'online' and s.has_data %}
                                <div class="badge">ONLINE</div>
                            {% elif s.has_active_entry %}
                                <div class="badge active">ACTIVE</div>
                            {% else %}
                                <div class="badge">NO DATA</div>
                            {% endif %}
                        </div>
                    </div>

                    <div class="topline">
                        <div class="mini">
                            <div class="mini-label">Temp</div>
                            <div id="shed-temp-{{ s.shed_no }}" class="mini-val">{{ s.temp_c }}</div>
                        </div>
                        <div class="mini">
                            <div class="mini-label">RH</div>
                            <div id="shed-rh-{{ s.shed_no }}" class="mini-val">{{ s.rh_pct }}</div>
                        </div>
                    </div>

                    <div class="big-pair">
                        <div id="shed-water-tile-{{ s.shed_no }}" class="metric metric-big {% if s.water_glow %}{{ s.water_glow }}{% endif %}">
                            <div class="metric-label">Live Water L/min</div>
                            <div id="shed-water-{{ s.shed_no }}" class="metric-val">{{ s.water_lpm }}</div>
                        </div>
                        <div id="shed-feed-tile-{{ s.shed_no }}" class="metric metric-big {% if s.feed_glow %}{{ s.feed_glow }}{% endif %}">
                            <div class="metric-label">Feed Bin KG</div>
                            <div id="shed-feed-{{ s.shed_no }}" class="metric-val">{{ s.feed_kg }}</div>
                        </div>
                    </div>

                    <div class="section">
                        <div class="metric-grid">
                            <div class="metric">
                                <div class="metric-label">Water L 7am-7am</div>
                                <div id="shed-water7-{{ s.shed_no }}" class="metric-val">{{ s.water_7to7 }}</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">Feed KG 7am-7am</div>
                                <div id="shed-feed7-{{ s.shed_no }}" class="metric-val">{{ s.feed_7to7 }}</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">Estimated Run Out</div>
                                <div class="metric-val">{{ s.runout_est }}</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">L/bird yesterday</div>
                                <div class="metric-val">{{ s.l_per_bird }}</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">KG/bird yesterday</div>
                                <div class="metric-val">{{ s.kg_per_bird }}</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">Avg KG Feed/Bird/Day</div>
                                <div class="metric-val">{{ s.avg_feed_per_bird }}</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">Water Total L</div>
                                <div class="metric-val">{{ s.total_water_to_date }}</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">Feed Total KG</div>
                                <div class="metric-val">{{ s.total_feed_to_date }}</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">Mortality</div>
                                <div id="shed-mortality-{{ s.shed_no }}" class="metric-val">{{ s.mortality_total }}</div>
                            </div>
                        </div>
                    </div>

                    <div class="section">
                        <div class="row"><span class="label">Crop</span>{{ s.crop_id }}</div>
                        <div class="row"><span class="label">Updated</span><span id="shed-updated-{{ s.shed_no }}">{{ s.updated }}</span></div>
                    </div>

                    <div id="shed-alarm-{{ s.shed_no }}" class="alarmbox" {% if not s.alarm_active %}style="display:none"{% endif %}>
                        <div><strong id="shed-alarm-key-{{ s.shed_no }}">{{ s.alarm_key }}</strong></div>
                        <div id="shed-alarm-msg-{{ s.shed_no }}">{{ s.alarm_msg }}</div>
                    </div>
                </div>
            </a>
            {% endfor %}

            <a class="card-link" href="{{ url_for('borehole_detail') }}">
                <div id="borehole-card" class="card {% if borehole.alarm_active %}alarm{% elif borehole.tile_state == 'online' %}online{% else %}offline{% endif %} {% if not borehole.has_data %}nodata{% endif %}">
                    <div class="head">
                        <div class="head-left">
                            <div class="shed">Bore Hole</div>
                        </div>

                        <div class="badge-wrap">
                            {% if borehole.alarm_active %}
                                <div class="badge alarm">ALARM</div>
                            {% elif borehole.has_data and borehole.tile_state == 'online' %}
                                <div class="badge">ONLINE</div>
                            {% else %}
                                <div class="badge">NO DATA</div>
                            {% endif %}
                        </div>
                    </div>

                    <div class="big-one">
                        <div id="borehole-water-tile" class="metric metric-big {% if borehole.water_glow %}{{ borehole.water_glow }}{% endif %}">
                            <div class="metric-label">Live Water L/min</div>
                            <div id="borehole-water" class="metric-val">{{ borehole.water_lpm }}</div>
                        </div>
                    </div>

                    <div class="section">
                        <div class="metric-grid-2">
                            <div class="metric">
                                <div class="metric-label">Water L 7am-7am</div>
                                <div id="borehole-daily" class="metric-val">{{ borehole.daily_water }}</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">Water L 7 Day</div>
                                <div id="borehole-weekly" class="metric-val">{{ borehole.weekly_water }}</div>
                            </div>
                        </div>
                    </div>

                    <div class="section">
                        <div class="row"><span class="label">Last 7 Days</span></div>
                        <div class="bore-list">
                            {% for d in borehole.last_7_days %}
                            <div class="bore-row">
                                <div class="bore-date">{{ d.label }}</div>
                                <div class="bore-val">{{ d.water }} L</div>
                            </div>
                            {% endfor %}
                        </div>
                    </div>

                    <div class="section">
                        <div class="row"><span class="label">Updated</span><span id="borehole-updated">{{ borehole.updated }}</span></div>
                    </div>

                    <div id="borehole-alarm" class="alarmbox" {% if not borehole.alarm_active %}style="display:none"{% endif %}>
                        <div><strong id="borehole-alarm-key">{{ borehole.alarm_key }}</strong></div>
                        <div id="borehole-alarm-msg">{{ borehole.alarm_msg }}</div>
                    </div>
                </div>
            </a>
        </div>

        <div id="overall-tile" class="summary-tile {{ overall.tile_state }}">
            <div class="summary-title">Current Crop Overall</div>
            <div class="summary-grid">
                <div class="summary-box">
                    <div class="summary-label">Farm Crop ID</div>
                    <div id="overall-crop" class="summary-val">{{ overall.farm_crop_id }}</div>
                </div>
                <div class="summary-box">
                    <div class="summary-label">Birds Placed</div>
                    <div id="overall-birds-placed" class="summary-val">{{ overall.birds_placed }}</div>
                </div>
                <div class="summary-box">
                    <div class="summary-label">Birds Remaining</div>
                    <div id="overall-birds-remaining" class="summary-val">{{ overall.birds_remaining }}</div>
                </div>
                <div class="summary-box">
                    <div class="summary-label">Total Water L</div>
                    <div id="overall-water" class="summary-val">{{ overall.water }}</div>
                </div>
                <div class="summary-box">
                    <div class="summary-label">Total Feed KG</div>
                    <div id="overall-feed" class="summary-val">{{ overall.feed }}</div>
                </div>
            </div>
        </div>
    </div>

<script>
function updateTopDateTime() {
    const el = document.getElementById("topDateTime");
    if (!el) return;

    const now = new Date();
    const datePart = now.toLocaleDateString(undefined, {
        weekday: "short",
        day: "2-digit",
        month: "short",
        year: "numeric"
    });
    const timePart = now.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
    });

    el.textContent = datePart + " " + timePart;
}

updateTopDateTime();
setInterval(updateTopDateTime, 1000);

function setDashText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function setDashClass(id, classes, allowed) {
    const el = document.getElementById(id);
    if (!el) return;
    allowed.forEach(name => el.classList.remove(name));
    classes.forEach(name => { if (name) el.classList.add(name); });
}

function renderShed(s) {
    setDashText(`shed-birds-${s.shed_no}`, s.bird_count);
    setDashText(`shed-age-${s.shed_no}`, s.bird_age);
    setDashText(`shed-farm-crop-${s.shed_no}`, s.farm_crop_id);
    setDashText(`shed-temp-${s.shed_no}`, s.temp_c);
    setDashText(`shed-rh-${s.shed_no}`, s.rh_pct);
    setDashText(`shed-water-${s.shed_no}`, s.water_lpm);
    setDashText(`shed-feed-${s.shed_no}`, s.feed_kg);
    setDashText(`shed-water7-${s.shed_no}`, s.water_7to7);
    setDashText(`shed-feed7-${s.shed_no}`, s.feed_7to7);
    setDashText(`shed-mortality-${s.shed_no}`, s.mortality_total);
    setDashText(`shed-updated-${s.shed_no}`, s.updated);
    setDashClass(`shed-card-${s.shed_no}`, [s.alarm_active ? 'alarm' : s.tile_state, s.has_data ? '' : 'nodata'], ['alarm', 'online', 'offline', 'nodata']);
    setDashClass(`shed-water-tile-${s.shed_no}`, [s.water_glow], ['flow-green', 'flow-red']);
    setDashClass(`shed-feed-tile-${s.shed_no}`, [s.feed_glow], ['feed-green', 'feed-red']);

    const alloc = document.getElementById(`shed-alloc-${s.shed_no}`);
    if (alloc) {
        alloc.textContent = s.allocation_text || '';
        alloc.style.display = s.allocation_text ? '' : 'none';
    }

    const alarm = document.getElementById(`shed-alarm-${s.shed_no}`);
    if (alarm) {
        if (s.alarm_active) {
            alarm.style.display = '';
            setDashText(`shed-alarm-key-${s.shed_no}`, s.alarm_key);
            setDashText(`shed-alarm-msg-${s.shed_no}`, s.alarm_msg);
        } else {
            alarm.style.display = 'none';
        }
    }
}

function renderBorehole(b) {
    setDashClass('borehole-card', [b.alarm_active ? 'alarm' : b.tile_state, b.has_data ? '' : 'nodata'], ['alarm', 'online', 'offline', 'nodata']);
    setDashClass('borehole-water-tile', [b.water_glow], ['flow-green', 'flow-red']);
    setDashText('borehole-water', b.water_lpm);
    setDashText('borehole-daily', b.daily_water);
    setDashText('borehole-weekly', b.weekly_water);
    setDashText('borehole-updated', b.updated);
    const alarm = document.getElementById('borehole-alarm');
    if (alarm) {
        if (b.alarm_active) {
            alarm.style.display = '';
            setDashText('borehole-alarm-key', b.alarm_key);
            setDashText('borehole-alarm-msg', b.alarm_msg);
        } else {
            alarm.style.display = 'none';
        }
    }
}

function renderOverall(o) {
    setDashClass('overall-tile', [o.tile_state], ['online', 'offline']);
    setDashText('overall-crop', o.farm_crop_id);
    setDashText('overall-birds-placed', o.birds_placed);
    setDashText('overall-birds-remaining', o.birds_remaining);
    setDashText('overall-water', o.water);
    setDashText('overall-feed', o.feed);
}

async function pollDashboard() {
    try {
        const resp = await fetch('/api/overview', { cache: 'no-store' });
        if (!resp.ok) return;
        const payload = await resp.json();
        (payload.sheds || []).forEach(renderShed);
        if (payload.borehole) renderBorehole(payload.borehole);
        if (payload.overall) renderOverall(payload.overall);
    } catch (err) {
    }
}

setInterval(pollDashboard, 2000);

if (window.EventSource) {
    const waterSource = new EventSource('/api/water-stream');
    waterSource.onmessage = (event) => {
        try {
            const payload = JSON.parse(event.data);
            (payload.sheds || []).forEach((s) => {
                setDashText(`shed-water-${s.shed_no}`, s.water_lpm);
                setDashClass(`shed-water-tile-${s.shed_no}`, [s.water_glow], ['flow-green', 'flow-red']);
            });
            if (payload.borehole) {
                setDashText('borehole-water', payload.borehole.water_lpm);
                setDashClass('borehole-water-tile', [payload.borehole.water_glow], ['flow-green', 'flow-red']);
            }
        } catch (err) {
        }
    };
}
</script>
</body>
</html>
"""


EVENTS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Office Event Log</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { margin:0; font-family:Arial, sans-serif; background:#5b5b5b; color:#ececec; }
        .wrap { max-width:1400px; margin:0 auto; padding:16px; }
        a { color:#f0f0f0; text-decoration:none; }
        .topbar { margin-bottom:16px; }
        .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:16px; }
        h1 { margin:0 0 8px 0; }
        .sub { color:#d2d2d2; margin-bottom:14px; }
        table { width:100%; border-collapse:collapse; font-size:14px; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; vertical-align:top; }
        th { color:#f0f0f0; }
        .mono { font-family:ui-monospace, SFMono-Regular, Menlo, monospace; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('dashboard') }}">← Back to dashboard</a></div>
        <div class="panel">
            <h1>Office Event Log</h1>
            <div class="sub">Recent office, controller, crop, sync, and mortality events.</div>
            <table>
                <thead>
                    <tr><th>Time</th><th>Source</th><th>Type</th><th>Shed</th><th>Message</th><th>Detail</th></tr>
                </thead>
                <tbody>
                    {% for row in rows %}
                    <tr>
                        <td>{{ row.ts_label }}</td>
                        <td>{{ row.source }}</td>
                        <td>{{ row.event_type }}</td>
                        <td>{{ row.shed if row.shed else "--" }}</td>
                        <td>{{ row.message }}</td>
                        <td class="mono">{{ row.detail if row.detail else "--" }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""


DETAIL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} Detail</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
        }
        .wrap {
            max-width: 1500px;
            margin: 0 auto;
            padding: 16px;
        }
        a {
            color: #f0f0f0;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        h1 {
            margin: 0 0 6px 0;
            font-size: 30px;
        }
        .sub {
            color: #d2d2d2;
            margin-bottom: 16px;
            font-size: 14px;
        }
        .topbar {
            margin-bottom: 14px;
        }
        .status {
            margin-bottom: 14px;
            padding: 10px 12px;
            border-radius: 10px;
            background: #737373;
            border: 1px solid #8a8a8a;
        }
        .status.ok {
            border-color: #35d07f;
            color: #dff9ea;
        }
        .status.err {
            border-color: #ff5b5b;
            color: #ffd6d6;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 14px;
            margin-bottom: 16px;
        }
        .navcard {
            display: block;
            background: #737373;
            border: 2px solid #8a8a8a;
            border-radius: 12px;
            padding: 18px;
            color: inherit;
            text-decoration: none;
        }
        .navcard:hover {
            border-color: #a4a4a4;
        }
        .navtitle {
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 8px;
        }
        .navsub {
            font-size: 14px;
            color: #d2d2d2;
        }
        .table-card {
            background: #737373;
            border: 2px solid #8a8a8a;
            border-radius: 12px;
            padding: 14px;
        }
        .table-card h2 {
            margin-top: 0;
            font-size: 22px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 10px 8px;
            text-align: left;
            vertical-align: middle;
        }
        th {
            color: #f0f0f0;
        }
        input[type="number"] {
            width: 110px;
            box-sizing: border-box;
            padding: 8px 10px;
            border-radius: 8px;
            border: 1px solid #8a8a8a;
            background: #686868;
            color: #ececec;
        }
        button {
            background: #727272;
            color: #ececec;
            border: 1px solid #8a8a8a;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
            min-width: 88px;
            text-align: center;
        }
        button:hover {
            background: #7b7b7b;
        }
        .danger {
            border-color: #8e3e3e;
        }
        .move {
            border-color: #6a6a2d;
        }
        .empty {
            color: #d2d2d2;
        }
        .entry-yes {
            color: #8ee7b0;
            font-weight: bold;
        }
        .entry-no {
            color: #ffb0b0;
            font-weight: bold;
        }
        .form-inline {
            display: inline-flex;
            margin-right: 6px;
            margin-bottom: 4px;
            vertical-align: top;
        }
        @media (max-width: 1200px) {
            .grid {
                grid-template-columns: 1fr;
            }
            table {
                font-size: 13px;
            }
            input[type="number"] {
                width: 90px;
            }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <a href="{{ url_for('dashboard') }}">← Back to dashboard</a>
        </div>

        <h1>{{ shed_name }}</h1>
        <div class="sub">Current crop {{ active_crop_id if active_crop_id is not none else "--" }}</div>

        {% if status_msg %}
        <div class="status {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}

        <div class="grid">
            <a class="navcard" href="{{ url_for('shed_period_view', shed_no=shed_no, period='hourly') }}">
                <div class="navtitle">Hourly</div>
                <div class="navsub">Current crop hourly list and zoomable charts.</div>
            </a>

            <a class="navcard" href="{{ url_for('shed_period_view', shed_no=shed_no, period='daily') }}">
                <div class="navtitle">Daily</div>
                <div class="navsub">Current crop completed 7am-7am daily list and zoomable charts.</div>
            </a>

            <a class="navcard" href="{{ url_for('shed_crop_history', shed_no=shed_no) }}">
                <div class="navtitle">Crop history</div>
                <div class="navsub">Open the last 6 crops for this shed.</div>
            </a>

            <a class="navcard" href="{{ url_for('shed_mortality_view', shed_no=shed_no) }}">
                <div class="navtitle">Mortality</div>
                <div class="navsub">Enter losses and deduct them from live bird numbers.</div>
            </a>
        </div>

        <div class="table-card">
            <h2>Shed entries</h2>
            <table>
                <thead>
                    <tr>
                        <th>Entry Shed</th>
                        <th>Birds</th>
                        <th>Pens</th>
                        <th>Started</th>
                        <th>Active</th>
                        <th>Update</th>
                        <th>Controls</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in entry_rows %}
                    <tr>
                        <td>Shed {{ r.dest_shed }}</td>
                        <td>
                            <form class="form-inline" method="post" action="{{ url_for('shed_entry_save', shed_no=shed_no, dest_shed=r.dest_shed) }}">
                                <input type="number" name="bird_count" min="0" step="1" value="{{ r.bird_count }}">
                                <button type="submit">Save</button>
                            </form>
                        </td>
                        <td>{{ r.pens_text if r.pens_text else "--" }}</td>
                        <td>{{ r.placement_str }}</td>
                        <td>
                            {% if r.crop_active == 1 %}
                                <span class="entry-yes">Yes</span>
                            {% else %}
                                <span class="entry-no">No</span>
                            {% endif %}
                        </td>
                        <td>
                            <form class="form-inline" method="post" action="{{ url_for('shed_entry_start', shed_no=shed_no, dest_shed=r.dest_shed) }}">
                                <button type="submit">Start</button>
                            </form>
                            <form class="form-inline" method="post" action="{{ url_for('shed_entry_end', shed_no=shed_no, dest_shed=r.dest_shed) }}">
                                <button class="danger" type="submit">End</button>
                            </form>
                        </td>
                        <td>
                            {% if r.can_move %}
                            <form class="form-inline" method="post" action="{{ url_for('shed_entry_move', shed_no=shed_no, dest_shed=r.dest_shed) }}">
                                <button class="move" type="submit">Move to Shed {{ r.dest_shed }}</button>
                            </form>
                            {% else %}
                            <span class="empty">--</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""


MORTALITY_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} Mortality</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { margin: 0; font-family: Arial, sans-serif; background: #5b5b5b; color: #ececec; }
        .wrap { max-width: 1200px; margin: 0 auto; padding: 16px; }
        a { color: #f0f0f0; text-decoration: none; }
        h1 { margin: 0 0 6px 0; font-size: 30px; }
        .sub { color: #d2d2d2; margin-bottom: 16px; font-size: 14px; }
        .topbar { margin-bottom: 14px; }
        .status { margin-bottom: 14px; padding: 10px 12px; border-radius: 10px; background: #737373; border: 1px solid #8a8a8a; }
        .status.ok { border-color: #35d07f; color: #dff9ea; }
        .status.err { border-color: #ff5b5b; color: #ffd6d6; }
        .grid { display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 14px; }
        .card { background: #737373; border: 2px solid #8a8a8a; border-radius: 12px; padding: 14px; }
        .card h2 { margin-top: 0; font-size: 22px; }
        label { display: block; color: #f0f0f0; margin-bottom: 6px; font-size: 14px; }
        input[type="number"], input[type="text"], select { width: 100%; box-sizing: border-box; padding: 10px 12px; border-radius: 8px; border: 1px solid #8a8a8a; background: #686868; color: #ececec; margin-bottom: 12px; }
        button { background: #727272; color: #f2f2f2; border: 1px solid #8a8a8a; border-radius: 8px; padding: 10px 14px; cursor: pointer; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th, td { border-bottom: 1px solid #818181; padding: 10px 8px; text-align: left; vertical-align: middle; }
        th { color: #f0f0f0; }
        .empty { color: #d2d2d2; }
        @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('shed_detail', shed_no=shed_no) }}">← {{ shed_name }}</a></div>
        <h1>{{ shed_name }} Mortality</h1>
        <div class="sub">Current crop {{ active_crop_id if active_crop_id is not none else "--" }}. Record losses against an active entry shed.</div>
        {% if status_msg %}
        <div class="status {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}
        <div class="grid">
            <div class="card">
                <h2>Add Mortality</h2>
                {% if target_rows %}
                <form method="post" action="{{ url_for('shed_mortality_add', shed_no=shed_no) }}">
                    <label for="dest_shed">Entry Shed</label>
                    <select id="dest_shed" name="dest_shed">
                        {% for row in target_rows %}
                        <option value="{{ row.dest_shed }}">Shed {{ row.dest_shed }} ({{ row.bird_count }} birds)</option>
                        {% endfor %}
                    </select>
                    <label for="bird_loss">Bird Loss</label>
                    <input id="bird_loss" type="number" name="bird_loss" min="1" step="1" value="">
                    <label for="note">Note</label>
                    <input id="note" type="text" name="note" value="">
                    <button type="submit">Record Mortality</button>
                </form>
                {% else %}
                <div class="empty">No active entries available for mortality.</div>
                {% endif %}
            </div>
            <div class="card">
                <h2>This Crop</h2>
                <table>
                    <tbody>
                        <tr><th>Total mortality</th><td>{{ mortality_total }}</td></tr>
                        <tr><th>Active birds</th><td>{{ active_birds }}</td></tr>
                    </tbody>
                </table>
                <h2 style="margin-top:18px;">Mortality Log</h2>
                {% if history_rows %}
                <table>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Entry Shed</th>
                            <th>Loss</th>
                            <th>Note</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for row in history_rows %}
                        <tr>
                            <td>{{ row.ts_label }}</td>
                            <td>Shed {{ row.dest_shed }}</td>
                            <td>{{ row.bird_loss }}</td>
                            <td>{{ row.note if row.note else "--" }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% else %}
                <div class="empty">No mortality logged for this crop yet.</div>
                {% endif %}
            </div>
        </div>
    </div>
</body>
</html>
"""


BOREHOLE_DETAIL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Bore Hole Detail</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="30">
    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
        }
        .wrap {
            max-width: 1200px;
            margin: 0 auto;
            padding: 16px;
        }
        a {
            color: #f0f0f0;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        h1 {
            margin: 0 0 6px 0;
            font-size: 30px;
        }
        .sub {
            color: #d2d2d2;
            margin-bottom: 16px;
            font-size: 14px;
        }
        .topbar {
            margin-bottom: 14px;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
        }
        .navcard {
            display: block;
            background: #737373;
            border: 2px solid #8a8a8a;
            border-radius: 12px;
            padding: 18px;
            color: inherit;
            text-decoration: none;
            transition: transform 0.12s ease, border-color 0.12s ease;
        }
        .navcard:hover {
            transform: translateY(-2px);
            border-color: #a4a4a4;
        }
        .navtitle {
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 8px;
        }
        .navsub {
            font-size: 14px;
            color: #d2d2d2;
        }
        @media (max-width: 800px) {
            .grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <a href="{{ url_for('dashboard') }}">← Back to dashboard</a>
        </div>

        <h1>Bore Hole</h1>
        <div class="sub">Hourly and daily water usage with zoomable charts.</div>

        <div class="grid">
            <a class="navcard" href="{{ url_for('borehole_period_view', period='hourly') }}">
                <div class="navtitle">Hourly</div>
                <div class="navsub">Hourly list and zoomable water chart.</div>
            </a>

            <a class="navcard" href="{{ url_for('borehole_period_view', period='daily') }}">
                <div class="navtitle">Daily</div>
                <div class="navsub">Completed 7am-7am daily list and zoomable water chart.</div>
            </a>
        </div>
    </div>
</body>
</html>
"""


HISTORY_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} Crop History</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
        }
        .wrap {
            max-width: 1200px;
            margin: 0 auto;
            padding: 16px;
        }
        a {
            color: #f0f0f0;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        h1 {
            margin: 0 0 10px 0;
            font-size: 30px;
        }
        .topbar {
            margin-bottom: 14px;
        }
        .sub {
            color: #d2d2d2;
            margin-bottom: 16px;
            font-size: 14px;
        }
        .card {
            background: #737373;
            border: 2px solid #8a8a8a;
            border-radius: 12px;
            padding: 14px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 10px 8px;
            text-align: left;
        }
        th {
            color: #f0f0f0;
        }
        .empty {
            color: #d2d2d2;
            font-size: 14px;
        }
        .actions a {
            margin-right: 12px;
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <a href="{{ url_for('shed_detail', shed_no=shed_no) }}">← {{ shed_name }}</a>
        </div>

        <h1>{{ shed_name }} Crop history</h1>
        <div class="sub">Last 6 crops found in hourly log data.</div>

        <div class="card">
            {% if crops %}
            <table>
                <thead>
                    <tr>
                        <th>Crop ID</th>
                        <th>Start</th>
                        <th>End</th>
                        <th>Open</th>
                    </tr>
                </thead>
                <tbody>
                    {% for c in crops %}
                    <tr>
                        <td>{{ c.crop_id }}</td>
                        <td>{{ c.start_label }}</td>
                        <td>{{ c.end_label }}</td>
                        <td class="actions">
                            <a href="{{ url_for('shed_crop_period_view', shed_no=shed_no, crop_id=c.crop_id, period='hourly') }}">Hourly</a>
                            <a href="{{ url_for('shed_crop_period_view', shed_no=shed_no, crop_id=c.crop_id, period='daily') }}">Daily</a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="empty">No crop history found yet.</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""


PERIOD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} {{ period_title }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="30">
    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
        }
        .wrap {
            max-width: 1850px;
            margin: 0 auto;
            padding: 16px;
        }
        a {
            color: #f0f0f0;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        h1 {
            margin: 0 0 6px 0;
            font-size: 30px;
        }
        .sub {
            color: #d2d2d2;
            margin-bottom: 16px;
            font-size: 14px;
        }
        .topbar {
            margin-bottom: 14px;
        }
        .grid {
            display: grid;
            grid-template-columns: 1.2fr 1fr;
            gap: 14px;
        }
        .stack {
            display: grid;
            grid-template-columns: 1fr;
            gap: 14px;
        }
        .card {
            background: #737373;
            border: 2px solid #8a8a8a;
            border-radius: 12px;
            padding: 14px;
        }
        .card h2 {
            margin-top: 0;
            font-size: 20px;
        }
        .toolbar {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 10px;
        }
        .toolbar button {
            background: #727272;
            color: #ececec;
            border: 1px solid #8a8a8a;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
        }
        .toolbar button:hover {
            background: #808080;
        }
        .chart-wrap {
            background: #686868;
            border: 1px solid #818181;
            border-radius: 10px;
            padding: 10px;
            overflow: hidden;
        }
        .chart-box {
            position: relative;
            height: 420px;
        }
        .table-wrap {
            max-height: 900px;
            overflow: auto;
            border: 1px solid #818181;
            border-radius: 10px;
            background: #686868;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 8px 6px;
            text-align: left;
        }
        th {
            color: #f0f0f0;
            position: sticky;
            top: 0;
            background: #686868;
        }
        td {
            color: #e7edf4;
        }
        .hint {
            color: #d2d2d2;
            font-size: 12px;
            margin-top: 8px;
        }
        .empty {
            color: #d2d2d2;
            font-size: 14px;
            padding: 10px 0;
        }
        @media (max-width: 1200px) {
            .grid { grid-template-columns: 1fr; }
        }
    </style>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <a href="{{ url_for('dashboard') }}">← Dashboard</a>
            &nbsp;|&nbsp;
            <a href="{{ url_for('shed_detail', shed_no=shed_no) }}">← {{ shed_name }}</a>
            {% if history_mode %}
            &nbsp;|&nbsp;
            <a href="{{ url_for('shed_crop_history', shed_no=shed_no) }}">← Crop history</a>
            {% endif %}
        </div>

        <h1>{{ shed_name }} {{ period_title }}</h1>
        <div class="sub">{{ period_sub }}</div>

        <div class="grid">
            <div class="card">
                <h2>{{ period_title }} list</h2>
                {% if rows %}
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>{{ first_col }}</th>
                                <th>Water L</th>
                                <th>Feed KG</th>
                                <th>Running Water L</th>
                                <th>Running Feed KG</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for r in rows %}
                            <tr>
                                <td>{{ r.label }}</td>
                                <td>{{ "%.1f"|format(r.water) if r.water is not none else "--" }}</td>
                                <td>{{ "%.2f"|format(r.feed) if r.feed is not none else "--" }}</td>
                                <td>{{ "%.1f"|format(r.running_water) if r.running_water is not none else "--" }}</td>
                                <td>{{ "%.2f"|format(r.running_feed) if r.running_feed is not none else "--" }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <div class="empty">No data yet.</div>
                {% endif %}
            </div>

            <div class="stack">
                <div class="card">
                    <h2>Feed {{ period_title }} chart</h2>
                    {% if rows %}
                    <div class="toolbar">
                        <button type="button" onclick="resetZoomSafe(feedChart)">Reset zoom</button>
                    </div>
                    <div class="chart-wrap">
                        <div class="chart-box">
                            <canvas id="feedChart"></canvas>
                        </div>
                    </div>
                    <div class="hint">Mouse wheel to zoom, drag to pan, shift + drag to zoom box.</div>
                    {% else %}
                    <div class="empty">No data yet.</div>
                    {% endif %}
                </div>

                <div class="card">
                    <h2>Water {{ period_title }} chart</h2>
                    {% if rows %}
                    <div class="toolbar">
                        <button type="button" onclick="resetZoomSafe(waterChart)">Reset zoom</button>
                    </div>
                    <div class="chart-wrap">
                        <div class="chart-box">
                            <canvas id="waterChart"></canvas>
                        </div>
                    </div>
                    <div class="hint">Mouse wheel to zoom, drag to pan, shift + drag to zoom box.</div>
                    {% else %}
                    <div class="empty">No data yet.</div>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>

<script>
const labels = {{ labels|tojson }};
const feedValues = {{ feed_values|tojson }};
const waterValues = {{ water_values|tojson }};
const xAxisTitle = {{ first_col|tojson }};

let feedChart = null;
let waterChart = null;

function resetZoomSafe(chart) {
    if (chart && chart.resetZoom) {
        chart.resetZoom();
    }
}

function buildChart(canvasId, chartLabel, values, yTitle, lineColor) {
    const el = document.getElementById(canvasId);
    if (!el) return null;

    return new Chart(el, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: chartLabel,
                data: values,
                borderWidth: 2,
                pointRadius: 2,
                pointHoverRadius: 4,
                tension: 0.2,
                borderColor: lineColor,
                backgroundColor: lineColor
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: {
                mode: 'nearest',
                intersect: false
            },
            plugins: {
                legend: {
                    labels: { color: '#f2f2f2' }
                },
                tooltip: { enabled: true },
                zoom: {
                    limits: {
                        x: {minRange: 1},
                        y: {minRange: 1}
                    },
                    pan: {
                        enabled: true,
                        mode: 'xy'
                    },
                    zoom: {
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        drag: {
                            enabled: true,
                            modifierKey: 'shift'
                        },
                        mode: 'xy'
                    }
                }
            },
            scales: {
                x: {
                    ticks: {
                        color: '#f0f0f0',
                        maxRotation: 60,
                        minRotation: 30,
                        autoSkip: true,
                        maxTicksLimit: 18
                    },
                    grid: { color: '#818181' },
                    title: {
                        display: true,
                        text: xAxisTitle,
                        color: '#f2f2f2'
                    }
                },
                y: {
                    ticks: { color: '#f0f0f0' },
                    grid: { color: '#818181' },
                    title: {
                        display: true,
                        text: yTitle,
                        color: '#f2f2f2'
                    }
                }
            }
        }
    });
}

feedChart = buildChart('feedChart', 'Feed KG', feedValues, 'Feed KG', '#35d07f');
waterChart = buildChart('waterChart', 'Water L', waterValues, 'Water L', '#4db6ff');
</script>
</body>
</html>
"""


BOREHOLE_PERIOD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Bore Hole {{ period_title }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="30">
    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
        }
        .wrap {
            max-width: 1650px;
            margin: 0 auto;
            padding: 16px;
        }
        a {
            color: #f0f0f0;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        h1 {
            margin: 0 0 6px 0;
            font-size: 30px;
        }
        .sub {
            color: #d2d2d2;
            margin-bottom: 16px;
            font-size: 14px;
        }
        .topbar {
            margin-bottom: 14px;
        }
        .grid {
            display: grid;
            grid-template-columns: 1.1fr 1fr;
            gap: 14px;
        }
        .card {
            background: #737373;
            border: 2px solid #8a8a8a;
            border-radius: 12px;
            padding: 14px;
        }
        .card h2 {
            margin-top: 0;
            font-size: 20px;
        }
        .toolbar {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 10px;
        }
        .toolbar button {
            background: #727272;
            color: #ececec;
            border: 1px solid #8a8a8a;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
        }
        .toolbar button:hover {
            background: #808080;
        }
        .chart-wrap {
            background: #686868;
            border: 1px solid #818181;
            border-radius: 10px;
            padding: 10px;
            overflow: hidden;
        }
        .chart-box {
            position: relative;
            height: 420px;
        }
        .table-wrap {
            max-height: 900px;
            overflow: auto;
            border: 1px solid #818181;
            border-radius: 10px;
            background: #686868;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 8px 6px;
            text-align: left;
        }
        th {
            color: #f0f0f0;
            position: sticky;
            top: 0;
            background: #686868;
        }
        td {
            color: #e7edf4;
        }
        .hint {
            color: #d2d2d2;
            font-size: 12px;
            margin-top: 8px;
        }
        .empty {
            color: #d2d2d2;
            font-size: 14px;
            padding: 10px 0;
        }
        @media (max-width: 1200px) {
            .grid { grid-template-columns: 1fr; }
        }
    </style>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <a href="{{ url_for('dashboard') }}">← Dashboard</a>
            &nbsp;|&nbsp;
            <a href="{{ url_for('borehole_detail') }}">← Bore Hole</a>
        </div>

        <h1>Bore Hole {{ period_title }}</h1>
        <div class="sub">{{ period_sub }}</div>

        <div class="grid">
            <div class="card">
                <h2>{{ period_title }} list</h2>
                {% if rows %}
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>{{ first_col }}</th>
                                <th>Water L</th>
                                <th>Running Water L</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for r in rows %}
                            <tr>
                                <td>{{ r.label }}</td>
                                <td>{{ "%.1f"|format(r.water) if r.water is not none else "--" }}</td>
                                <td>{{ "%.1f"|format(r.running_water) if r.running_water is not none else "--" }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <div class="empty">No data yet.</div>
                {% endif %}
            </div>

            <div class="card">
                <h2>Water {{ period_title }} chart</h2>
                {% if rows %}
                <div class="toolbar">
                    <button type="button" onclick="resetZoomSafe(waterChart)">Reset zoom</button>
                </div>
                <div class="chart-wrap">
                    <div class="chart-box">
                        <canvas id="waterChart"></canvas>
                    </div>
                </div>
                <div class="hint">Mouse wheel to zoom, drag to pan, shift + drag to zoom box.</div>
                {% else %}
                <div class="empty">No data yet.</div>
                {% endif %}
            </div>
        </div>
    </div>

<script>
const labels = {{ labels|tojson }};
const waterValues = {{ water_values|tojson }};
const xAxisTitle = {{ first_col|tojson }};

let waterChart = null;

function resetZoomSafe(chart) {
    if (chart && chart.resetZoom) {
        chart.resetZoom();
    }
}

function buildChart(canvasId, chartLabel, values, yTitle, lineColor) {
    const el = document.getElementById(canvasId);
    if (!el) return null;

    return new Chart(el, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: chartLabel,
                data: values,
                borderWidth: 2,
                pointRadius: 2,
                pointHoverRadius: 4,
                tension: 0.2,
                borderColor: lineColor,
                backgroundColor: lineColor
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: {
                mode: 'nearest',
                intersect: false
            },
            plugins: {
                legend: {
                    labels: { color: '#f2f2f2' }
                },
                tooltip: { enabled: true },
                zoom: {
                    limits: {
                        x: {minRange: 1},
                        y: {minRange: 1}
                    },
                    pan: {
                        enabled: true,
                        mode: 'xy'
                    },
                    zoom: {
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        drag: {
                            enabled: true,
                            modifierKey: 'shift'
                        },
                        mode: 'xy'
                    }
                }
            },
            scales: {
                x: {
                    ticks: {
                        color: '#f0f0f0',
                        maxRotation: 60,
                        minRotation: 30,
                        autoSkip: true,
                        maxTicksLimit: 18
                    },
                    grid: { color: '#818181' },
                    title: {
                        display: true,
                        text: xAxisTitle,
                        color: '#f2f2f2'
                    }
                },
                y: {
                    ticks: { color: '#f0f0f0' },
                    grid: { color: '#818181' },
                    title: {
                        display: true,
                        text: yTitle,
                        color: '#f2f2f2'
                    }
                }
            }
        }
    });
}

waterChart = buildChart('waterChart', 'Water L', waterValues, 'Water L', '#4db6ff');
</script>
</body>
</html>
"""


@app.route("/")
def dashboard():
    return render_template_string(HTML, **build_dashboard_context())


@app.route("/events")
def office_events_view():
    return render_template_string(EVENTS_HTML, rows=get_recent_events(250))


@app.route("/backup/create")
def create_office_backup_view():
    path = create_office_backup_zip("manual")
    log_event("office", "backup_created", "Office backup created", detail=os.path.basename(path))
    return redirect(url_for("dashboard"))


@app.route("/backup/latest")
def download_latest_office_backup_view():
    backups = list_office_backup_files()
    if not backups:
        path = create_office_backup_zip("manual")
    else:
        path = backups[0]
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.route("/api/overview")
def dashboard_overview_api():
    return jsonify(build_dashboard_context())


@app.route("/api/water-stream")
def dashboard_water_stream_api():
    def event_stream():
        while True:
            payload = build_dashboard_water_context()
            yield "data: %s\n\n" % json.dumps(payload)
            time.sleep(1.0)

    return Response(event_stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/shed/<int:shed_no>")
def shed_detail(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)

    shed_name = shed_name_from_number(shed_no)
    active_crop_id = get_active_crop_id_for_shed(shed_name)
    state = load_shed_entries_state()
    entries = ensure_shed_entry_bucket(state, shed_name)
    entry_rows = build_detail_entry_rows(shed_no, entries)

    status_msg = request.args.get("msg", "")
    status_ok = request.args.get("ok", "1") == "1"

    return render_template_string(
        DETAIL_HTML,
        shed_name=shed_name,
        shed_no=shed_no,
        active_crop_id=active_crop_id,
        entry_rows=entry_rows,
        status_msg=status_msg,
        status_ok=status_ok,
    )


@app.route("/shed/<int:shed_no>/mortality")
def shed_mortality_view(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    payload = mortality_payload_for_shed(shed_no)
    status_msg = request.args.get("msg")
    status_ok = request.args.get("ok", "1") == "1"
    return render_template_string(
        MORTALITY_HTML,
        shed_no=payload["shed_no"],
        shed_name=payload["shed_name"],
        active_crop_id=payload["active_crop_id"],
        target_rows=payload["target_rows"],
        history_rows=payload["history_rows"],
        mortality_total=fmt_value(payload["mortality_total"], "i"),
        active_birds=fmt_value(payload["active_birds"], "i"),
        status_msg=status_msg,
        status_ok=status_ok,
    )


@app.route("/shed/<int:shed_no>/mortality/add", methods=["POST"])
def shed_mortality_add(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)

    try:
        dest_shed = int(request.form.get("dest_shed"))
        bird_loss = int(request.form.get("bird_loss"))
        if dest_shed not in SHED_NUMBERS or bird_loss <= 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("shed_mortality_view", shed_no=shed_no, ok=0, msg="Invalid mortality entry"))

    note = str(request.form.get("note", "") or "").strip()
    ok, msg = apply_mortality_to_shed(shed_no, dest_shed, bird_loss, note=note, updated_by="dashboard")
    return redirect(url_for("shed_mortality_view", shed_no=shed_no, ok=1 if ok else 0, msg=msg))


@app.route("/api/shed/<int:shed_no>/mortality", methods=["GET"])
def shed_mortality_api_get(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    return jsonify(mortality_payload_for_shed(shed_no))


@app.route("/api/shed/<int:shed_no>/mortality", methods=["POST"])
def shed_mortality_api_post(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)

    payload = request.get_json(silent=True) or {}
    try:
        dest_shed = int(payload.get("dest_shed"))
        bird_loss = int(payload.get("bird_loss"))
    except Exception:
        return jsonify({"ok": False, "message": "Invalid mortality entry"}), 400

    note = str(payload.get("note", "") or "").strip()
    ok, msg = apply_mortality_to_shed(shed_no, dest_shed, bird_loss, note=note, updated_by="controller")
    if not ok:
        return jsonify({"ok": False, "message": msg}), 400
    return jsonify({
        "ok": True,
        "message": msg,
        "summary": shed_sync_payload(shed_no).get("summary", {}),
    })


@app.route("/shed/<int:shed_no>/entry/<int:dest_shed>/save", methods=["POST"])
def shed_entry_save(shed_no, dest_shed):
    if shed_no not in SHED_NUMBERS or dest_shed not in SHED_NUMBERS:
        abort(404)

    raw = request.form.get("bird_count", "").strip()
    try:
        bird_count = int(raw)
        if bird_count < 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Invalid bird count"))

    state = load_shed_entries_state()
    shed_name = shed_name_from_number(shed_no)
    entries = ensure_shed_entry_bucket(state, shed_name)

    rec = entries.get(str(dest_shed), {
        "bird_count": 0,
        "crop_active": 0,
        "placement_epoch": None,
        "crop_id": None,
        "updated_ts": None,
        "updated_by": "dashboard",
    })
    rec = clean_entry_record(rec)
    now_ts = int(time.time())

    if bird_count == 0:
        had_active_crop = int(rec.get("crop_active", 0) or 0) == 1 and rec.get("crop_id") is not None
        rec["bird_count"] = 0
        rec["crop_active"] = 0
        rec["placement_epoch"] = None
        rec["crop_id"] = None
    else:
        rec["bird_count"] = bird_count

    rec["updated_ts"] = now_ts
    rec["updated_by"] = "dashboard"

    entries[str(dest_shed)] = rec
    save_shed_entries_state(state)
    if bird_count == 0:
        refresh_farm_crop_current_id(state)
        if had_active_crop:
            log_crop_event(shed_name, rec, False)
        log_event("office", "entry_cleared", "Entry saved as zero birds", shed_no=shed_no, detail="Entry Shed %d" % dest_shed)
    else:
        log_event("office", "entry_saved", "Bird count saved", shed_no=shed_no, detail="Entry Shed %d = %d" % (dest_shed, bird_count))
    push_shed_state_to_controller(shed_no)
    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg="Entry saved"))


@app.route("/shed/<int:shed_no>/entry/<int:dest_shed>/start", methods=["POST"])
def shed_entry_start(shed_no, dest_shed):
    if shed_no not in SHED_NUMBERS or dest_shed not in SHED_NUMBERS:
        abort(404)

    state = load_shed_entries_state()
    shed_name = shed_name_from_number(shed_no)
    entries = ensure_shed_entry_bucket(state, shed_name)

    rec = entries.get(str(dest_shed), {
        "bird_count": 0,
        "crop_active": 0,
        "placement_epoch": None,
        "crop_id": None,
        "updated_ts": None,
        "updated_by": "dashboard",
    })
    rec = clean_entry_record(rec)

    try:
        bird_count = int(rec.get("bird_count", 0) or 0)
    except Exception:
        bird_count = 0

    if bird_count <= 0:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Set birds before starting"))

    rec["crop_active"] = 1
    if rec.get("placement_epoch") is None:
        rec["placement_epoch"] = int(time.time())
    if rec.get("crop_id") in [None, ""]:
        rec["crop_id"] = crop_id_for_new_start(state)
    rec["updated_ts"] = int(time.time())
    rec["updated_by"] = "dashboard"

    entries[str(dest_shed)] = rec
    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)
    log_crop_event(shed_name, rec, True)
    log_event("office", "entry_started", "Entry started", shed_no=shed_no, detail="Entry Shed %d Crop %s" % (dest_shed, rec.get("crop_id")))
    push_shed_state_to_controller(shed_no)
    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg="Entry started"))


@app.route("/shed/<int:shed_no>/entry/<int:dest_shed>/end", methods=["POST"])
def shed_entry_end(shed_no, dest_shed):
    if shed_no not in SHED_NUMBERS or dest_shed not in SHED_NUMBERS:
        abort(404)

    state = load_shed_entries_state()
    shed_name = shed_name_from_number(shed_no)
    entries = ensure_shed_entry_bucket(state, shed_name)

    rec = entries.get(str(dest_shed))
    if not rec:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Entry not found"))

    rec = clean_entry_record(rec)
    rec["updated_ts"] = int(time.time())
    rec["updated_by"] = "dashboard"
    log_crop_event(shed_name, rec, False)
    del entries[str(dest_shed)]
    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)
    log_event("office", "entry_ended", "Entry ended", shed_no=shed_no, detail="Entry Shed %d" % dest_shed)
    push_shed_state_to_controller(shed_no)

    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg="Entry ended and shed cleared"))


@app.route("/shed/<int:shed_no>/entry/<int:dest_shed>/move", methods=["POST"])
def shed_entry_move(shed_no, dest_shed):
    if shed_no not in SHED_NUMBERS or dest_shed not in SHED_NUMBERS:
        abort(404)

    if shed_no == dest_shed:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Cannot move to same shed"))

    state = load_shed_entries_state()

    from_name = shed_name_from_number(shed_no)
    to_name = shed_name_from_number(dest_shed)

    from_entries = ensure_shed_entry_bucket(state, from_name)
    to_entries = ensure_shed_entry_bucket(state, to_name)

    rec = from_entries.get(str(dest_shed))
    if not rec:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Entry not found"))

    try:
        bird_count = int(rec.get("bird_count", 0) or 0)
    except Exception:
        bird_count = 0

    try:
        crop_active = int(rec.get("crop_active", 0) or 0)
    except Exception:
        crop_active = 0

    if bird_count <= 0 or crop_active != 1:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Only active entries with birds can move"))

    dest_rec = to_entries.get(str(dest_shed), {
        "bird_count": 0,
        "crop_active": 0,
        "placement_epoch": None,
        "crop_id": None,
        "updated_ts": None,
        "updated_by": "dashboard",
    })
    rec = clean_entry_record(rec)
    dest_rec = clean_entry_record(dest_rec)

    try:
        existing = int(dest_rec.get("bird_count", 0) or 0)
    except Exception:
        existing = 0

    dest_rec["bird_count"] = existing + bird_count
    dest_rec["crop_active"] = 1
    if dest_rec.get("placement_epoch") is None:
        dest_rec["placement_epoch"] = rec.get("placement_epoch") or int(time.time())
    if dest_rec.get("crop_id") in [None, ""]:
        dest_rec["crop_id"] = rec.get("crop_id")
    move_ts = int(time.time())
    dest_rec["updated_ts"] = move_ts
    dest_rec["updated_by"] = "dashboard"
    rec["updated_ts"] = move_ts
    rec["updated_by"] = "dashboard"

    to_entries[str(dest_shed)] = dest_rec
    log_crop_event(from_name, rec, False)
    log_crop_event(to_name, dest_rec, True)
    del from_entries[str(dest_shed)]

    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)
    log_event("office", "entry_moved", "Entry moved between sheds", shed_no=shed_no, detail="Entry Shed %d moved to Shed %d" % (dest_shed, dest_shed))
    push_shed_state_to_controller(shed_no)
    push_shed_state_to_controller(dest_shed)
    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg="Entry moved to Shed %d" % dest_shed))


@app.route("/api/shed/<int:shed_no>/sync", methods=["GET"])
def shed_sync_get(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    return jsonify(shed_sync_payload(shed_no))


@app.route("/api/shed/<int:shed_no>/sync", methods=["POST"])
def shed_sync_post(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)

    payload = request.get_json(silent=True) or {}
    incoming_entries = payload.get("entries", {})
    incoming_controller_meta = payload.get("controller_meta")
    changed = apply_external_shed_entries(shed_no, incoming_entries, source="controller")
    if isinstance(incoming_controller_meta, dict):
        save_controller_meta_for_shed(shed_no, incoming_controller_meta)
        log_event("controller", "controller_meta", "Controller telemetry updated", shed_no=shed_no)

    return jsonify({
        "ok": True,
        "changed": bool(changed),
        "shed_no": shed_no,
        "current_crop_id": get_active_crop_id_for_shed(shed_name_from_number(shed_no)),
    })


@app.route("/api/event", methods=["POST"])
def office_event_api():
    payload = request.get_json(silent=True) or {}
    try:
        shed_no = int(payload.get("shed_no")) if payload.get("shed_no") not in [None, ""] else None
    except Exception:
        shed_no = None
    log_event(
        payload.get("source", "controller"),
        payload.get("event_type", "event"),
        payload.get("message", ""),
        shed_no=shed_no,
        detail=payload.get("detail", ""),
    )
    return jsonify({"ok": True})


@app.route("/api/shed/<int:shed_no>/current-crop/hourly", methods=["GET"])
def shed_current_crop_hourly_api(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)

    shed_name = shed_name_from_number(shed_no)
    active_crop_id = get_active_crop_id_for_shed(shed_name)
    rows = get_hourly_history_for_shed(shed_name, max_points=168, crop_id=active_crop_id)

    return jsonify({
        "shed_no": shed_no,
        "shed": shed_name,
        "crop_id": active_crop_id,
        "rows": rows,
    })


@app.route("/borehole")
def borehole_detail():
    return render_template_string(BOREHOLE_DETAIL_HTML)


@app.route("/borehole/<period>")
def borehole_period_view(period):
    if period not in ["hourly", "daily"]:
        abort(404)

    if period == "hourly":
        rows = get_borehole_hourly_history(max_points=168)
        rows = add_running_water_totals(rows)
        period_title = "Hourly"
        period_sub = "Bore Hole hourly list with running totals and zoomable water chart."
        first_col = "Hour"
    else:
        rows = get_borehole_daily_history(max_days=40)
        rows = add_running_water_totals(rows)
        period_title = "Daily"
        period_sub = "Bore Hole completed 7am-7am daily list with running totals and zoomable water chart."
        first_col = "Day"

    labels = []
    water_values = []

    i = 0
    while i < len(rows):
        labels.append(rows[i]["label"])
        water_values.append(rows[i]["water"])
        i += 1

    return render_template_string(
        BOREHOLE_PERIOD_HTML,
        period=period,
        period_title=period_title,
        period_sub=period_sub,
        first_col=first_col,
        rows=rows,
        labels=labels,
        water_values=water_values,
    )


@app.route("/shed/<int:shed_no>/history")
def shed_crop_history(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)

    shed_name = shed_name_from_number(shed_no)
    crops = get_recent_crops_for_shed(shed_name, max_crops=6)

    return render_template_string(
        HISTORY_HTML,
        shed_name=shed_name,
        shed_no=shed_no,
        crops=crops,
    )


@app.route("/shed/<int:shed_no>/<period>")
def shed_period_view(shed_no, period):
    if shed_no not in SHED_NUMBERS:
        abort(404)

    if period not in ["hourly", "daily"]:
        abort(404)

    shed_name = shed_name_from_number(shed_no)
    active_crop_id = get_active_crop_id_for_shed(shed_name)

    if period == "hourly":
        rows = get_hourly_history_for_shed(shed_name, max_points=168, crop_id=active_crop_id)
        rows = add_running_totals(rows)
        period_title = "Hourly"
        period_sub = "Current crop %s hourly list with running totals and separate zoomable feed and water charts." % (
            str(active_crop_id) if active_crop_id is not None else "--"
        )
        first_col = "Hour"
    else:
        rows = get_daily_history_for_shed(shed_name, max_days=40, crop_id=active_crop_id)
        rows = add_running_totals(rows)
        period_title = "Daily"
        period_sub = "Current crop %s completed 7am-7am daily list with running totals and separate zoomable feed and water charts." % (
            str(active_crop_id) if active_crop_id is not None else "--"
        )
        first_col = "Day"

    labels = []
    feed_values = []
    water_values = []

    i = 0
    while i < len(rows):
        labels.append(rows[i]["label"])
        feed_values.append(rows[i]["feed"])
        water_values.append(rows[i]["water"])
        i += 1

    return render_template_string(
        PERIOD_HTML,
        shed_name=shed_name,
        shed_no=shed_no,
        history_mode=False,
        period=period,
        period_title=period_title,
        period_sub=period_sub,
        first_col=first_col,
        rows=rows,
        labels=labels,
        feed_values=feed_values,
        water_values=water_values,
    )


@app.route("/shed/<int:shed_no>/crop/<int:crop_id>/<period>")
def shed_crop_period_view(shed_no, crop_id, period):
    if shed_no not in SHED_NUMBERS:
        abort(404)

    if period not in ["hourly", "daily"]:
        abort(404)

    shed_name = shed_name_from_number(shed_no)

    if period == "hourly":
        rows = get_hourly_history_for_shed(shed_name, max_points=0, crop_id=crop_id)
        rows = add_running_totals(rows)
        period_title = "Crop %d Hourly" % crop_id
        period_sub = "Historic crop %d hourly list with running totals and separate zoomable feed and water charts." % crop_id
        first_col = "Hour"
    else:
        rows = get_daily_history_for_shed(shed_name, max_days=0, crop_id=crop_id)
        rows = add_running_totals(rows)
        period_title = "Crop %d Daily" % crop_id
        period_sub = "Historic crop %d completed 7am-7am daily list with running totals and separate zoomable feed and water charts." % crop_id
        first_col = "Day"

    labels = []
    feed_values = []
    water_values = []

    i = 0
    while i < len(rows):
        labels.append(rows[i]["label"])
        feed_values.append(rows[i]["feed"])
        water_values.append(rows[i]["water"])
        i += 1

    return render_template_string(
        PERIOD_HTML,
        shed_name=shed_name,
        shed_no=shed_no,
        history_mode=True,
        period=period,
        period_title=period_title,
        period_sub=period_sub,
        first_col=first_col,
        rows=rows,
        labels=labels,
        feed_values=feed_values,
        water_values=water_values,
    )


if __name__ == "__main__":
    ensure_data_dir()
    app.run(host="0.0.0.0", port=8090)
