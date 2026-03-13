from flask import Flask, render_template_string, abort, url_for, request, redirect, jsonify, Response, send_file
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta

app = Flask(__name__)

CDF_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="12" fill="#4f4f4f"/>
<rect x="4" y="4" width="56" height="56" rx="10" fill="none" stroke="#35d07f" stroke-width="2.5"/>
<text x="32" y="39" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="23" font-weight="700" fill="#f1f1f1">CDF</text>
</svg>"""


@app.route("/favicon.ico")
@app.route("/favicon.svg")
def favicon_view():
    return Response(CDF_FAVICON_SVG, mimetype="image/svg+xml")


@app.after_request
def inject_favicon(response):
    try:
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if "text/html" in content_type and response.direct_passthrough is False:
            body = response.get_data(as_text=True)
            if "<head>" in body and 'rel="icon"' not in body:
                body = body.replace('<head>', '<head><link rel="icon" type="image/svg+xml" href="/favicon.svg">', 1)
                response.set_data(body)
                response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception:
        pass
    return response

DATA_DIR = "data"
SHED_NUMBERS = [1, 2, 3, 4, 6, 7, 8, 9, 10]
OFFICE_BACKUP_KEEP_COUNT = 6
OFFICE_AUTO_BACKUP_INTERVAL_SECONDS = 3600
OFFICE_AUTO_BACKUP_CHECK_SECONDS = 60
_office_backup_lock = threading.Lock()


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(backups_dir(), exist_ok=True)


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
    cfg = read_json_file(os.path.join(DATA_DIR, "office_config.json"), {})
    if isinstance(cfg, dict):
        backup_dir = str(cfg.get("backup_dir", "") or "").strip()
        if backup_dir:
            if os.path.isabs(backup_dir):
                return backup_dir
            return os.path.join(office_repo_dir(), backup_dir)
    return os.path.join(DATA_DIR, "backups")


def load_office_config():
    data = read_json_file(os.path.join(DATA_DIR, "office_config.json"), {})
    return data if isinstance(data, dict) else {}


def controller_backup_root():
    path = os.path.join(DATA_DIR, "controller_backups")
    os.makedirs(path, exist_ok=True)
    return path


def controller_backup_status_path():
    return os.path.join(DATA_DIR, "controller_backup_status.json")


def load_controller_backup_status():
    data = read_json_file(controller_backup_status_path(), {})
    return data if isinstance(data, dict) else {}


def save_controller_backup_status(data):
    write_json_file_atomic(controller_backup_status_path(), data if isinstance(data, dict) else {})


def controller_backup_dir(controller_key):
    path = os.path.join(controller_backup_root(), controller_key)
    os.makedirs(path, exist_ok=True)
    return path


def list_controller_backup_files(controller_key):
    base = controller_backup_dir(controller_key)
    rows = []
    try:
        for name in os.listdir(base):
            path = os.path.join(base, name)
            if os.path.isfile(path) and name.endswith(".zip"):
                rows.append(path)
    except Exception:
        return []
    rows.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return rows


def prune_controller_backup_files(controller_key, keep=6):
    rows = list_controller_backup_files(controller_key)
    i = keep
    while i < len(rows):
        try:
            os.remove(rows[i])
        except Exception:
            pass
        i += 1


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
    with _office_backup_lock:
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


def latest_office_backup_mtime():
    backups = list_office_backup_files()
    if not backups:
        return None
    try:
        return int(os.path.getmtime(backups[0]))
    except Exception:
        return None


def ensure_recent_auto_backup():
    last_mtime = latest_office_backup_mtime()
    now_ts = int(time.time())
    if last_mtime is not None and (now_ts - last_mtime) < OFFICE_AUTO_BACKUP_INTERVAL_SECONDS:
        return None
    path = create_office_backup_zip("auto")
    log_event("office", "backup_created", "Automatic office backup created", detail=os.path.basename(path))
    return path


def office_backup_worker():
    while True:
        try:
            ensure_recent_auto_backup()
        except Exception as exc:
            log_event("office", "backup_failed", "Automatic office backup failed", detail=str(exc))
        time.sleep(OFFICE_AUTO_BACKUP_CHECK_SECONDS)


def controller_backup_url_map():
    urls = {}
    controllers = load_controller_config()
    if isinstance(controllers, dict):
        for key, rec in controllers.items():
            if not isinstance(rec, dict):
                continue
            sync_url = str(rec.get("sync_url", "") or "").strip().rstrip("/")
            if sync_url:
                if str(key).isdigit():
                    controller_key = "shed_%s" % key
                    label = "Shed %s" % key
                else:
                    controller_key = str(key).strip().lower().replace(" ", "_")
                    label = str(rec.get("label", "") or str(key).replace("_", " ").title()).strip()
                urls[controller_key] = {
                    "label": label,
                    "url": sync_url + "/backup/latest",
                    "token": str(rec.get("sync_token", "") or ""),
                }
    return urls


def collect_controller_backup(controller_key, label, url, token=""):
    status_map = load_controller_backup_status()
    now_ts = int(time.time())
    try:
        headers = {}
        if token:
            headers["X-Controller-Token"] = token
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if not (200 <= int(resp.status) < 300):
                raise RuntimeError("HTTP %d" % int(resp.status))
            content = resp.read()
        stamp = datetime.fromtimestamp(now_ts).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(controller_backup_dir(controller_key), "%s_%s.zip" % (controller_key, stamp))
        with open(path, "wb") as f:
            f.write(content)
        prune_controller_backup_files(controller_key, keep=6)
        status_map[controller_key] = {
            "label": label,
            "last_collected_ts": now_ts,
            "last_status": "Office copy OK: %s" % os.path.basename(path),
        }
        save_controller_backup_status(status_map)
        return True
    except Exception as exc:
        status_map[controller_key] = {
            "label": label,
            "last_collected_ts": now_ts,
            "last_status": "Office copy failed: %s" % exc,
        }
        save_controller_backup_status(status_map)
        return False


def maybe_collect_controller_backups():
    status_map = load_controller_backup_status()
    urls = controller_backup_url_map()
    for controller_key, rec in urls.items():
        last_ts = None
        try:
            last_ts = int(status_map.get(controller_key, {}).get("last_collected_ts"))
        except Exception:
            last_ts = None
        if last_ts is not None and (int(time.time()) - last_ts) < OFFICE_AUTO_BACKUP_INTERVAL_SECONDS:
            continue
        collect_controller_backup(controller_key, rec.get("label", controller_key), rec.get("url", ""), str(rec.get("token", "") or ""))


def controller_backup_worker():
    while True:
        try:
            maybe_collect_controller_backups()
        except Exception as exc:
            log_event("office", "controller_backup_failed", "Automatic controller backup collection failed", detail=str(exc))
        time.sleep(OFFICE_AUTO_BACKUP_CHECK_SECONDS)


def start_office_background_workers():
    th = threading.Thread(target=office_backup_worker, daemon=True)
    th.start()
    th2 = threading.Thread(target=controller_backup_worker, daemon=True)
    th2.start()


def backup_path_by_name(name):
    if not name:
        return None
    path = os.path.join(backups_dir(), os.path.basename(name))
    if os.path.isfile(path) and path.endswith(".zip"):
        return path
    return None


def office_update_status_path():
    ensure_data_dir()
    return os.path.join(DATA_DIR, "office_update_status.json")


def load_office_update_status():
    default = {
        "checked_at": None,
        "status": "Not checked",
        "branch": "main",
        "local_commit": "--",
        "remote_commit": "--",
        "update_available": False,
    }
    data = read_json_file(office_update_status_path(), default)
    merged = dict(default)
    if isinstance(data, dict):
        merged.update(data)
    return merged


def save_office_update_status(payload):
    status = load_office_update_status()
    status.update(payload)
    write_json_file_atomic(office_update_status_path(), status)


def office_repo_dir():
    return os.path.dirname(os.path.abspath(__file__))


def run_office_git_command(args, timeout=20):
    try:
        proc = subprocess.run(
            ["git", "-C", office_repo_dir()] + list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except Exception as exc:
        return 1, "", str(exc)


def get_office_git_status():
    code, branch_out, branch_err = run_office_git_command(["branch", "--show-current"])
    if code != 0:
        return {"ok": False, "error": branch_err or branch_out or "Git branch lookup failed"}

    code, local_out, local_err = run_office_git_command(["rev-parse", "HEAD"])
    if code != 0:
        return {"ok": False, "error": local_err or local_out or "Git commit lookup failed"}

    return {
        "ok": True,
        "branch": branch_out or "main",
        "local_commit": local_out[:7] if local_out else "--",
    }


def check_office_update():
    local = get_office_git_status()
    status = {
        "checked_at": int(time.time()),
        "branch": local.get("branch", "main"),
        "local_commit": local.get("local_commit", "--"),
        "remote_commit": "--",
        "update_available": False,
        "status": "Up to date" if local.get("ok") else (local.get("error") or "Git status failed"),
    }
    if not local.get("ok"):
        save_office_update_status(status)
        return status

    code, _, fetch_err = run_office_git_command(["fetch", "origin", local["branch"]], timeout=30)
    if code != 0:
        status["status"] = fetch_err or "Fetch failed"
        save_office_update_status(status)
        return status

    code, remote_out, remote_err = run_office_git_command(["rev-parse", "origin/%s" % local["branch"]])
    if code != 0:
        status["status"] = remote_err or remote_out or "Remote commit lookup failed"
        save_office_update_status(status)
        return status

    status["remote_commit"] = remote_out[:7] if remote_out else "--"
    status["update_available"] = remote_out != local["local_commit"]
    status["status"] = "Update available" if status["update_available"] else "Up to date"
    save_office_update_status(status)
    return status


def restart_office_delayed(delay_seconds=1.0):
    def _restart():
        time.sleep(delay_seconds)
        os._exit(0)

    th = threading.Thread(target=_restart, daemon=True)
    th.start()


def zip_json_member(path, member_name, default):
    try:
        with zipfile.ZipFile(path, "r") as zf:
            with zf.open(member_name) as f:
                return json.load(f)
    except Exception:
        return default


def zip_ndjson_member(path, member_name):
    try:
        rows = []
        with zipfile.ZipFile(path, "r") as zf:
            with zf.open(member_name) as f:
                for raw in f:
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass
        return rows
    except Exception:
        return []


def restore_full_office_from_backup(path):
    with zipfile.ZipFile(path, "r") as zf:
        for name in zf.namelist():
            if "/" in name or name.endswith("/"):
                continue
            target = os.path.join(DATA_DIR, name)
            with zf.open(name) as src, open(target, "wb") as dst:
                dst.write(src.read())


def restore_shed_from_backup(path, shed_no):
    shed_name = shed_name_from_number(shed_no)

    backup_entries = zip_json_member(path, "shed_entries.json", {})
    if isinstance(backup_entries, dict):
        current_entries = load_shed_entries_state()
        if shed_name in backup_entries:
            current_entries[shed_name] = backup_entries[shed_name]
            save_shed_entries_state(current_entries)

    backup_meta = zip_json_member(path, "controller_meta.json", {})
    if isinstance(backup_meta, dict):
        current_meta = load_controller_meta()
        key = str(int(shed_no))
        if key in backup_meta:
            current_meta[key] = backup_meta[key]
            save_controller_meta(current_meta)

    backup_live = zip_json_member(path, "live_latest.json", {})
    if isinstance(backup_live, dict):
        current_live = latest_live_by_shed()
        if shed_name in backup_live:
            current_live[shed_name] = backup_live[shed_name]
            write_json_file_atomic(os.path.join(DATA_DIR, "live_latest.json"), current_live)


def restore_borehole_from_backup(path):
    backup_live = zip_json_member(path, "borehole_live_latest.json", {})
    if isinstance(backup_live, dict):
        save_borehole_live(backup_live)

    backup_meta = zip_json_member(path, "borehole_meta.json", {})
    if isinstance(backup_meta, dict):
        save_borehole_meta(backup_meta)


def restore_shed_from_controller_backup(path, shed_no):
    shed_name = shed_name_from_number(shed_no)
    controller_state = zip_json_member(path, "controller_state.json", {})
    if not isinstance(controller_state, dict):
        raise RuntimeError("Controller backup missing controller_state.json")

    incoming_entries = controller_state.get("entries", {})
    if not isinstance(incoming_entries, dict):
        incoming_entries = {}

    state = load_shed_entries_state()
    bucket = ensure_shed_entry_bucket(state, shed_name)
    bucket.clear()
    for key, rec in incoming_entries.items():
        try:
            dest_shed = int(key)
        except Exception:
            continue
        bucket[str(dest_shed)] = clean_entry_record(rec)
    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)


def restore_borehole_from_controller_backup(path):
    live_rows = zip_ndjson_member(path, "live.ndjson")
    hourly_rows = zip_ndjson_member(path, "hourly.ndjson")
    controller_state = zip_json_member(path, "controller_state.json", {})

    latest_live = {}
    if live_rows:
        latest_live = live_rows[-1]
    elif isinstance(controller_state, dict):
        sensors = controller_state.get("sensors", {})
        if isinstance(sensors, dict):
            latest_live = {
                "water_lpm": sensors.get("water_lpm"),
                "ts": sensors.get("last_sensor_ts"),
                "source": "borehole_controller_backup",
            }
    if latest_live:
        save_borehole_live(latest_live)

    hourly_path = os.path.join(DATA_DIR, "borehole_hourly.ndjson")
    with open(hourly_path, "w") as f:
        for row in hourly_rows:
            f.write(json.dumps(row) + "\n")

    if isinstance(controller_state, dict):
        meta = load_borehole_meta()
        meta["last_backup_ts"] = controller_state.get("last_backup_ts")
        meta["last_backup_status"] = controller_state.get("last_backup_status")
        meta["received_ts"] = int(time.time())
        save_borehole_meta(meta)


def latest_live_by_shed():
    data = read_json_file(os.path.join(DATA_DIR, "live_latest.json"), {})
    return data if isinstance(data, dict) else {}


def latest_borehole_live():
    data = read_json_file(os.path.join(DATA_DIR, "borehole_live_latest.json"), {})
    return data if isinstance(data, dict) else {}


def save_borehole_live(data):
    path = os.path.join(DATA_DIR, "borehole_live_latest.json")
    write_json_file_atomic(path, data if isinstance(data, dict) else {})


def load_borehole_meta():
    data = read_json_file(os.path.join(DATA_DIR, "borehole_meta.json"), {})
    return data if isinstance(data, dict) else {}


def save_borehole_meta(data):
    path = os.path.join(DATA_DIR, "borehole_meta.json")
    write_json_file_atomic(path, data if isinstance(data, dict) else {})


def clean_borehole_meta(meta):
    if not isinstance(meta, dict):
        meta = {}
    return {
        "last_sensor_ts": meta.get("last_sensor_ts"),
        "device_status": meta.get("device_status"),
        "pico_connected": bool(meta.get("pico_connected", False)),
        "received_ts": int(time.time()),
        "controller_sync_version": meta.get("controller_sync_version"),
        "controller_state_updated_ts": meta.get("controller_state_updated_ts"),
        "last_backup_ts": meta.get("last_backup_ts"),
        "last_backup_status": meta.get("last_backup_status"),
        "app_branch": meta.get("app_branch"),
        "app_version": meta.get("app_version"),
        "pico_local_hash": meta.get("pico_local_hash"),
        "pico_deployed_hash": meta.get("pico_deployed_hash"),
        "controller_alarms": meta.get("controller_alarms", []) if isinstance(meta.get("controller_alarms", []), list) else [],
    }


def load_farm_crop():
    data = read_json_file(os.path.join(DATA_DIR, "farm_crop.json"), {})
    return data if isinstance(data, dict) else {}


def load_controller_config():
    data = read_json_file(os.path.join(DATA_DIR, "controllers.json"), {})
    return data if isinstance(data, dict) else {}


def controller_config_record(controller_key):
    config = load_controller_config()
    rec = config.get(str(controller_key))
    return rec if isinstance(rec, dict) else {}


def controller_token_for_key(controller_key):
    rec = controller_config_record(controller_key)
    return str(rec.get("sync_token", "") or "").strip()


def require_controller_token(controller_key):
    expected = controller_token_for_key(controller_key)
    if not expected:
        return None
    provided = str(request.headers.get("X-Controller-Token", "") or "").strip()
    if provided != expected:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    return None


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
        "last_backup_ts": meta.get("last_backup_ts"),
        "last_backup_status": meta.get("last_backup_status"),
        "app_branch": meta.get("app_branch"),
        "app_version": meta.get("app_version"),
        "pico_local_hash": meta.get("pico_local_hash"),
        "pico_deployed_hash": meta.get("pico_deployed_hash"),
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


def crop_start_epoch_for_state(state, crop_id):
    if crop_id in [None, ""]:
        return None
    earliest = None
    for shed_name in state:
        entries = ensure_shed_entry_bucket(state, shed_name)
        for key in entries:
            rec = entries.get(key, {})
            try:
                rec_crop_id = int(rec.get("crop_id"))
            except Exception:
                continue
            if rec_crop_id != int(crop_id):
                continue
            placement_epoch = rec.get("placement_epoch")
            try:
                placement_epoch = int(placement_epoch)
            except Exception:
                continue
            if earliest is None or placement_epoch < earliest:
                earliest = placement_epoch
    return earliest


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
                "crop_code": fmt_crop_code(rec.get("crop_id"), rec.get("placement_epoch")),
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
        "active_crop_code": fmt_crop_code(active_crop_id, crop_start_epoch_for_state(state, active_crop_id)),
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


def controller_token_for_shed(shed_no):
    config = load_controller_config()
    keys = [str(shed_no), shed_name_from_number(shed_no)]

    for key in keys:
        rec = config.get(key)
        if isinstance(rec, dict):
            token = rec.get("sync_token")
            if token:
                return str(token).strip()
    return ""


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
            "mortality_total": mortality_total_for_shed_crop(shed_name, active_crop_id) if active_crop_id is not None else None,
        },
        "generated_ts": int(time.time()),
    }


def push_shed_state_to_controller(shed_no):
    base_url = controller_url_for_shed(shed_no)
    if not base_url:
        return False, "No controller sync URL configured"

    payload = shed_sync_payload(shed_no)
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = controller_token_for_shed(shed_no)
    if token:
        headers["X-Controller-Token"] = token
    req = urllib.request.Request(
        base_url + "/api/dashboard-sync",
        data=body,
        headers=headers,
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


def fmt_crop_code(crop_id, epoch=None):
    try:
        crop_no = int(crop_id)
        if crop_no <= 0:
            return "--"
        if epoch not in [None, ""]:
            date_part = datetime.fromtimestamp(int(epoch)).strftime("%Y%m%d")
            return "CDF-%s-%04d" % (date_part, crop_no)
        return "CDF-%04d" % crop_no
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
            "crop_code": fmt_crop_code(rec["crop_id"], rec["first_epoch"]),
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


def borehole_hour_exists(hour_epoch):
    rows = read_all_json_lines("borehole_hourly.ndjson")
    i = 0
    while i < len(rows):
        try:
            if int(rows[i].get("hour_epoch")) == int(hour_epoch):
                return True
        except Exception:
            pass
        i += 1
    return False


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
            "crop_code": fmt_crop_code(rec.get("crop_id"), placement_epoch),
            "pens_text": ", ".join(pens_parts),
            "can_move": can_move,
        })
        i += 1
    return rows


def build_borehole_row():
    live = latest_borehole_live()
    meta = load_borehole_meta()
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

    received_ts = meta.get("received_ts")
    try:
        sync_age = int(time.time()) - int(received_ts) if received_ts not in [None, ""] else None
    except Exception:
        sync_age = None
    if sync_age is None:
        sync_pill_class = "sync-missing"
        sync_pill_text = "SHED SYNC --"
    elif sync_age <= 30:
        sync_pill_class = "sync-ok"
        sync_pill_text = "SHED SYNC OK • %ss" % sync_age
    else:
        sync_pill_class = "sync-stale"
        sync_pill_text = "SHED SYNC STALE • %ss" % sync_age

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
        "sync_pill_class": sync_pill_class,
        "sync_pill_text": sync_pill_text,
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
    current_crop_epoch = crop_start_epoch_for_state(state, current_crop_id)

    total_birds_remaining = 0
    total_birds_placed = 0
    total_water = 0.0
    total_feed = 0.0
    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        shed_name = shed_name_from_number(shed_no)

        live = effective_live_for_shed(live_map, controller_meta_map, shed_no)
        entries = ensure_shed_entry_bucket(state, shed_name)
        active_entries = active_entries_for_tile(entries)

        birds_remaining = total_birds_from_active_entries(active_entries)
        total_birds_remaining += birds_remaining
        total_birds_placed += birds_remaining
        if current_crop_id not in [None, ""]:
            total_birds_placed += mortality_total_for_shed_crop(shed_name, current_crop_id)

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

    tile_state = "online" if current_crop_id not in [None, ""] else "offline"

    return {
        "tile_state": tile_state,
        "birds_placed": fmt_value(total_birds_placed if total_birds_placed > 0 else None, "i"),
        "birds_remaining": fmt_value(total_birds_remaining if total_birds_remaining > 0 else None, "i"),
        "water": fmt_value(total_water if total_water > 0 else None, "f0"),
        "feed": fmt_value(total_feed if total_feed > 0 else None, "f1"),
        "farm_crop_id": fmt_crop_code(farm_crop.get("current_crop_id"), current_crop_epoch),
    }


def build_rows():
    ensure_data_dir()

    live_map = latest_live_by_shed()
    alarms_map = active_alarms_by_shed()
    controller_meta_map = load_controller_meta()
    state = load_shed_entries_state()
    farm_crop = load_farm_crop()
    current_farm_crop_id = farm_crop.get("current_crop_id")
    current_farm_crop_epoch = crop_start_epoch_for_state(state, current_farm_crop_id)

    rows = []
    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        shed = shed_name_from_number(shed_no)
        live = effective_live_for_shed(live_map, controller_meta_map, shed_no)
        controller_meta = controller_meta_map.get(str(int(shed_no)), {})
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
        received_ts = controller_meta.get("received_ts")
        try:
            sync_age = int(time.time()) - int(received_ts) if received_ts not in [None, ""] else None
        except Exception:
            sync_age = None
        if sync_age is None:
            sync_pill_class = "sync-missing"
            sync_pill_text = "SHED SYNC --"
        elif sync_age <= 30:
            sync_pill_class = "sync-ok"
            sync_pill_text = "SHED SYNC OK • %ss" % sync_age
        else:
            sync_pill_class = "sync-stale"
            sync_pill_text = "SHED SYNC STALE • %ss" % sync_age

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
            "crop_id": fmt_crop_code(crop_id, placement_epoch),
            "farm_crop_id": fmt_crop_code(current_farm_crop_id, current_farm_crop_epoch),
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
            "mortality_total": fmt_value(mortality_total_for_shed_crop(shed, active_crop_id) if active_crop_id is not None else None, "i"),
            "sync_pill_class": sync_pill_class,
            "sync_pill_text": sync_pill_text,
        })
        i += 1

    return rows


def build_dashboard_context():
    overall = build_overall_summary()
    return {
        "sheds": build_rows(),
        "borehole": build_borehole_row(),
        "overall": overall,
        "header_class": "active" if str(overall.get("farm_crop_id", "--")) != "--" else "inactive",
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
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            align-items: center;
            margin-bottom: 12px;
            gap: 12px;
        }
        .topbar-left {
            display: flex;
            align-items: center;
            justify-self: start;
        }
        .topbar-center { justify-self: center; }
        .topbar-right { justify-self: end; }
        .settings-link {
            color: #ededed;
            text-decoration: none;
            font-size: 13px;
            padding: 7px 10px;
            border: 1px solid #7c7c7c;
            border-radius: 10px;
            background: #6a6a6a;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        h1 {
            margin: 0;
            font-size: 28px;
            color: #f0f0f0;
        }
        h1.active {
            text-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        h1.inactive {
            text-shadow:
                0 0 10px rgba(255,119,119,0.95),
                0 0 20px rgba(255,119,119,0.65),
                0 0 34px rgba(255,119,119,0.35);
        }
        .datetime {
            font-size: 18px;
            font-weight: bold;
            color: #efefef;
            white-space: nowrap;
        }
        .datetime.active {
            text-shadow:
                0 0 10px rgba(53,208,127,0.9),
                0 0 18px rgba(53,208,127,0.55),
                0 0 28px rgba(53,208,127,0.28);
        }
        .datetime.inactive {
            text-shadow:
                0 0 10px rgba(255,119,119,0.90),
                0 0 18px rgba(255,119,119,0.55),
                0 0 28px rgba(255,119,119,0.28);
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
            border-color: #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
        }
        .card.flow-green {
            border-color: #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .card.flow-red {
            border-color: #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
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
        .badge.online {
            border-color: #35d07f;
            color: #b8ffd2;
            box-shadow:
                0 0 8px rgba(53,208,127,0.75),
                0 0 16px rgba(53,208,127,0.35);
        }
        .badge.nodata {
            border-color: #d55;
            color: #ffb1b1;
            box-shadow:
                0 0 8px rgba(255,91,91,0.75),
                0 0 16px rgba(255,91,91,0.35);
        }
        .badge.alarm {
            border-color: #d55;
            color: #ff8a8a;
            box-shadow:
                0 0 8px rgba(255,91,91,0.75),
                0 0 16px rgba(255,91,91,0.35);
        }
        .badge.active {
            border-color: #35d07f;
            color: #b8ffd2;
            box-shadow:
                0 0 8px rgba(53,208,127,0.75),
                0 0 16px rgba(53,208,127,0.35);
        }
        .badge.sync-ok {
            border-color: #35d07f;
            color: #b8ffd2;
            box-shadow:
                0 0 8px rgba(53,208,127,0.75),
                0 0 16px rgba(53,208,127,0.35);
        }
        .badge.sync-stale {
            border-color: #ffd06a;
            color: #ffe5a0;
        }
        .badge.sync-missing {
            border-color: #d55;
            color: #ffb1b1;
            box-shadow:
                0 0 8px rgba(255,91,91,0.75),
                0 0 16px rgba(255,91,91,0.35);
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
            border-color: #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.45),
                0 0 34px rgba(255,91,91,0.22);
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
            .topbar { grid-template-columns: 1fr; }
            .topbar-left, .topbar-center, .topbar-right { justify-self: center; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <div class="topbar-left">
                <h1 id="headerTitle" class="{{ header_class }}">Cherry Dene Farm Dashboard</h1>
            </div>
            <div class="topbar-center">
                <a class="settings-link" href="{{ url_for('office_settings_view') }}">⚙ Settings</a>
            </div>
            <div class="topbar-right">
                <div id="topDateTime" class="datetime {{ header_class }}">--</div>
            </div>
        </div>

        <div class="grid">
            {% for s in sheds %}
            <a class="card-link" href="{{ url_for('shed_detail', shed_no=s.shed_no) }}">
                <div id="shed-card-{{ s.shed_no }}" class="card {% if s.alarm_active %}alarm{% elif s.tile_state == 'online' %}online{% else %}offline{% endif %} {% if not s.has_data %}nodata{% endif %}">
                    <div class="head">
                        <div class="head-left">
                            <div class="shed">{{ s.shed }}</div>
                            <div class="birds-top">Birds: <span id="shed-birds-{{ s.shed_no }}">{{ s.bird_count }}</span> • Age: <span id="shed-age-{{ s.shed_no }}">{{ s.bird_age }}</span></div>
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
                                <div class="badge nodata">NO DATA</div>
                            {% elif s.tile_state == 'online' and s.has_data %}
                                <div class="badge online">ONLINE</div>
                            {% elif s.has_active_entry %}
                                <div class="badge active">ACTIVE</div>
                            {% else %}
                                <div class="badge nodata">NO DATA</div>
                            {% endif %}
                            <div id="shed-sync-badge-{{ s.shed_no }}" class="badge {{ s.sync_pill_class }}">{{ s.sync_pill_text }}</div>
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
                <div id="borehole-card" class="card {% if borehole.alarm_active %}alarm{% else %}{{ borehole.water_glow }}{% endif %} {% if not borehole.has_data %}nodata{% endif %}">
                    <div class="head">
                        <div class="head-left">
                            <div class="shed">Bore Hole</div>
                        </div>

                        <div class="badge-wrap">
                            {% if borehole.alarm_active %}
                                <div class="badge alarm">ALARM</div>
                            {% elif borehole.has_data and borehole.tile_state == 'online' %}
                                <div class="badge online">ONLINE</div>
                            {% else %}
                                <div class="badge nodata">NO DATA</div>
                            {% endif %}
                            <div id="borehole-sync-badge" class="badge {{ borehole.sync_pill_class }}">{{ borehole.sync_pill_text }}</div>
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

function setHeaderClass(active) {
    const cls = active ? 'active' : 'inactive';
    ['headerTitle', 'topDateTime'].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.remove('active', 'inactive');
        el.classList.add(cls);
    });
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
    setDashText(`shed-sync-badge-${s.shed_no}`, s.sync_pill_text);
    setDashClass(`shed-sync-badge-${s.shed_no}`, ['badge', s.sync_pill_class], ['sync-ok', 'sync-stale', 'sync-missing']);

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
    setDashClass('borehole-card', [b.alarm_active ? 'alarm' : b.water_glow, b.has_data ? '' : 'nodata'], ['alarm', 'online', 'offline', 'flow-green', 'flow-red', 'nodata']);
    setDashClass('borehole-water-tile', [b.water_glow], ['flow-green', 'flow-red']);
    setDashText('borehole-water', b.water_lpm);
    setDashText('borehole-daily', b.daily_water);
    setDashText('borehole-weekly', b.weekly_water);
    setDashText('borehole-updated', b.updated);
    setDashText('borehole-sync-badge', b.sync_pill_text);
    setDashClass('borehole-sync-badge', ['badge', b.sync_pill_class], ['sync-ok', 'sync-stale', 'sync-missing']);
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
    setHeaderClass(o.farm_crop_id && o.farm_crop_id !== '--');
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


RESTORE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Office Backup Restore</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { margin:0; font-family:Arial, sans-serif; background:#5b5b5b; color:#ececec; }
        .wrap { max-width:1400px; margin:0 auto; padding:16px; }
        a { color:#f0f0f0; text-decoration:none; }
        .topbar { margin-bottom:16px; }
        .status { margin-bottom:14px; padding:10px 12px; border-radius:10px; background:#737373; border:1px solid #8a8a8a; }
        .status.ok { border-color:#35d07f; color:#e4ffed; }
        .status.err { border-color:#c65460; color:#ffdbe1; }
        .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
        .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:16px; }
        h1 { margin:0 0 8px 0; }
        h2 { margin:0 0 10px 0; }
        .sub { color:#d2d2d2; margin-bottom:14px; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #818181; }
        .detail:last-child { border-bottom:0; }
        .label { color:#d2d2d2; }
        select { width:100%; box-sizing:border-box; padding:10px 12px; border-radius:8px; border:1px solid #8a8a8a; background:#686868; color:#ececec; margin-bottom:12px; }
        button { background:#727272; color:#ececec; border:1px solid #8a8a8a; border-radius:8px; padding:10px 14px; cursor:pointer; width:100%; }
        button.danger { border-color:#8e3e3e; }
        table { width:100%; border-collapse:collapse; font-size:14px; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; }
        th { color:#f0f0f0; }
        @media (max-width: 900px) { .grid { grid-template-columns:1fr; } }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('dashboard') }}">← Back to dashboard</a></div>
        <h1>Backup Restore</h1>
        <div class="sub">Restore the full office data set, office backup state, or latest collected controller copies.</div>
        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}
        <div class="grid">
            <div class="panel">
                <h2>Full Office Restore</h2>
                <div class="sub">Restores the full contents of the selected backup into the office data folder.</div>
                <form method="post" action="{{ url_for('restore_office_backup_apply_view') }}" onsubmit="return confirm('Restore the full office backup? This will overwrite current office data.');">
                    <select name="backup_name">
                        {% for b in backups %}
                        <option value="{{ b.name }}">{{ b.name }} ({{ b.mtime }})</option>
                        {% endfor %}
                    </select>
                    <button class="danger" type="submit">Restore Full Backup</button>
                </form>
            </div>
            <div class="panel">
                <h2>Shed Restore</h2>
                <div class="sub">Restores just one shed's live state from the selected backup.</div>
                <form method="post" action="{{ url_for('restore_office_backup_shed_view') }}" onsubmit="return confirm('Restore this shed from the selected office backup?');">
                    <select name="backup_name">
                        {% for b in backups %}
                        <option value="{{ b.name }}">{{ b.name }} ({{ b.mtime }})</option>
                        {% endfor %}
                    </select>
                    <select name="shed_no">
                        {% for shed_no in shed_numbers %}
                        <option value="{{ shed_no }}">Shed {{ shed_no }}</option>
                        {% endfor %}
                    </select>
                    <button type="submit">Restore Shed State</button>
                </form>
            </div>
            <div class="panel">
                <h2>Bore Hole Restore</h2>
                <div class="sub">Restores the bore hole live/meta state from the selected backup.</div>
                <form method="post" action="{{ url_for('restore_office_backup_borehole_view') }}" onsubmit="return confirm('Restore the bore hole state from the selected office backup?');">
                    <select name="backup_name">
                        {% for b in backups %}
                        <option value="{{ b.name }}">{{ b.name }} ({{ b.mtime }})</option>
                        {% endfor %}
                    </select>
                    <button type="submit">Restore Bore Hole State</button>
                </form>
            </div>
        </div>
        <div class="panel" style="margin-top:16px;">
            <h2>Restore From Collected Controller Copies</h2>
            <div class="sub">Use the latest backup ZIP collected from each controller by the office.</div>
            <table>
                <thead><tr><th>Controller</th><th>Latest Office Copy</th><th>Action</th></tr></thead>
                <tbody>
                    {% for row in controller_copy_rows %}
                    <tr>
                        <td>{{ row.label }}</td>
                        <td>{{ row.latest_name }}</td>
                        <td>
                            {% if row.restore_kind == 'shed' %}
                            <form method="post" action="{{ url_for('restore_controller_copy_shed_view') }}" onsubmit="return confirm('Restore this shed from the latest office-collected controller copy?');">
                                <input type="hidden" name="controller_key" value="{{ row.controller_key }}">
                                <input type="hidden" name="shed_no" value="{{ row.shed_no }}">
                                <button type="submit">Restore {{ row.label }}</button>
                            </form>
                            {% elif row.restore_kind == 'borehole' %}
                            <form method="post" action="{{ url_for('restore_controller_copy_borehole_view') }}" onsubmit="return confirm('Restore the bore hole from the latest office-collected controller copy?');">
                                <input type="hidden" name="controller_key" value="{{ row.controller_key }}">
                                <button type="submit">Restore Bore Hole</button>
                            </form>
                            {% else %}
                            --
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        <div class="panel" style="margin-top:16px;">
            <h2>Available Backups</h2>
            <table>
                <thead><tr><th>Name</th><th>Modified</th></tr></thead>
                <tbody>
                    {% for b in backups %}
                    <tr><td>{{ b.name }}</td><td>{{ b.mtime }}</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
<script>
setTimeout(() => {
    document.querySelectorAll('.auto-dismiss').forEach((el) => {
        el.style.display = 'none';
    });
}, 10000);
</script>
</body>
</html>
"""


OFFICE_SETTINGS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Office Settings</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { margin:0; font-family:Arial, sans-serif; background:#5b5b5b; color:#ececec; }
        .wrap { max-width:1400px; margin:0 auto; padding:16px; }
        a { color:#f0f0f0; text-decoration:none; }
        .topbar { margin-bottom:16px; }
        h1 { margin:0 0 8px 0; }
        .sub { color:#d2d2d2; margin-bottom:14px; }
        .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
        .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:16px; }
        .health-grid { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:12px; margin-top:12px; }
        .health-card { background:#686868; border:1px solid #8a8a8a; border-radius:12px; padding:12px; }
        .health-label { color:#d2d2d2; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; }
        .health-value { margin-top:6px; font-size:24px; font-weight:700; }
        .health-note { margin-top:6px; color:#dcdcdc; font-size:12px; line-height:1.35; }
        .action-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
        .action-link, button {
            display:inline-flex;
            align-items:center;
            justify-content:center;
            width:100%;
            box-sizing:border-box;
            min-height:46px;
            padding:10px 14px;
            border-radius:10px;
            border:1px solid #8a8a8a;
            background:#686868;
            color:#ececec;
            text-decoration:none;
            font-size:14px;
            cursor:pointer;
        }
        .action-link.wide, button.wide { grid-column:1 / -1; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #818181; }
        .detail:last-child { border-bottom:0; }
        .label { color:#d2d2d2; }
        .status { margin:0 0 14px 0; padding:10px 12px; border-radius:10px; background:#686868; border:1px solid #8a8a8a; }
        .status.ok { border-color:#35d07f; color:#e4ffed; }
        .status.err { border-color:#c65460; color:#ffdbe1; }
        .mono { font-family:ui-monospace, SFMono-Regular, Menlo, monospace; }
        .update-actions { display:grid; grid-template-columns:1fr; gap:10px; margin-top:14px; }
        table { width:100%; border-collapse:collapse; font-size:14px; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; vertical-align:top; }
        th { color:#f0f0f0; }
        @media (max-width: 900px) { .grid, .action-grid, .health-grid { grid-template-columns:1fr; } }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('dashboard') }}">← Back to dashboard</a></div>
        <h1>Office Settings</h1>
        <div class="sub">Backups, restore, event log, and software update for the office dashboard.</div>
        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}
        <div class="panel" style="margin-bottom:16px;">
            <h2>Farm Health</h2>
            <div class="sub">Current controller freshness, backup status, and Pico link summary across the farm.</div>
            <div class="health-grid">
                <div class="health-card">
                    <div class="health-label">Stale Controllers</div>
                    <div class="health-value">{{ farm_health.stale_count }}</div>
                    <div class="health-note">{{ farm_health.stale_labels }}</div>
                </div>
                <div class="health-card">
                    <div class="health-label">Pico Offline</div>
                    <div class="health-value">{{ farm_health.pico_offline_count }}</div>
                    <div class="health-note">{{ farm_health.pico_offline_labels }}</div>
                </div>
                <div class="health-card">
                    <div class="health-label">Backup Issues</div>
                    <div class="health-value">{{ farm_health.backup_issue_count }}</div>
                    <div class="health-note">{{ farm_health.backup_issue_labels }}</div>
                </div>
                <div class="health-card">
                    <div class="health-label">Last Backup Collect</div>
                    <div class="health-value">{{ farm_health.last_collect_age }}</div>
                    <div class="health-note">{{ farm_health.last_collect_note }}</div>
                </div>
            </div>
        </div>
        <div class="grid">
            <div class="panel">
                <h2>Actions</h2>
                <div class="sub">Open office tools and backup actions.</div>
                <div class="detail"><span class="label">Backup Path</span><span class="mono">{{ backup_dir }}</span></div>
                <div class="detail"><span class="label">Auto Backup</span><span>Hourly, keep newest {{ backup_keep_count }}</span></div>
                <div class="detail"><span class="label">Latest Backup</span><span>{{ latest_backup_name }}</span></div>
                <div class="action-grid">
                    <a class="action-link" href="{{ url_for('office_events_view') }}">Event Log</a>
                    <a class="action-link" href="{{ url_for('office_versions_view') }}">Versions</a>
                    <a class="action-link" href="{{ url_for('restore_office_backup_view') }}">Restore Backup</a>
                    <a class="action-link" href="{{ url_for('create_office_backup_view') }}">Create Backup</a>
                    <a class="action-link" href="{{ url_for('download_latest_office_backup_view') }}">Download Backup</a>
                    <a class="action-link" href="{{ url_for('collect_controller_backups_now_view') }}">Collect Controller Backups</a>
                </div>
            </div>
            <div class="panel">
                <h2>Software Update</h2>
                <div class="sub">Check GitHub for a newer office dashboard version, then apply it when ready.</div>
                <div class="detail"><span class="label">Branch</span><span class="mono">{{ update_status.branch }}</span></div>
                <div class="detail"><span class="label">Current Commit</span><span class="mono">{{ update_status.local_commit }}</span></div>
                <div class="detail"><span class="label">Latest Commit</span><span class="mono">{{ update_status.remote_commit }}</span></div>
                <div class="detail"><span class="label">Last Checked</span><span>{{ update_checked_at }}</span></div>
                <div class="detail"><span class="label">Status</span><span>{{ update_status.status }}</span></div>
                <div class="update-actions">
                    <form method="post" action="{{ url_for('office_check_update_view') }}">
                        <button class="wide" type="submit">Check for Update</button>
                    </form>
                    {% if update_status.update_available %}
                    <form method="post" action="{{ url_for('office_apply_update_view') }}">
                        <button class="wide" type="submit">Update Now</button>
                    </form>
                    {% endif %}
                </div>
            </div>
        </div>
        <div class="panel" style="margin-top:16px;">
            <h2>Shed Controller Backups</h2>
            <div class="sub">Latest controller-reported backup status plus the office-side collected ZIP copy.</div>
            <table>
                <thead><tr><th>Controller</th><th>Controller Backup</th><th>Controller Status</th><th>Office Copy</th><th>Office Copy Status</th></tr></thead>
                <tbody>
                    {% for row in controller_backup_rows %}
                    <tr>
                        <td>{{ row.label }}</td>
                        <td>{{ row.last_backup }}</td>
                        <td>{{ row.last_backup_status }}</td>
                        <td>{{ row.office_copy_at }}</td>
                        <td>{{ row.office_copy_status }}{% if row.office_copy_name != '--' %} · <a href="{{ url_for('download_collected_controller_backup_view', controller_key=row.controller_key) }}">Download</a>{% endif %}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
<script>
setTimeout(() => {
    document.querySelectorAll('.auto-dismiss').forEach((el) => {
        el.style.display = 'none';
    });
}, 10000);
</script>
</body>
</html>
"""


VERSIONS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Versions</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { margin:0; font-family:Arial,sans-serif; background:#5b5b5b; color:#ececec; }
        .wrap { max-width:1180px; margin:0 auto; padding:24px; }
        .topbar a { color:#ececec; text-decoration:none; }
        .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:16px; margin-top:16px; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #818181; }
        .detail:last-child { border-bottom:0; }
        .label { color:#d2d2d2; }
        .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
        .sub { color:#d2d2d2; margin-bottom:14px; }
        table { width:100%; border-collapse:collapse; font-size:14px; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('office_settings_view') }}">← Back to settings</a></div>
        <h1>Versions</h1>
        <div class="sub">Office, shed controller, bore hole controller, and Pico version visibility.</div>
        <div class="panel">
            <h2>Office Dashboard</h2>
            <div class="detail"><span class="label">Branch</span><span class="mono">{{ office.branch }}</span></div>
            <div class="detail"><span class="label">Current Commit</span><span class="mono">{{ office.local_commit }}</span></div>
            <div class="detail"><span class="label">Latest Commit</span><span class="mono">{{ office.remote_commit }}</span></div>
            <div class="detail"><span class="label">Status</span><span>{{ office.status }}</span></div>
            <div class="detail"><span class="label">Last Checked</span><span>{{ office.checked_at }}</span></div>
        </div>
        <div class="panel">
            <h2>Controllers</h2>
            <table>
                <thead><tr><th>Controller</th><th>App Version</th><th>Pico Local</th><th>Pico Deployed</th><th>Last Seen</th><th>State Ver</th><th>Office Sync Ver</th></tr></thead>
                <tbody>
                    {% for row in controller_rows %}
                    <tr>
                        <td>{{ row.label }}</td>
                        <td class="mono">{{ row.app_version }}</td>
                        <td class="mono">{{ row.pico_local }}</td>
                        <td class="mono">{{ row.pico_deployed }}</td>
                        <td>{{ row.last_seen }}</td>
                        <td>{{ row.state_version }}</td>
                        <td>{{ row.office_sync_version }}</td>
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
        <div class="sub">Current crop {{ active_crop_code }}</div>

        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
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
<script>
setTimeout(() => {
    document.querySelectorAll('.auto-dismiss').forEach((el) => {
        el.style.display = 'none';
    });
}, 10000);
</script>
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
        <div class="sub">Current crop {{ active_crop_code }}. Record losses against an active entry shed.</div>
        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
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
<script>
setTimeout(() => {
    document.querySelectorAll('.auto-dismiss').forEach((el) => {
        el.style.display = 'none';
    });
}, 10000);
</script>
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
                        <td>{{ c.crop_code }}</td>
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


@app.route("/settings")
def office_settings_view():
    update_status = load_office_update_status()
    checked_at = update_status.get("checked_at")
    latest_backups = list_office_backup_files()
    controller_meta = load_controller_meta()
    collector_status = load_controller_backup_status()
    controller_backup_rows = []
    stale_labels = []
    pico_offline_labels = []
    backup_issue_labels = []
    collect_ages = []
    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        meta = controller_meta.get(str(int(shed_no)), {}) if isinstance(controller_meta, dict) else {}
        office_copy = collector_status.get("shed_%d" % shed_no, {}) if isinstance(collector_status, dict) else {}
        try:
            received_ts = int(meta.get("received_ts")) if meta.get("received_ts") not in [None, ""] else None
        except Exception:
            received_ts = None
        if received_ts is None or (int(time.time()) - received_ts) > 30:
            stale_labels.append("Shed %s" % shed_no)
        if not bool(meta.get("pico_connected", False)):
            pico_offline_labels.append("Shed %s" % shed_no)
        backup_status = str(meta.get("last_backup_status", "") or "--")
        if backup_status == "--" or "fail" in backup_status.lower():
            backup_issue_labels.append("Shed %s" % shed_no)
        try:
            collected_ts = int(office_copy.get("last_collected_ts")) if office_copy.get("last_collected_ts") not in [None, ""] else None
        except Exception:
            collected_ts = None
        if collected_ts is not None:
            collect_ages.append(max(0, int(time.time()) - collected_ts))
        controller_backup_rows.append({
            "label": "Shed %s" % shed_no,
            "controller_key": "shed_%d" % shed_no,
            "last_backup": datetime.fromtimestamp(int(meta.get("last_backup_ts"))).strftime("%d %b %Y %H:%M:%S") if meta.get("last_backup_ts") not in [None, ""] else "--",
            "last_backup_status": str(meta.get("last_backup_status", "") or "--"),
            "office_copy_at": datetime.fromtimestamp(int(office_copy.get("last_collected_ts"))).strftime("%d %b %Y %H:%M:%S") if office_copy.get("last_collected_ts") not in [None, ""] else "--",
            "office_copy_status": str(office_copy.get("last_status", "") or "--"),
            "office_copy_name": os.path.basename(list_controller_backup_files("shed_%d" % shed_no)[0]) if list_controller_backup_files("shed_%d" % shed_no) else "--",
        })
        i += 1
    borehole_meta = load_borehole_meta()
    borehole_copy = collector_status.get("borehole", {}) if isinstance(collector_status, dict) else {}
    try:
        borehole_received_ts = int(borehole_meta.get("received_ts")) if borehole_meta.get("received_ts") not in [None, ""] else None
    except Exception:
        borehole_received_ts = None
    if borehole_received_ts is None or (int(time.time()) - borehole_received_ts) > 30:
        stale_labels.append("Bore Hole")
    if not bool(borehole_meta.get("pico_connected", False)):
        pico_offline_labels.append("Bore Hole")
    borehole_backup_status = str(borehole_meta.get("last_backup_status", "") or "--")
    if borehole_backup_status == "--" or "fail" in borehole_backup_status.lower():
        backup_issue_labels.append("Bore Hole")
    try:
        borehole_collected_ts = int(borehole_copy.get("last_collected_ts")) if borehole_copy.get("last_collected_ts") not in [None, ""] else None
    except Exception:
        borehole_collected_ts = None
    if borehole_collected_ts is not None:
        collect_ages.append(max(0, int(time.time()) - borehole_collected_ts))
    controller_backup_rows.append({
        "label": "Bore Hole",
        "controller_key": "borehole",
        "last_backup": datetime.fromtimestamp(int(borehole_meta.get("last_backup_ts"))).strftime("%d %b %Y %H:%M:%S") if borehole_meta.get("last_backup_ts") not in [None, ""] else "--",
        "last_backup_status": str(borehole_meta.get("last_backup_status", "") or "--"),
        "office_copy_at": datetime.fromtimestamp(int(borehole_copy.get("last_collected_ts"))).strftime("%d %b %Y %H:%M:%S") if borehole_copy.get("last_collected_ts") not in [None, ""] else "--",
        "office_copy_status": str(borehole_copy.get("last_status", "") or "--"),
        "office_copy_name": os.path.basename(list_controller_backup_files("borehole")[0]) if list_controller_backup_files("borehole") else "--",
    })
    return render_template_string(
        OFFICE_SETTINGS_HTML,
        update_status=update_status,
        update_checked_at=datetime.fromtimestamp(int(checked_at)).strftime("%d %b %Y %H:%M:%S") if checked_at else "--",
        backup_dir=backups_dir(),
        backup_keep_count=OFFICE_BACKUP_KEEP_COUNT,
        latest_backup_name=os.path.basename(latest_backups[0]) if latest_backups else "--",
        farm_health={
            "stale_count": len(stale_labels),
            "stale_labels": ", ".join(stale_labels) if stale_labels else "All controller heartbeats are current",
            "pico_offline_count": len(pico_offline_labels),
            "pico_offline_labels": ", ".join(pico_offline_labels) if pico_offline_labels else "All controller Pico links currently report connected",
            "backup_issue_count": len(backup_issue_labels),
            "backup_issue_labels": ", ".join(backup_issue_labels) if backup_issue_labels else "No current controller backup issues reported",
            "last_collect_age": ("%ss ago" % min(collect_ages)) if collect_ages else "--",
            "last_collect_note": ("Newest office-collected controller copy" if collect_ages else "No controller copies collected yet"),
        },
        controller_backup_rows=controller_backup_rows,
        status_msg=request.args.get("msg", ""),
        status_ok=request.args.get("ok", "1") == "1",
    )


@app.route("/settings/update/check", methods=["POST"])
def office_check_update_view():
    check_office_update()
    return redirect(url_for("office_settings_view"))


@app.route("/settings/update/apply", methods=["POST"])
def office_apply_update_view():
    status = check_office_update()
    if not status.get("update_available"):
        return redirect(url_for("office_settings_view", ok=1, msg="Office dashboard is already up to date"))

    branch = status.get("branch", "main")
    code, stdout, stderr = run_office_git_command(["pull", "--ff-only", "origin", branch], timeout=60)
    save_office_update_status({
        "checked_at": int(time.time()),
        "status": "Update applied. Restarting office dashboard..." if code == 0 else (stderr or stdout or "Update failed"),
        "local_commit": get_office_git_status().get("local_commit", "--"),
        "update_available": False if code == 0 else True,
    })
    if code == 0:
        log_event("office", "office_updated", "Office dashboard updated", detail="Branch %s" % branch)
        restart_office_delayed(1.0)
        return render_template_string(
            """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Restarting Office Dashboard</title>
                <meta http-equiv="refresh" content="6;url={{ url_for('office_settings_view') }}">
                <style>
                    body { margin:0; font-family:Arial, sans-serif; background:#5b5b5b; color:#ececec; }
                    .wrap { max-width:900px; margin:0 auto; padding:30px 16px; }
                    .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:24px; }
                    h1 { margin:0 0 8px 0; }
                    .sub { color:#d2d2d2; }
                </style>
            </head>
            <body>
                <div class="wrap">
                    <div class="panel">
                        <h1>Restarting office dashboard</h1>
                        <div class="sub">The latest code has been pulled. The office dashboard is restarting now and will return to settings automatically.</div>
                    </div>
                </div>
            </body>
            </html>
            """
        )
    return redirect(url_for("office_settings_view", ok=0, msg=stderr or stdout or "Update failed"))


@app.route("/settings/collect-backups")
def collect_controller_backups_now_view():
    maybe_collect_controller_backups()
    return redirect(url_for("office_settings_view", ok=1, msg="Collected controller backups"))


@app.route("/controller-backups/<controller_key>/latest")
def download_collected_controller_backup_view(controller_key):
    rows = list_controller_backup_files(controller_key)
    if not rows:
        abort(404)
    path = rows[0]
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


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


@app.route("/backup/restore")
def restore_office_backup_view():
    backups = []
    for path in list_office_backup_files():
        try:
            mtime = datetime.fromtimestamp(int(os.path.getmtime(path))).strftime("%d %b %Y %H:%M:%S")
        except Exception:
            mtime = "--"
        backups.append({"name": os.path.basename(path), "mtime": mtime})
    controller_copy_rows = []
    config = load_controller_config()
    for key, rec in config.items():
        label = "Shed %s" % key if str(key).isdigit() else str(rec.get("label", key) if isinstance(rec, dict) else key).replace("_", " ").title()
        latest_files = list_controller_backup_files("shed_%s" % key) if str(key).isdigit() else list_controller_backup_files(str(key).strip().lower().replace(" ", "_"))
        latest_name = os.path.basename(latest_files[0]) if latest_files else "--"
        row = {
            "controller_key": "shed_%s" % key if str(key).isdigit() else str(key).strip().lower().replace(" ", "_"),
            "label": label,
            "latest_name": latest_name,
            "restore_kind": "shed" if str(key).isdigit() else ("borehole" if str(key).strip().lower() == "borehole" else ""),
            "shed_no": int(key) if str(key).isdigit() else None,
        }
        controller_copy_rows.append(row)
    return render_template_string(
        RESTORE_HTML,
        backups=backups,
        shed_numbers=SHED_NUMBERS,
        controller_copy_rows=controller_copy_rows,
        status_msg=request.args.get("msg", ""),
        status_ok=request.args.get("ok", "1") == "1",
    )


@app.route("/backup/restore/full", methods=["POST"])
def restore_office_backup_apply_view():
    path = backup_path_by_name(request.form.get("backup_name", ""))
    if not path:
        return redirect(url_for("restore_office_backup_view", ok=0, msg="Backup not found"))
    try:
        restore_full_office_from_backup(path)
        log_event("office", "backup_restored", "Full office backup restored", detail=os.path.basename(path))
        return redirect(url_for("restore_office_backup_view", ok=1, msg="Full office backup restored"))
    except Exception as exc:
        return redirect(url_for("restore_office_backup_view", ok=0, msg="Restore failed: %s" % exc))


@app.route("/backup/restore/shed", methods=["POST"])
def restore_office_backup_shed_view():
    path = backup_path_by_name(request.form.get("backup_name", ""))
    try:
        shed_no = int(request.form.get("shed_no", "0"))
    except Exception:
        shed_no = 0
    if not path or shed_no not in SHED_NUMBERS:
        return redirect(url_for("restore_office_backup_view", ok=0, msg="Invalid restore request"))
    try:
        restore_shed_from_backup(path, shed_no)
        log_event("office", "shed_restored", "Shed backup restored", shed_no=shed_no, detail=os.path.basename(path))
        return redirect(url_for("restore_office_backup_view", ok=1, msg="Shed %d restored from backup" % shed_no))
    except Exception as exc:
        return redirect(url_for("restore_office_backup_view", ok=0, msg="Shed restore failed: %s" % exc))


@app.route("/backup/restore/borehole", methods=["POST"])
def restore_office_backup_borehole_view():
    path = backup_path_by_name(request.form.get("backup_name", ""))
    if not path:
        return redirect(url_for("restore_office_backup_view", ok=0, msg="Backup not found"))
    try:
        restore_borehole_from_backup(path)
        log_event("office", "borehole_restored", "Bore hole backup restored", detail=os.path.basename(path))
        return redirect(url_for("restore_office_backup_view", ok=1, msg="Bore hole restored from backup"))
    except Exception as exc:
        return redirect(url_for("restore_office_backup_view", ok=0, msg="Bore hole restore failed: %s" % exc))


@app.route("/backup/restore/controller-copy/shed", methods=["POST"])
def restore_controller_copy_shed_view():
    controller_key = str(request.form.get("controller_key", "") or "").strip()
    try:
        shed_no = int(request.form.get("shed_no", "0"))
    except Exception:
        shed_no = 0
    files = list_controller_backup_files(controller_key)
    if shed_no not in SHED_NUMBERS or not files:
        return redirect(url_for("restore_office_backup_view", ok=0, msg="Controller copy not found"))
    try:
        restore_shed_from_controller_backup(files[0], shed_no)
        log_event("office", "shed_restored", "Shed restored from office-collected controller copy", shed_no=shed_no, detail=os.path.basename(files[0]))
        return redirect(url_for("restore_office_backup_view", ok=1, msg="Shed %d restored from collected controller copy" % shed_no))
    except Exception as exc:
        return redirect(url_for("restore_office_backup_view", ok=0, msg="Controller copy restore failed: %s" % exc))


@app.route("/backup/restore/controller-copy/borehole", methods=["POST"])
def restore_controller_copy_borehole_view():
    controller_key = str(request.form.get("controller_key", "") or "borehole").strip()
    files = list_controller_backup_files(controller_key)
    if not files:
        return redirect(url_for("restore_office_backup_view", ok=0, msg="Controller copy not found"))
    try:
        restore_borehole_from_controller_backup(files[0])
        log_event("office", "borehole_restored", "Bore hole restored from office-collected controller copy", detail=os.path.basename(files[0]))
        return redirect(url_for("restore_office_backup_view", ok=1, msg="Bore hole restored from collected controller copy"))
    except Exception as exc:
        return redirect(url_for("restore_office_backup_view", ok=0, msg="Controller copy restore failed: %s" % exc))


@app.route("/versions")
def office_versions_view():
    office = load_office_update_status()
    checked_at = office.get("checked_at")
    office["checked_at"] = datetime.fromtimestamp(int(checked_at)).strftime("%d %b %Y %H:%M:%S") if checked_at else "--"
    controller_rows = []
    controller_meta = load_controller_meta()
    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        meta = controller_meta.get(str(shed_no), {}) if isinstance(controller_meta, dict) else {}
        controller_rows.append({
            "label": "Shed %d" % shed_no,
            "app_version": str(meta.get("app_version", "") or "--"),
            "pico_local": str(meta.get("pico_local_hash", "") or "--"),
            "pico_deployed": str(meta.get("pico_deployed_hash", "") or "--"),
            "last_seen": fmt_ts(meta.get("received_ts")),
            "state_version": str(meta.get("controller_sync_version", "") or "--"),
            "office_sync_version": str(meta.get("last_seen_office_sync_version", "") or "--"),
        })
        i += 1
    borehole_meta = load_borehole_meta()
    controller_rows.append({
        "label": "Bore Hole",
        "app_version": str(borehole_meta.get("app_version", "") or "--"),
        "pico_local": str(borehole_meta.get("pico_local_hash", "") or "--"),
        "pico_deployed": str(borehole_meta.get("pico_deployed_hash", "") or "--"),
        "last_seen": fmt_ts(borehole_meta.get("received_ts")),
        "state_version": str(borehole_meta.get("controller_sync_version", "") or "--"),
        "office_sync_version": str(borehole_meta.get("last_seen_office_sync_version", "") or "--"),
    })
    return render_template_string(VERSIONS_HTML, office=office, controller_rows=controller_rows)


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
        active_crop_code=fmt_crop_code(active_crop_id, active_crop_record_for_shed(shed_name).get("placement_epoch")),
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
        active_crop_code=payload["active_crop_code"],
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
    auth_error = require_controller_token(str(shed_no))
    if auth_error:
        return auth_error
    return jsonify(shed_sync_payload(shed_no))


@app.route("/api/shed/<int:shed_no>/sync", methods=["POST"])
def shed_sync_post(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    auth_error = require_controller_token(str(shed_no))
    if auth_error:
        return auth_error

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
    source = str(payload.get("source", "controller") or "controller").strip().lower()
    if source == "borehole_controller":
        auth_error = require_controller_token("borehole")
        if auth_error:
            return auth_error
    else:
        try:
            auth_shed_no = int(payload.get("shed_no")) if payload.get("shed_no") not in [None, ""] else None
        except Exception:
            auth_shed_no = None
        if auth_shed_no in SHED_NUMBERS:
            auth_error = require_controller_token(str(auth_shed_no))
            if auth_error:
                return auth_error
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


@app.route("/api/borehole/sync", methods=["GET"])
def borehole_sync_api_get():
    auth_error = require_controller_token("borehole")
    if auth_error:
        return auth_error
    days = get_borehole_daily_history(max_days=40)
    yesterday_water = days[-1].get("water") if days else None
    return jsonify({
        "ok": True,
        "live": latest_borehole_live(),
        "summary": {
            "water_7to7": yesterday_water,
        },
        "generated_ts": int(time.time()),
    })


@app.route("/api/borehole/sync", methods=["POST"])
def borehole_sync_api_post():
    auth_error = require_controller_token("borehole")
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or {}
    incoming_controller_meta = payload.get("controller_meta")
    if isinstance(incoming_controller_meta, dict):
        save_borehole_meta(clean_borehole_meta(incoming_controller_meta))
    else:
        current_meta = load_borehole_meta()
        current_meta["received_ts"] = int(time.time())
        save_borehole_meta(current_meta)

    live = payload.get("live")
    if isinstance(live, dict):
        merged_live = latest_borehole_live()
        merged_live.update({
            "water_lpm": live.get("water_lpm"),
            "ts": live.get("ts") if live.get("ts") not in [None, ""] else int(time.time()),
            "device": live.get("device"),
            "source": "borehole_controller",
        })
        save_borehole_live(merged_live)

    hourly = payload.get("hourly")
    if isinstance(hourly, dict):
        try:
            hour_epoch = int(hourly.get("hour_epoch"))
            water_hour_liters = float(hourly.get("water_hour_liters"))
        except Exception:
            hour_epoch = None
            water_hour_liters = None
        if hour_epoch is not None and water_hour_liters is not None and not borehole_hour_exists(hour_epoch):
            append_named_json_line("borehole_hourly.ndjson", {
                "ts": int(time.time()),
                "hour_epoch": hour_epoch,
                "water_hour_liters": water_hour_liters,
                "source": "borehole_controller",
            })

    alarms = payload.get("alarms")
    if isinstance(alarms, list):
        i = 0
        while i < len(alarms):
            rec = alarms[i]
            if isinstance(rec, dict):
                append_named_json_line("borehole_alarm.ndjson", {
                    "ts": int(rec.get("ts") or time.time()),
                    "alarm_key": str(rec.get("alarm_key") or ""),
                    "active": 1 if int(rec.get("active", 1) or 0) == 1 else 0,
                    "message": str(rec.get("message") or ""),
                })
            i += 1

    days = get_borehole_daily_history(max_days=40)
    yesterday_water = days[-1].get("water") if days else None
    return jsonify({
        "ok": True,
        "summary": {
            "water_7to7": yesterday_water,
        },
        "generated_ts": int(time.time()),
    })


@app.route("/api/shed/<int:shed_no>/current-crop/hourly", methods=["GET"])
def shed_current_crop_hourly_api(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)

    shed_name = shed_name_from_number(shed_no)
    active_crop_id = get_active_crop_id_for_shed(shed_name)
    active_crop = active_crop_record_for_shed(shed_name)
    rows = get_hourly_history_for_shed(shed_name, max_points=168, crop_id=active_crop_id)

    return jsonify({
        "shed_no": shed_no,
        "shed": shed_name,
        "crop_id": active_crop_id,
        "crop_code": fmt_crop_code(active_crop_id, active_crop.get("placement_epoch")),
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
    active_crop = active_crop_record_for_shed(shed_name)
    active_crop_code = fmt_crop_code(active_crop_id, active_crop.get("placement_epoch"))

    if period == "hourly":
        rows = get_hourly_history_for_shed(shed_name, max_points=168, crop_id=active_crop_id)
        rows = add_running_totals(rows)
        period_title = "Hourly"
        period_sub = "Current crop %s hourly list with running totals and separate zoomable feed and water charts." % active_crop_code
        first_col = "Hour"
    else:
        rows = get_daily_history_for_shed(shed_name, max_days=40, crop_id=active_crop_id)
        rows = add_running_totals(rows)
        period_title = "Daily"
        period_sub = "Current crop %s completed 7am-7am daily list with running totals and separate zoomable feed and water charts." % active_crop_code
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
    crop_start_epoch = None

    if period == "hourly":
        rows = get_hourly_history_for_shed(shed_name, max_points=0, crop_id=crop_id)
        if rows:
            try:
                crop_start_epoch = int(rows[0].get("hour_epoch"))
            except Exception:
                crop_start_epoch = None
        rows = add_running_totals(rows)
        period_title = "%s Hourly" % fmt_crop_code(crop_id, crop_start_epoch)
        period_sub = "Historic crop %s hourly list with running totals and separate zoomable feed and water charts." % fmt_crop_code(crop_id, crop_start_epoch)
        first_col = "Hour"
    else:
        rows = get_daily_history_for_shed(shed_name, max_days=0, crop_id=crop_id)
        if rows:
            try:
                crop_start_epoch = int(rows[0].get("bucket_start_epoch"))
            except Exception:
                crop_start_epoch = None
        rows = add_running_totals(rows)
        period_title = "%s Daily" % fmt_crop_code(crop_id, crop_start_epoch)
        period_sub = "Historic crop %s completed 7am-7am daily list with running totals and separate zoomable feed and water charts." % fmt_crop_code(crop_id, crop_start_epoch)
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
    start_office_background_workers()
    app.run(host="0.0.0.0", port=8090)
