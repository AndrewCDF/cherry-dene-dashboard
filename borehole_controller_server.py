from flask import Flask, Response, jsonify, redirect, render_template_string, request, send_file, url_for
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta


APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_ROOT, "borehole_controller_data")
STATE_LOCK = threading.Lock()

DEFAULT_CONFIG = {
    "dashboard_url": "http://127.0.0.1:8090",
    "sync_token": "",
    "deployment_mode": "commissioning",
    "commissioning_mode": True,
    "mode_switch_pin": "2468",
    "listen_port": 8092,
    "touch_refresh_seconds": 1,
    "water_low_lpm": 0.1,
    "water_pulses_per_litre": 450.0,
    "backup_keep": 6,
}
LOCAL_OFFICE_HEARTBEAT_SECONDS = 10
LOCAL_BACKGROUND_SYNC_LOOP_SECONDS = 5
SENSOR_STALE_SECONDS = 30
NO_FLOW_EPSILON_LPM = 0.01
HIDE_HOME_ALERTS_DURING_SETUP = True
SYSTEM_ACTION_PATHS = {
    "shutdown": [("/sbin/shutdown", ["-h", "now"]), ("/usr/sbin/shutdown", ["-h", "now"])],
    "reboot": [("/sbin/reboot", []), ("/usr/sbin/reboot", [])],
}


app = Flask(__name__)

CDF_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="12" fill="#4f4f4f"/>
<rect x="4" y="4" width="56" height="56" rx="10" fill="none" stroke="#35d07f" stroke-width="2.5"/>
<text x="32" y="39" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="23" font-weight="700" fill="#f1f1f1">CDF</text>
</svg>"""

TOUCH_OPTIMIZE_HEAD = (
    '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'
    '<style id="cdf-touch-optimize">'
    'html,body{touch-action:pan-y;overscroll-behavior-y:contain;-webkit-overflow-scrolling:touch;}'
    'body,*{-webkit-tap-highlight-color:transparent;-webkit-touch-callout:none;}'
    'body,div,span,p,h1,h2,h3,h4,h5,h6,table,thead,tbody,tr,th,td,a,button,label,.button-link,.metric-link,.settings-button{-webkit-user-select:none;user-select:none;}'
    'a,.button-link,.metric-link,.settings-button{touch-action:pan-y;}'
    'button,input,select,textarea,label,summary{touch-action:manipulation;}'
    'input,textarea,select,.mono{-webkit-user-select:text;user-select:text;}'
    '.cdf-number-pad{position:fixed;right:12px;bottom:12px;z-index:9999;width:min(420px,calc(100vw - 24px));padding:10px;background:rgba(54,54,54,0.96);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,0.14);border-radius:18px;box-shadow:0 18px 36px rgba(0,0,0,0.28);transform:translateY(calc(100% + 16px));transition:transform .12s ease-out;}'
    '.cdf-number-pad.is-open{transform:translateY(0);}'
    '.cdf-number-pad__panel{max-width:none;margin:0;}'
    '.cdf-number-pad__head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px;color:#ececec;font:700 15px/1 Arial,sans-serif;}'
    '.cdf-number-pad__value{color:#d2d2d2;font:600 13px/1 Arial,sans-serif;min-height:14px;}'
    '.cdf-number-pad__grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;}'
    '.cdf-number-pad__key{min-height:52px;border-radius:12px;border:1px solid #8a8a8a;background:linear-gradient(180deg,#7a7a7a,#676767);color:#ececec;font:700 22px/1 Arial,sans-serif;}'
    '.cdf-number-pad__key--wide{grid-column:span 2;}'
    '.cdf-number-pad__key--action{background:linear-gradient(180deg,#6f6f6f,#5f5f5f);font-size:17px;}'
    '.cdf-number-pad__key[hidden]{display:none;}'
    '@media (max-width:700px){.cdf-number-pad{left:10px;right:10px;bottom:10px;width:auto;padding:10px;}.cdf-number-pad__key{min-height:54px;}}'
    '</style>'
)

NUMBER_PAD_BODY = """
<div id="cdfNumberPad" class="cdf-number-pad" aria-hidden="true">
  <div class="cdf-number-pad__panel">
    <div class="cdf-number-pad__head">
      <span>Number Entry</span>
      <span id="cdfNumberPadValue" class="cdf-number-pad__value"></span>
    </div>
    <div class="cdf-number-pad__grid">
      <button type="button" class="cdf-number-pad__key" data-key="7">7</button>
      <button type="button" class="cdf-number-pad__key" data-key="8">8</button>
      <button type="button" class="cdf-number-pad__key" data-key="9">9</button>
      <button type="button" class="cdf-number-pad__key" data-key="4">4</button>
      <button type="button" class="cdf-number-pad__key" data-key="5">5</button>
      <button type="button" class="cdf-number-pad__key" data-key="6">6</button>
      <button type="button" class="cdf-number-pad__key" data-key="1">1</button>
      <button type="button" class="cdf-number-pad__key" data-key="2">2</button>
      <button type="button" class="cdf-number-pad__key" data-key="3">3</button>
      <button type="button" class="cdf-number-pad__key cdf-number-pad__key--action" data-action="clear">Clear</button>
      <button type="button" class="cdf-number-pad__key" data-key="0">0</button>
      <button type="button" id="cdfNumberPadDecimal" class="cdf-number-pad__key" data-key=".">.</button>
      <button type="button" class="cdf-number-pad__key cdf-number-pad__key--action" data-action="backspace">Back</button>
      <button type="button" class="cdf-number-pad__key cdf-number-pad__key--action cdf-number-pad__key--wide" data-action="done">Done</button>
    </div>
  </div>
</div>
<script id="cdf-number-pad-script">
(function () {
  const pad = document.getElementById('cdfNumberPad');
  if (!pad) return;
  const valueEl = document.getElementById('cdfNumberPadValue');
  const decimalBtn = document.getElementById('cdfNumberPadDecimal');
  let activeInput = null;
  let dragScroll = null;
  let suppressClickUntil = 0;

  function supportsDecimal(input) {
    const inputMode = (input.getAttribute('inputmode') || '').toLowerCase();
    if (inputMode === 'decimal') return true;
    const step = (input.getAttribute('step') || '').toLowerCase();
    if (step === 'any') return true;
    return step.indexOf('.') !== -1;
  }

  function syncDisplay() {
    valueEl.textContent = activeInput ? (activeInput.value || ' ') : '';
    if (activeInput) {
      decimalBtn.hidden = !supportsDecimal(activeInput);
    }
  }

  function openPad(input) {
    if (!input || input.disabled) return;
    activeInput = input;
    pad.classList.add('is-open');
    pad.setAttribute('aria-hidden', 'false');
    syncDisplay();
  }

  function closePad() {
    activeInput = null;
    pad.classList.remove('is-open');
    pad.setAttribute('aria-hidden', 'true');
    valueEl.textContent = '';
  }

  function commitValue(nextValue) {
    if (!activeInput) return;
    activeInput.value = nextValue;
    activeInput.dispatchEvent(new Event('input', { bubbles: true }));
    activeInput.dispatchEvent(new Event('change', { bubbles: true }));
    syncDisplay();
  }

  document.addEventListener('focusin', function (event) {
    const target = event.target;
    if (target && target.matches && target.matches('input[type="number"]')) {
      openPad(target);
    }
  });

  function isInteractiveTarget(target) {
    return !!(target && target.closest && target.closest('input, textarea, select, button, .cdf-number-pad'));
  }

  document.addEventListener('touchstart', function (event) {
    if (!event.touches || event.touches.length !== 1) return;
    const target = event.target;
    if (isInteractiveTarget(target)) return;
    const touch = event.touches[0];
    dragScroll = {
      startY: touch.clientY,
      lastY: touch.clientY,
      moved: false,
    };
  }, { passive: true });

  document.addEventListener('touchmove', function (event) {
    if (!dragScroll || !event.touches || event.touches.length !== 1) return;
    const touch = event.touches[0];
    const deltaY = touch.clientY - dragScroll.lastY;
    const totalMove = touch.clientY - dragScroll.startY;
    if (Math.abs(totalMove) > 6) {
      dragScroll.moved = true;
    }
    if (dragScroll.moved) {
      window.scrollBy(0, -deltaY);
      dragScroll.lastY = touch.clientY;
      suppressClickUntil = Date.now() + 250;
      event.preventDefault();
    }
  }, { passive: false });

  document.addEventListener('touchend', function () {
    dragScroll = null;
  }, { passive: true });

  document.addEventListener('click', function (event) {
    if (Date.now() < suppressClickUntil) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);

  document.addEventListener('pointerdown', function (event) {
    const target = event.target;
    if (target && target.matches && target.matches('input[type="number"]')) {
      openPad(target);
      return;
    }
    if (!pad.contains(target)) {
      closePad();
    }
  });

  pad.addEventListener('click', function (event) {
    const button = event.target.closest('button');
    if (!button || !activeInput) return;
    const action = button.getAttribute('data-action');
    const key = button.getAttribute('data-key');
    const current = String(activeInput.value || '');

    if (action === 'clear') {
      commitValue('');
      return;
    }
    if (action === 'backspace') {
      commitValue(current.slice(0, -1));
      return;
    }
    if (action === 'done') {
      activeInput.blur();
      closePad();
      return;
    }
    if (!key) return;
    if (key === '.' && (!supportsDecimal(activeInput) || current.includes('.'))) return;
    if (current === '0' && key !== '.') {
      commitValue(key);
      return;
    }
    commitValue(current + key);
  });
})();
</script>
"""


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
            if "<head>" in body and 'cdf-touch-optimize' not in body:
                body = body.replace('<head>', '<head>' + TOUCH_OPTIMIZE_HEAD, 1)
            if "</body>" in body and 'cdf-number-pad-script' not in body:
                body = body.replace("</body>", NUMBER_PAD_BODY + "</body>", 1)
            response.set_data(body)
            response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception:
        pass
    return response


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
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=parent)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def host_ipv4_addresses():
    seen = []

    def add_ip(ip):
        ip = str(ip or "").strip()
        if not ip or ip.startswith("127."):
            return
        if ip not in seen:
            seen.append(ip)

    try:
        output = subprocess.check_output(["hostname", "-I"], text=True, stderr=subprocess.DEVNULL)
        for part in output.split():
            if part.count(".") == 3:
                add_ip(part)
    except Exception:
        pass

    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM)
        for info in infos:
            add_ip(info[4][0])
    except Exception:
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        add_ip(sock.getsockname()[0])
        sock.close()
    except Exception:
        pass

    def sort_key(ip):
        if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
            return (0, ip)
        if ip.startswith("100."):
            return (1, ip)
        return (2, ip)

    seen.sort(key=sort_key)
    return seen


def host_ipv4_display():
    ips = host_ipv4_addresses()
    return " • ".join(ips) if ips else "--"


def append_named_json_line(name, payload):
    ensure_data_dir()
    path = os.path.join(DATA_DIR, name)
    with open(path, "a") as f:
        f.write(json.dumps(payload) + "\n")


def read_all_json_lines(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def fmt_value(value, fmt=None):
    if value in [None, ""]:
        return "--"
    try:
        if fmt == "f0":
            return f"{float(value):,.0f}"
        if fmt == "f1":
            return f"{float(value):,.1f}"
        if fmt == "f2":
            return f"{float(value):,.2f}"
        if fmt == "i":
            return f"{int(value):,d}"
        return str(value)
    except Exception:
        return "--"


def fmt_ts(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%d %b %Y %H:%M:%S")
    except Exception:
        return "--"


def fmt_age_seconds(ts):
    try:
        age = max(0, int(time.time()) - int(ts))
    except Exception:
        return "--"
    if age < 60:
        return "%ds ago" % age
    if age < 3600:
        return "%dm ago" % (age // 60)
    return "%dh %02dm ago" % (age // 3600, (age % 3600) // 60)


def run_system_action(action_name):
    action_paths = SYSTEM_ACTION_PATHS.get(action_name, [])
    executable = None
    extra_args = []
    for candidate, args in action_paths:
        if os.path.exists(candidate):
            executable = candidate
            extra_args = list(args)
            break
    if not executable:
        return False, "System action is not available on this controller"
    try:
        proc = subprocess.run(
            ["sudo", "-n", executable] + extra_args,
            cwd=APP_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if not detail:
            detail = "Passwordless sudo is not configured for this controller"
        return False, detail
    return True, ""


def restart_self_delayed(delay_seconds=1.0):
    def _restart():
        time.sleep(delay_seconds)
        if os.environ.get("INVOCATION_ID") or os.environ.get("JOURNAL_STREAM"):
            os._exit(0)
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])

    threading.Thread(target=_restart, daemon=True).start()


def local_ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def load_config():
    ensure_data_dir()
    path = os.path.join(DATA_DIR, "controller_config.json")
    cfg = read_json_file(path, {})
    merged = dict(DEFAULT_CONFIG)
    if isinstance(cfg, dict):
        merged.update(cfg)
    merged["deployment_mode"] = str(merged.get("deployment_mode", "commissioning") or "commissioning").strip().lower()
    if merged["deployment_mode"] not in ["commissioning", "live"]:
        merged["deployment_mode"] = "commissioning"
    merged["commissioning_mode"] = bool(merged.get("commissioning_mode", merged["deployment_mode"] != "live"))
    merged["deployment_mode"] = "commissioning" if merged["commissioning_mode"] else "live"
    merged["mode_switch_pin"] = str(merged.get("mode_switch_pin", DEFAULT_CONFIG["mode_switch_pin"]) or DEFAULT_CONFIG["mode_switch_pin"]).strip()
    return merged


def commissioning_mode_enabled(cfg=None):
    cfg = cfg or load_config()
    return bool(cfg.get("commissioning_mode", True))


def current_mode_label(cfg=None):
    return "Commissioning" if commissioning_mode_enabled(cfg) else "Live"


def save_config(cfg):
    path = os.path.join(DATA_DIR, "controller_config.json")
    write_json_file_atomic(path, cfg)


def default_state():
    return {
        "sensors": {
            "water_lpm": None,
            "flow_total_pulses": None,
            "last_sensor_ts": None,
            "device_status": "USB Disconnected",
            "pico_connected": False,
            "controller_alarms": [],
            "raw": {},
        },
        "dashboard_summary": {
            "water_7to7": None,
        },
        "last_push_ts": None,
        "last_push_status": "Waiting",
        "last_dashboard_contact_ts": None,
        "last_dashboard_status": "Waiting",
        "last_log_ts": None,
        "last_log_status": "Waiting",
        "last_backup_ts": None,
        "last_backup_status": "Waiting",
        "last_sync_ts": None,
        "last_sync_status": "No sync yet",
        "hourly_rollup": {
            "hour_epoch": None,
            "water_liters": 0.0,
            "last_sample_ts": None,
            "last_total_pulses": None,
        },
        "water_calibration": {
            "active": False,
            "start_ts": None,
            "end_ts": None,
            "start_total_pulses": None,
            "latest_total_pulses": None,
            "completed": False,
            "pulse_delta": None,
        },
        "state_version": 0,
        "state_updated_ts": None,
        "last_pico_deployed_hash": "--",
    }


def load_state():
    ensure_data_dir()
    path = os.path.join(DATA_DIR, "controller_state.json")
    data = read_json_file(path, default_state())
    state = default_state()
    if isinstance(data, dict):
        state.update(data)
    sensors = dict(default_state()["sensors"])
    sensors.update(state.get("sensors", {}))
    if not isinstance(sensors.get("controller_alarms"), list):
        sensors["controller_alarms"] = []
    if not isinstance(sensors.get("raw"), dict):
        sensors["raw"] = {}
    state["sensors"] = sensors
    refresh_controller_alarms_in_state(state)
    return state


def save_state(state):
    path = os.path.join(DATA_DIR, "controller_state.json")
    write_json_file_atomic(path, state)


def mutate_state(mutator):
    with STATE_LOCK:
        state = load_state()
        mutator(state)
        refresh_controller_alarms_in_state(state)
        state["state_version"] = int(state.get("state_version", 0) or 0) + 1
        state["state_updated_ts"] = int(time.time())
        save_state(state)
        return state


def pico_firmware_path():
    return os.path.join(APP_ROOT, "pico_firmware", "main.py")


def pico_firmware_hash():
    path = pico_firmware_path()
    if not os.path.exists(path):
        return "--"
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:10]


def mpremote_command():
    direct = shutil.which("mpremote")
    if direct:
        return [direct]
    user_local = os.path.join(os.path.expanduser("~"), ".local", "bin", "mpremote")
    if os.path.exists(user_local):
        return [user_local]
    return [sys.executable, "-m", "mpremote"]


def build_controller_alarms(state, cfg=None):
    cfg = cfg or load_config()
    if commissioning_mode_enabled(cfg):
        return []
    sensors = state.get("sensors", {})
    alarms = []
    now_ts = int(time.time())

    pico_connected = bool(sensors.get("pico_connected"))
    last_sensor_ts = sensors.get("last_sensor_ts")
    try:
        sensor_age = now_ts - int(last_sensor_ts) if last_sensor_ts not in [None, ""] else None
    except Exception:
        sensor_age = None
    sensor_recent = sensor_age is not None and sensor_age <= SENSOR_STALE_SECONDS

    if not pico_connected or not sensor_recent:
        alarms.append({
            "alarm_key": "no_pico",
            "message": "No Pico detected",
        })
        return alarms

    water = sensors.get("water_lpm")
    try:
        water_f = float(water) if water not in [None, ""] else None
    except Exception:
        water_f = None

    pulses = sensors.get("flow_total_pulses")
    no_flow = pulses in [None, ""] or water_f is None or water_f <= NO_FLOW_EPSILON_LPM
    if no_flow:
        alarms.append({
            "alarm_key": "no_flow",
            "message": "No pulses / flow detected",
        })
        return alarms

    low_flow_threshold = float(cfg.get("water_low_lpm", 0.1) or 0.1)
    if water_f < low_flow_threshold:
        alarms.append({
            "alarm_key": "low_flow",
            "message": "Low flow alarm: below %.2f L/PM" % low_flow_threshold,
        })

    return alarms


def refresh_controller_alarms_in_state(state, cfg=None):
    sensors = state.get("sensors", {})
    sensors["controller_alarms"] = build_controller_alarms(state, cfg=cfg)
    state["sensors"] = sensors


def record_event(event_type, message, detail=""):
    append_named_json_line("events.ndjson", {
        "ts": int(time.time()),
        "event_type": event_type,
        "message": message,
        "detail": detail,
    })


def get_events(limit=200):
    rows = read_all_json_lines("events.ndjson")
    rows.sort(key=lambda r: int(r.get("ts", 0)), reverse=True)
    rows = rows[:limit]
    for row in rows:
        row["ts_label"] = fmt_ts(row.get("ts"))
    return rows


def custom_day_key(dt_obj):
    if dt_obj.hour < 7:
        dt_obj = dt_obj - timedelta(days=1)
    return dt_obj.strftime("%Y-%m-%d")


def get_hourly_history(max_points=168):
    rows = []
    for rec in read_all_json_lines("hourly.ndjson"):
        try:
            hour_epoch = int(rec.get("hour_epoch"))
            water = float(rec.get("water_hour_liters"))
        except Exception:
            continue
        rows.append({
            "epoch": hour_epoch,
            "label": datetime.fromtimestamp(hour_epoch).strftime("%d %b %H:%M"),
            "water": water,
        })
    rows.sort(key=lambda r: r["epoch"])
    if max_points and len(rows) > max_points:
        rows = rows[-max_points:]
    return rows


def get_daily_history(max_days=40):
    rows = get_hourly_history(max_points=0)
    day_totals = {}
    latest_epoch = None
    for row in rows:
        try:
            epoch = int(row["epoch"])
            dt_obj = datetime.fromtimestamp(epoch)
        except Exception:
            continue
        key = custom_day_key(dt_obj)
        if latest_epoch is None or epoch > latest_epoch:
            latest_epoch = epoch
        day_totals.setdefault(key, {"water": 0.0})
        if row.get("water") is not None:
            day_totals[key]["water"] += float(row["water"])
    active_key = custom_day_key(datetime.fromtimestamp(latest_epoch)) if latest_epoch is not None else None
    out = []
    for key in sorted(day_totals.keys()):
        if key == active_key:
            continue
        try:
            label = datetime.strptime(key, "%Y-%m-%d").strftime("%d %b")
        except Exception:
            label = key
        out.append({"label": label, "water": day_totals[key]["water"]})
    if max_days and len(out) > max_days:
        out = out[-max_days:]
    return out


def list_backup_files():
    ensure_data_dir()
    backup_dir = os.path.join(DATA_DIR, "backups")
    rows = []
    for name in os.listdir(backup_dir):
        if name.endswith(".zip"):
            rows.append(os.path.join(backup_dir, name))
    rows.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return rows


def prune_backup_files():
    keep = int(load_config().get("backup_keep", 6) or 6)
    rows = list_backup_files()
    i = keep
    while i < len(rows):
        try:
            os.remove(rows[i])
        except Exception:
            pass
        i += 1


def create_backup_zip(tag="auto"):
    ensure_data_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = "borehole-controller-%s-%s.zip" % (tag, ts)
    path = os.path.join(DATA_DIR, "backups", name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename in ["controller_config.json", "controller_state.json", "events.ndjson", "live.ndjson", "hourly.ndjson"]:
            src = os.path.join(DATA_DIR, filename)
            if os.path.exists(src):
                zf.write(src, arcname=filename)
    prune_backup_files()
    mutate_state(lambda state: state.update({
        "last_backup_ts": int(time.time()),
        "last_backup_status": "Backup OK: %s" % os.path.basename(path),
    }))
    return path


def maybe_auto_backup():
    state = load_state()
    last_ts = state.get("last_backup_ts")
    if last_ts in [None, ""] or int(time.time()) - int(last_ts) >= 3600:
        try:
            create_backup_zip("auto")
        except Exception as exc:
            mutate_state(lambda s: s.update({
                "last_backup_ts": int(time.time()),
                "last_backup_status": "Backup failed: %s" % exc,
            }))


def backup_worker():
    while True:
        maybe_auto_backup()
        time.sleep(60)


def record_live_log(sensors):
    append_named_json_line("live.ndjson", {
        "ts": int(time.time()),
        "water_lpm": sensors.get("water_lpm"),
        "flow_total_pulses": sensors.get("flow_total_pulses"),
    })
    mutate_state(lambda state: state.update({
        "last_log_ts": int(time.time()),
        "last_log_status": "Log OK",
    }))


def close_hour_if_needed(state, now_ts):
    roll = state.get("hourly_rollup", {})
    hour_epoch = roll.get("hour_epoch")
    current_hour = (int(now_ts) // 3600) * 3600
    if hour_epoch not in [None, current_hour]:
        append_named_json_line("hourly.ndjson", {
            "ts": int(time.time()),
            "hour_epoch": int(hour_epoch),
            "water_hour_liters": float(roll.get("water_liters", 0.0) or 0.0),
        })
        payload = {
            "live": {
                "water_lpm": state.get("sensors", {}).get("water_lpm"),
                "ts": state.get("sensors", {}).get("last_sensor_ts") or int(time.time()),
                "device": "borehole_controller",
            },
            "hourly": {
                "hour_epoch": int(hour_epoch),
                "water_hour_liters": float(roll.get("water_liters", 0.0) or 0.0),
            },
        }
        push_to_dashboard_payload(payload, state)
        roll["hour_epoch"] = current_hour
        roll["water_liters"] = 0.0
        roll["last_sample_ts"] = now_ts


def update_rollup_from_sample(state, water_lpm, total_pulses=None, ts=None):
    now_ts = int(ts or time.time())
    roll = state.get("hourly_rollup", {})
    current_hour = (now_ts // 3600) * 3600
    if roll.get("hour_epoch") is None:
        roll["hour_epoch"] = current_hour
        roll["water_liters"] = 0.0
        roll["last_sample_ts"] = now_ts
        roll["last_total_pulses"] = total_pulses
        state["hourly_rollup"] = roll
        return
    close_hour_if_needed(state, now_ts)
    roll = state.get("hourly_rollup", {})
    last_sample_ts = roll.get("last_sample_ts")
    liters_delta = 0.0
    if total_pulses not in [None, ""] and roll.get("last_total_pulses") not in [None, ""]:
        try:
            pulses_per_litre = float(load_config().get("water_pulses_per_litre", 450.0))
            pulse_delta = max(0, int(total_pulses) - int(roll.get("last_total_pulses")))
            liters_delta = float(pulse_delta) / pulses_per_litre
        except Exception:
            liters_delta = 0.0
    elif last_sample_ts not in [None, ""] and water_lpm not in [None, ""]:
        try:
            sec_delta = max(0, int(now_ts) - int(last_sample_ts))
            liters_delta = (float(water_lpm) * sec_delta) / 60.0
        except Exception:
            liters_delta = 0.0
    roll["water_liters"] = float(roll.get("water_liters", 0.0) or 0.0) + liters_delta
    roll["last_sample_ts"] = now_ts
    roll["last_total_pulses"] = total_pulses
    roll["hour_epoch"] = current_hour
    state["hourly_rollup"] = roll


def run_git(args, timeout=20):
    proc = subprocess.run(["git", "-C", APP_ROOT] + list(args), capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def check_for_update():
    code, branch, err = run_git(["branch", "--show-current"])
    if code != 0:
        return {"status": err or "Git error", "update_available": False, "branch": "main", "local_commit": "--", "remote_commit": "--"}
    branch = branch or "main"
    _, local_commit, _ = run_git(["rev-parse", "--short", "HEAD"])
    code, _, err = run_git(["fetch", "origin", branch], timeout=30)
    if code != 0:
        return {"status": err or "Fetch failed", "update_available": False, "branch": branch, "local_commit": local_commit or "--", "remote_commit": "--"}
    _, remote_commit, _ = run_git(["rev-parse", "--short", "origin/%s" % branch])
    return {
        "status": "Update available" if remote_commit and remote_commit != local_commit else "Already on latest version",
        "update_available": bool(remote_commit and remote_commit != local_commit),
        "branch": branch,
        "local_commit": local_commit or "--",
        "remote_commit": remote_commit or "--",
    }


def local_version_info():
    code, branch, _ = run_git(["branch", "--show-current"])
    code2, commit, _ = run_git(["rev-parse", "--short", "HEAD"])
    return {
        "branch": branch if code == 0 and branch else "main",
        "local_commit": commit if code2 == 0 and commit else "--",
    }


def apply_update():
    status = check_for_update()
    if not status.get("update_available"):
        return False, status.get("status", "Already on latest version")
    code, out, err = run_git(["pull", "--ff-only", "origin", status["branch"]], timeout=60)
    return (code == 0), (out or err or "Update finished")


def push_to_dashboard_payload(payload, state=None):
    cfg = load_config()
    base_url = str(cfg.get("dashboard_url") or "").rstrip("/")
    if not base_url:
        return False, "No office URL configured"
    if state is None:
        state = load_state()
    sensors = state.get("sensors", {})
    merged_payload = dict(payload)
    version = local_version_info()
    merged_payload["controller_meta"] = {
        "last_sensor_ts": sensors.get("last_sensor_ts"),
        "device_status": sensors.get("device_status"),
        "pico_connected": sensors.get("pico_connected"),
        "controller_alarms": sensors.get("controller_alarms", []),
        "controller_sync_version": state.get("state_version", 0),
        "controller_state_updated_ts": state.get("state_updated_ts"),
        "last_backup_ts": state.get("last_backup_ts"),
        "last_backup_status": state.get("last_backup_status"),
        "app_branch": version.get("branch", "main"),
        "app_version": version.get("local_commit", "--"),
        "pico_local_hash": pico_firmware_hash(),
        "pico_deployed_hash": str(state.get("last_pico_deployed_hash", "") or "--"),
    }
    headers = {"Content-Type": "application/json"}
    token = str(cfg.get("sync_token", "") or "").strip()
    if token:
        headers["X-Controller-Token"] = token
    req = urllib.request.Request(
        base_url + "/api/borehole/sync",
        data=json.dumps(merged_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            def mutator(s):
                s["last_push_ts"] = int(time.time())
                s["last_push_status"] = "Push OK"
                s["last_dashboard_contact_ts"] = int(time.time())
                s["last_dashboard_status"] = "Office Reachable"
                if isinstance(data, dict):
                    summary = data.get("summary", {})
                    if isinstance(summary, dict):
                        s["dashboard_summary"] = {"water_7to7": summary.get("water_7to7")}
                s["last_sync_ts"] = int(time.time())
                s["last_sync_status"] = "Office sync OK"
            mutate_state(mutator)
            return True, "Push OK"
    except Exception as exc:
        mutate_state(lambda s: s.update({
            "last_push_ts": int(time.time()),
            "last_push_status": "Push failed",
            "last_dashboard_status": "Office error: %s" % exc,
            "last_sync_status": "Office sync failed",
        }))
        return False, str(exc)


def push_current_state():
    state = load_state()
    sensors = state.get("sensors", {})
    payload = {
        "live": {
            "water_lpm": sensors.get("water_lpm"),
            "ts": sensors.get("last_sensor_ts") or int(time.time()),
            "device": "borehole_controller",
        },
    }
    return push_to_dashboard_payload(payload, state)


def maybe_heartbeat_to_dashboard(min_age_seconds=LOCAL_OFFICE_HEARTBEAT_SECONDS):
    state = load_state()
    last_push_ts = state.get("last_push_ts")
    now_ts = int(time.time())
    try:
        last_push_ts = int(last_push_ts) if last_push_ts not in [None, ""] else None
    except Exception:
        last_push_ts = None

    if last_push_ts is None or (now_ts - last_push_ts) >= int(min_age_seconds):
        push_current_state()


def background_sync_loop():
    while True:
        try:
            maybe_heartbeat_to_dashboard()
        except Exception:
            pass
        time.sleep(LOCAL_BACKGROUND_SYNC_LOOP_SECONDS)


def require_office_token():
    expected = str(load_config().get("sync_token", "") or "").strip()
    if not expected:
        return None
    provided = str(request.headers.get("X-Controller-Token", "") or "").strip()
    if provided != expected:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    return None


def home_context():
    cfg = load_config()
    state = load_state()
    sensors = state.get("sensors", {})
    water = sensors.get("water_lpm")
    try:
        water_f = float(water) if water not in [None, ""] else None
    except Exception:
        water_f = None
    water_glow = "flow-red" if water_f is None or water_f < float(cfg.get("water_low_lpm", 0.1)) else "flow-green"
    daily = state.get("dashboard_summary", {}).get("water_7to7")
    alarms = sensors.get("controller_alarms", [])
    alarm_class = "bad" if alarms else "ok"
    alarm_short = "Active" if alarms else "OK"
    push_status = state.get("last_push_status", "Waiting")
    push_class = "ok" if "OK" in push_status else "bad"
    office_status = state.get("last_dashboard_status", "Waiting")
    office_class = "ok" if "Reachable" in office_status else "bad"
    pico_connected = bool(sensors.get("pico_connected"))
    pico_class = "ok" if pico_connected else "bad"
    pico_short = "Connected" if pico_connected else "Disconnected"
    log_status = state.get("last_log_status", "Waiting")
    log_class = "ok" if "OK" in log_status else "bad"
    sync_status = state.get("last_sync_status", "No sync yet")
    sync_class = "ok" if "OK" in sync_status else "bad"
    office_age = fmt_age_seconds(state.get("last_dashboard_contact_ts"))
    sync_age = fmt_age_seconds(state.get("last_sync_ts"))
    last_sensor_ts = sensors.get("last_sensor_ts")
    try:
        sensor_age = int(time.time()) - int(last_sensor_ts) if last_sensor_ts not in [None, ""] else None
    except Exception:
        sensor_age = None
    header_class = "active" if pico_connected and sensor_age is not None and sensor_age <= SENSOR_STALE_SECONDS else "inactive"
    return {
        "host_ips": host_ipv4_display(),
        "refresh_seconds": max(1, int(cfg.get("touch_refresh_seconds", 1) or 1)),
        "water_lpm": fmt_value(water, "f2"),
        "water_glow": water_glow,
        "header_class": header_class,
        "water_7to7": fmt_value(daily, "f0"),
        "alarm_class": alarm_class,
        "alarm_short": alarm_short,
        "office_class": office_class,
        "office_short": ("OK • %s" % office_age) if office_class == "ok" else ("WAIT • %s" % office_age),
        "sync_class": sync_class,
        "sync_short": ("OK • %s" % sync_age) if sync_class == "ok" else ("WAIT • %s" % sync_age),
        "pico_class": pico_class,
        "pico_short": pico_short,
        "push_class": push_class,
        "push_short": "OK" if push_class == "ok" else "WAIT",
        "log_class": log_class,
        "log_short": "OK" if log_class == "ok" else "WAIT",
        "current_datetime": datetime.now().strftime("%d %b %Y %H:%M:%S"),
    }


HOME_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Bore Hole Controller</title>
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
  <style>
    :root { --bg:#5b5b5b; --panel:rgba(115,115,115,0.96); --panel2:rgba(104,104,104,0.98); --line:#8a8a8a; --text:#ececec; --muted:#d2d2d2; }
    body { margin:0; background:var(--bg); color:var(--text); font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }
    .wrap { max-width:1024px; margin:0 auto; padding:18px; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:18px; }
    h1 { margin:0; font-size:40px; line-height:1; }
    h1.active {
      text-shadow:0 0 10px rgba(53,208,127,0.95),0 0 20px rgba(53,208,127,0.65),0 0 34px rgba(53,208,127,0.35);
    }
    h1.inactive {
      text-shadow:0 0 10px rgba(255,91,91,0.95),0 0 20px rgba(255,91,91,0.65),0 0 34px rgba(255,91,91,0.35);
    }
    .title-row { display:flex; align-items:center; justify-content:space-between; gap:16px; }
    .hero-datetime { font-size:18px; font-weight:700; }
    .hero-datetime.active {
      text-shadow:0 0 10px rgba(53,208,127,0.95),0 0 20px rgba(53,208,127,0.65),0 0 34px rgba(53,208,127,0.35);
    }
    .hero-datetime.inactive {
      text-shadow:0 0 10px rgba(255,91,91,0.95),0 0 20px rgba(255,91,91,0.65),0 0 34px rgba(255,91,91,0.35);
    }
    .hero-pills { margin-top:14px; }
    .pill-grid { display:grid; grid-template-columns:repeat(6, minmax(0,1fr)); gap:8px; }
    .pill { border-radius:14px; border:1px solid var(--line); background:var(--panel2); padding:7px 8px; min-height:44px; display:flex; flex-direction:column; justify-content:center; align-items:center; }
    .pill-label { font-size:9px; letter-spacing:0.08em; text-transform:uppercase; color:var(--muted); }
    .pill-value { font-size:12px; font-weight:700; color:var(--text); }
    .pill.ok { border-color:#35d07f; box-shadow:0 0 10px rgba(53,208,127,0.28); }
    .pill.bad { border-color:#ff5b5b; box-shadow:0 0 10px rgba(255,91,91,0.24); }
    .top-grid { margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:16px; }
    .metric-link { color:inherit; text-decoration:none; display:block; }
    .metric { min-height:188px; border-radius:20px; padding:16px; background:var(--panel); border:1px solid var(--line); }
    .metric-label { color:var(--muted); font-size:14px; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:12px; }
    .metric-val { font-size:42px; font-weight:700; line-height:1; }
    .metric-sub { margin-top:10px; font-size:15px; color:var(--muted); }
    .metric.flow-green { border-color:#35d07f; box-shadow:0 0 10px rgba(53,208,127,0.95),0 0 20px rgba(53,208,127,0.65),0 0 34px rgba(53,208,127,0.35); }
    .metric.flow-red { border-color:#ff5b5b; box-shadow:0 0 10px rgba(255,91,91,0.95),0 0 20px rgba(255,91,91,0.65),0 0 34px rgba(255,91,91,0.35); }
    .settings-row { margin-top:16px; }
    .settings-button { display:flex; align-items:center; justify-content:center; gap:14px; min-height:98px; border-radius:16px; border:1px solid var(--line); background:linear-gradient(180deg, #7a7a7a, #676767); color:var(--text); text-decoration:none; font-size:26px; font-weight:700; }
    .msg { margin-bottom:14px; padding:10px 12px; border-radius:12px; background:var(--panel); border:1px solid var(--line); }
    @media (min-width: 901px) and (max-width: 1100px) and (max-height: 700px) {
      .wrap { padding:10px 12px 12px; }
      .panel { border-radius:16px; padding:12px; }
      h1 { font-size:32px; }
      .hero-datetime { font-size:15px; }
      .hero-pills { margin-top:10px; }
      .pill-grid { gap:5px; }
      .pill { min-height:38px; padding:5px 7px; border-radius:12px; }
      .pill-label { font-size:7px; }
      .pill-value { font-size:11px; }
      .top-grid { margin-top:10px; gap:10px; }
      .metric { min-height:120px; border-radius:16px; padding:10px; }
      .metric-label { margin-bottom:8px; font-size:12px; }
      .metric-val { font-size:30px; }
      .metric-sub { margin-top:6px; font-size:12px; }
      .settings-row { margin-top:10px; }
      .settings-button { min-height:68px; border-radius:14px; font-size:20px; }
      .msg { margin-bottom:10px; padding:10px 12px; border-radius:14px; font-size:15px; }
    }
    @media (max-width:900px) { .pill-grid,.top-grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    {% if msg and not hide_home_alerts %}<div class="msg">{{ msg }}</div>{% endif %}
    <div class="panel">
      <div class="title-row">
        <h1 id="headerTitle" class="{{ header_class }}">CDF - BORE HOLE</h1>
        <div id="dateTime" class="hero-datetime {{ header_class }}">{{ current_datetime }}</div>
      </div>
      <div class="hero-pills">
        <div class="pill-grid">
          <div id="alarmPill" class="pill {{ alarm_class }}"><span class="pill-label">Alarm</span><span class="pill-value" id="alarmValue">{{ alarm_short }}</span></div>
          <div id="officePill" class="pill {{ office_class }}"><span class="pill-label">Office Link</span><span class="pill-value" id="officeValue">{{ office_short }}</span></div>
          <div id="syncPill" class="pill {{ sync_class }}"><span class="pill-label">Office Sync</span><span class="pill-value" id="syncValue">{{ sync_short }}</span></div>
          <div id="picoPill" class="pill {{ pico_class }}"><span class="pill-label">Pico</span><span class="pill-value" id="picoValue">{{ pico_short }}</span></div>
          <div id="pushPill" class="pill {{ push_class }}"><span class="pill-label">Update</span><span class="pill-value" id="pushValue">{{ push_short }}</span></div>
          <div id="logPill" class="pill {{ log_class }}"><span class="pill-label">Logging</span><span class="pill-value" id="logValue">{{ log_short }}</span></div>
        </div>
      </div>
    </div>
    <div class="top-grid">
      <a class="metric-link" href="{{ url_for('water_settings_view') }}">
        <div id="waterTile" class="metric {{ water_glow }}">
          <div class="metric-label">Water L/PM</div>
          <div id="waterValue" class="metric-val">{{ water_lpm }}</div>
          <div class="metric-sub">Live water flow</div>
        </div>
      </a>
      <a class="metric-link" href="{{ url_for('water_history_view') }}">
        <div class="metric">
          <div class="metric-label">Water Yesterday 7am-7am</div>
          <div id="water7to7Value" class="metric-val">{{ water_7to7 }}</div>
          <div class="metric-sub">Litres</div>
        </div>
      </a>
    </div>
    <div class="settings-row">
      <a class="settings-button" href="{{ url_for('settings_view') }}"><span>&#9881;</span><span>Settings</span></a>
    </div>
  </div>
  <script>
    function setText(id, value) { const el=document.getElementById(id); if(el) el.textContent=value; }
    function setPillClass(id, cls) {
      const el=document.getElementById(id); if(!el) return;
      el.classList.remove('ok','bad'); el.classList.add(cls);
    }
    function setHeaderClass(cls) {
      ['headerTitle', 'dateTime'].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.remove('active', 'inactive');
        el.classList.add(cls);
      });
    }
    function render(data) {
      setText('dateTime', data.current_datetime || '--');
      setHeaderClass(data.header_class || 'inactive');
      setText('waterValue', data.water_lpm || '--');
      setText('water7to7Value', data.water_7to7 || '--');
      if (document.getElementById('alarmValue')) setText('alarmValue', data.alarm_short || '--');
      setText('officeValue', data.office_short || '--');
      setText('syncValue', data.sync_short || '--');
      setText('picoValue', data.pico_short || '--');
      setText('pushValue', data.push_short || '--');
      setText('logValue', data.log_short || '--');
      if (document.getElementById('alarmPill')) setPillClass('alarmPill', data.alarm_class);
      setPillClass('officePill', data.office_class);
      setPillClass('syncPill', data.sync_class);
      setPillClass('picoPill', data.pico_class);
      setPillClass('pushPill', data.push_class);
      setPillClass('logPill', data.log_class);
      const waterTile=document.getElementById('waterTile');
      if (waterTile) {
        waterTile.classList.remove('flow-green','flow-red');
        if (data.water_glow) waterTile.classList.add(data.water_glow);
      }
    }
    setInterval(async () => {
      try {
        const resp = await fetch('/api/home-state', {cache:'no-store'});
        if (!resp.ok) return;
        render(await resp.json());
      } catch (err) {}
    }, {{ refresh_seconds * 1000 }});
  </script>
</body>
</html>
"""


SETTINGS_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Bore Hole Settings</title>
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
  <style>
    :root {
      --bg:#5b5b5b;
      --panel:rgba(115,115,115,0.96);
      --panel-2:rgba(104,104,104,0.98);
      --line:#8a8a8a;
      --text:#ececec;
      --muted:#d2d2d2;
    }
    body {
      margin:0;
      color:var(--text);
      font-family:"Helvetica Neue", Helvetica, Arial, sans-serif;
      background:#5b5b5b;
    }
    .wrap {
      max-width:1024px;
      margin:0 auto;
      padding:18px;
    }
    .topbar {
      margin-bottom:16px;
    }
    .topbar a {
      color:var(--text);
      text-decoration:none;
      font-size:18px;
    }
    .grid {
      display:grid;
      grid-template-columns:1.05fr 0.95fr;
      gap:16px;
    }
    .panel {
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:20px;
      padding:18px;
    }
    h1 {
      margin:0 0 8px 0;
      font-size:38px;
    }
    .sub {
      color:var(--muted);
      margin-bottom:16px;
      font-size:18px;
    }
    .action-grid {
      display:grid;
      grid-template-columns:1fr;
      gap:12px;
    }
    .action-form {
      margin:0;
    }
    .button-link {
      display:block;
      min-height:74px;
      width:100%;
      border-radius:16px;
      border:1px solid #8a8a8a;
      background:linear-gradient(180deg, #7a7a7a, #676767);
      color:var(--text);
      font-size:20px;
      font-weight:700;
      text-decoration:none;
      text-align:center;
      line-height:74px;
      white-space:nowrap;
    }
    .button-icon {
      margin-right:10px;
    }
    .full-panel {
      margin-top:16px;
    }
    .detail-list {
      display:grid;
      gap:10px;
    }
    .detail {
      display:flex;
      justify-content:space-between;
      gap:12px;
      padding:12px 0;
      border-bottom:1px solid #818181;
      font-size:18px;
    }
    .detail:last-child {
      border-bottom:0;
    }
    .label {
      color:var(--muted);
    }
    .status-note {
      margin:12px 0 0;
      color:var(--muted);
      font-size:16px;
    }
    .status-note.is-busy {
      color:var(--text);
    }
    .msg {
      margin-bottom:16px;
      padding:12px 14px;
      border-radius:14px;
      border:1px solid #8a8a8a;
      background:rgba(115,115,115,0.96);
      font-size:18px;
    }
    .button-row {
      display:grid;
      grid-template-columns:1fr;
      gap:12px;
      margin-top:14px;
      max-width:560px;
      margin-left:auto;
      margin-right:auto;
    }
    .update-split {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:16px;
      margin-top:12px;
    }
    .update-box {
      background:var(--panel-2);
      border:1px solid var(--line);
      border-radius:16px;
      padding:16px;
    }
    .update-box h2 {
      margin:0 0 10px 0;
      font-size:24px;
    }
    .button-row form {
      width:100%;
      margin:0;
    }
    button {
      min-height:74px;
      width:100%;
      border-radius:16px;
      border:1px solid #8a8a8a;
      background:linear-gradient(180deg, #7a7a7a, #676767);
      color:var(--text);
      font-size:20px;
      font-weight:700;
      cursor:pointer;
    }
    button.secondary {
      background:linear-gradient(180deg, #737373, #626262);
    }
    @media (max-width:900px) {
      .grid {
        grid-template-columns:1fr;
      }
      .update-split {
        grid-template-columns:1fr;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    {% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
    <div class="topbar"><a href="{{ url_for('index') }}">← Back</a></div>
    <div class="grid">
      <div class="panel">
        <h1>Bore Hole Settings</h1>
        <div class="sub">Controller actions, alarms, logs, config, and water tools.</div>
        <div class="action-grid">
          <div class="detail"><span class="label">Current Mode</span><span>{{ current_mode }}</span></div>
          <a class="button-link" href="{{ url_for('water_settings_view') }}">Water Settings</a>
          <a class="button-link" href="{{ url_for('water_history_view') }}">Water History</a>
          <a class="button-link" href="{{ url_for('commissioning_view') }}">Commissioning</a>
          <a class="button-link" href="{{ url_for('alarms_view') }}">Alarms{% if alarm_count %} ({{ alarm_count }}){% endif %}</a>
          <a class="button-link" href="{{ url_for('events_view') }}">Event Log</a>
          <a class="button-link" href="{{ url_for('config_view') }}">Controller Config</a>
          <a class="button-link" href="{{ url_for('health_view') }}">Controller Health</a>
          <form class="action-form" method="post" action="{{ url_for('controller_reboot_view') }}" onsubmit="return confirm('Reboot this controller Pi now?');">
            <button class="secondary" type="submit"><span class="button-icon">↻</span>Reboot</button>
          </form>
          <form class="action-form" method="post" action="{{ url_for('controller_shutdown_view') }}" onsubmit="return confirm('Shut down this controller Pi now?');">
            <button class="secondary" type="submit"><span class="button-icon">⏻</span>Shutdown</button>
          </form>
        </div>
      </div>
      <div class="panel">
        <h1>Current State</h1>
        <div class="sub">Live controller summary moved off the home screen.</div>
        <div class="detail-list">
          <div class="detail"><span class="label">Water L/PM</span><span>{{ water_lpm }}</span></div>
          <div class="detail"><span class="label">Updated At</span><span>{{ last_sensor }}</span></div>
          <div class="detail"><span class="label">Sensor Age</span><span>{{ last_sensor_age }}</span></div>
          <div class="detail"><span class="label">Office Sync</span><span>{{ sync_short }}</span></div>
          <div class="detail"><span class="label">Pico</span><span>{{ pico_short }}</span></div>
          <div class="detail"><span class="label">Logging</span><span>{{ log_short }}</span></div>
        </div>
      </div>
    </div>
    <div class="panel full-panel">
      <h1 style="font-size:28px;">Software Update</h1>
      <div class="sub">Check the controller version against GitHub and apply a newer version when one is available.</div>
      <div class="update-split">
        <div class="update-box">
          <h2>Controller Update</h2>
          <div class="detail-list">
            <div class="detail"><span class="label">Branch</span><span id="controllerUpdateBranch">{{ update.branch }}</span></div>
            <div class="detail"><span class="label">Current Version</span><span id="controllerUpdateCurrent">{{ update.local_commit }}</span></div>
            <div class="detail"><span class="label">Latest Version</span><span id="controllerUpdateLatest">{{ update.remote_commit }}</span></div>
          </div>
          <div id="controllerUpdateStatus" class="status-note">{{ update.status }}</div>
          <div class="button-row">
            <form id="controllerUpdateCheckForm" method="post" action="{{ url_for('check_update_view') }}">
              <button id="controllerUpdateCheckButton" class="secondary" type="submit">Check for Update</button>
            </form>
            <form id="controllerUpdateApplyForm" method="post" action="{{ url_for('apply_update_view') }}" {% if not update.update_available %}style="display:none;"{% endif %}>
              <button type="submit">Update Now</button>
            </form>
          </div>
        </div>
        <div class="update-box">
          <h2>Pico Update</h2>
          <div class="detail-list">
            <div class="detail"><span class="label">Status</span><span>{{ pico_status }}</span></div>
            <div class="detail"><span class="label">Last Backup</span><span>{{ last_backup }}</span></div>
            <div class="detail"><span class="label">Backup Status</span><span>{{ last_backup_status }}</span></div>
          </div>
          <div class="button-row">
            <form method="post" action="{{ url_for('pico_update_view') }}">
              <button type="submit">Update Pico</button>
            </form>
            <form method="post" action="{{ url_for('pico_soft_reset_view') }}">
              <button type="submit" class="secondary">Soft Reset Pico</button>
            </form>
          </div>
        </div>
      </div>
      <div class="update-split" style="margin-top:16px;">
        <div class="update-box">
          <h2>Mode Lock</h2>
          <div class="detail-list">
            <div class="detail"><span class="label">Current Mode</span><span>{{ current_mode }}</span></div>
            <div class="detail"><span class="label">Next Mode</span><span>{{ next_mode_label }}</span></div>
          </div>
          <div class="status-note">A PIN is required before this controller can leave commissioning mode or return to it.</div>
          <div class="button-row">
            <form method="post" action="{{ url_for('switch_mode_view') }}">
              <input type="hidden" name="target_mode" value="{{ next_mode_key }}">
              <input type="number" name="mode_pin" inputmode="numeric" enterkeyhint="done" placeholder="Enter mode PIN" style="width:100%; min-height:64px; border-radius:14px; border:1px solid #8a8a8a; background:#686868; color:#ececec; font-size:22px; padding:10px 14px; box-sizing:border-box; margin-bottom:12px;">
              <button type="submit">{{ "Go Live" if next_mode_key == "live" else "Return to Commissioning" }}</button>
            </form>
          </div>
        </div>
        <div class="update-box">
          <h2>Backup</h2>
          <div class="button-row">
            <a class="button-link" href="{{ url_for('create_backup_view') }}">Create Backup Now</a>
            <a class="button-link" href="{{ url_for('download_backup_view') }}">Download Latest Backup</a>
          </div>
        </div>
        <div class="update-box">
          <h2>Office</h2>
          <div class="detail-list">
            <div class="detail"><span class="label">Office Link</span><span>{{ office_short }}</span></div>
            <div class="detail"><span class="label">Office Sync</span><span>{{ sync_short }}</span></div>
            <div class="detail"><span class="label">Alarm</span><span>{{ alarm_short }}</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <script>
  (function () {
    const form = document.getElementById('controllerUpdateCheckForm');
    if (!form) return;
    const button = document.getElementById('controllerUpdateCheckButton');
    const statusEl = document.getElementById('controllerUpdateStatus');
    const branchEl = document.getElementById('controllerUpdateBranch');
    const currentEl = document.getElementById('controllerUpdateCurrent');
    const latestEl = document.getElementById('controllerUpdateLatest');
    const applyForm = document.getElementById('controllerUpdateApplyForm');
    const defaultLabel = button.textContent;

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      button.disabled = true;
      button.textContent = 'Checking...';
      statusEl.textContent = 'Checking GitHub...';
      statusEl.classList.add('is-busy');
      try {
        const resp = await fetch(form.action, {
          method: 'POST',
          headers: {
            'X-Requested-With': 'fetch',
            'Accept': 'application/json'
          }
        });
        if (!resp.ok) throw new Error('Update check failed');
        const data = await resp.json();
        branchEl.textContent = data.branch || '--';
        currentEl.textContent = data.local_commit || '--';
        latestEl.textContent = data.remote_commit || '--';
        statusEl.textContent = data.status || '--';
        if (data.update_available) {
          applyForm.style.display = '';
        } else {
          applyForm.style.display = 'none';
        }
      } catch (err) {
        statusEl.textContent = 'Update check failed';
      } finally {
        statusEl.classList.remove('is-busy');
        button.disabled = false;
        button.textContent = defaultLabel;
      }
    });
  })();
  </script>
</body>
</html>
"""


SIMPLE_PAGE_HTML = """
<!doctype html><html><head><meta charset="utf-8"><title>{{ title }}</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>
body{margin:0;background:#5b5b5b;color:#ececec;font-family:Arial,sans-serif}.wrap{max-width:1100px;margin:0 auto;padding:18px}.panel{background:rgba(115,115,115,0.96);border:1px solid #8a8a8a;border-radius:20px;padding:18px}.topbar{margin-bottom:14px}.topbar a{color:#ececec;text-decoration:none}.detail{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid #818181}.detail:last-child{border-bottom:0}.label{color:#d2d2d2}.alarm{padding:10px 12px;border-radius:12px;border:1px solid rgba(255,119,119,0.35);background:rgba(84,34,34,0.38);margin-top:10px}.mono{font-family:ui-monospace, monospace; color:#d2d2d2; word-break:break-word}.button-link,button,input,textarea{border-radius:14px;border:1px solid #8a8a8a}.button-link,button{display:flex;align-items:center;justify-content:center;min-height:58px;width:100%;background:linear-gradient(180deg,#7a7a7a,#676767);color:#ececec;text-decoration:none;font-size:20px;font-weight:700;cursor:pointer}input{width:100%;box-sizing:border-box;min-height:58px;background:rgba(104,104,104,0.98);color:#ececec;font-size:20px;padding:12px 14px;margin-bottom:12px}table{width:100%;border-collapse:collapse}th,td{padding:10px 8px;border-bottom:1px solid #818181;text-align:left}th{color:#d2d2d2}
</style></head><body><div class="wrap"><div class="topbar"><a href="{{ back_url }}">← Back</a></div><div class="panel">{{ body|safe }}</div></div></body></html>
"""


WATER_SETTINGS_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Bore Hole Water Settings</title>
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
  <style>
    :root { --bg:#5b5b5b; --panel:rgba(115,115,115,0.96); --line:#8a8a8a; --text:#ececec; --muted:#d2d2d2; }
    body { margin:0; color:var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background:var(--bg); }
    .wrap { max-width:860px; margin:0 auto; padding:18px; }
    .topbar { margin-bottom:16px; }
    .topbar a { color:var(--text); text-decoration:none; font-size:18px; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:18px; margin-bottom:16px; }
    h1 { margin:0 0 8px 0; font-size:38px; }
    .sub { color:var(--muted); margin-bottom:16px; font-size:18px; }
    .current { font-size:34px; font-weight:700; }
    label { display:block; color:var(--muted); font-size:16px; margin-bottom:8px; }
    input[type="number"] { width:100%; min-height:72px; border-radius:16px; border:1px solid var(--line); background:#686868; color:var(--text); font-size:30px; padding:12px 16px; box-sizing:border-box; }
    button { min-height:72px; width:100%; border-radius:16px; border:1px solid #8a8a8a; background:linear-gradient(180deg, #7d7d7d, #696969); color:var(--text); font-size:22px; font-weight:700; padding:0 18px; cursor:pointer; margin-top:14px; }
    .hint { color:var(--muted); font-size:16px; margin-top:12px; }
    .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #818181; }
    .detail:last-child { border-bottom:0; }
    .label { color:var(--muted); }
    .grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    @media (max-width:900px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar"><a href="{{ url_for('index') }}">← Back</a></div>
    <div class="panel">
      <h1>Bore Hole Water</h1>
      <div class="sub">Adjust the low-flow alarm threshold and calibrate pulses per litre from the physical water meter.</div>
      <div class="current">Current: {{ current_value }} L/PM</div>
    </div>
    <div class="panel">
      <form method="post" action="{{ url_for('save_water_settings') }}">
        <label for="threshold_value">Low flow alarm threshold L/PM</label>
        <input id="threshold_value" name="threshold_value" type="number" min="0" step="0.01" value="{{ water_low_lpm }}" inputmode="decimal">
        <button type="submit">Save Water Threshold</button>
      </form>
      <div class="hint">Tile glow and low-flow alarm use this threshold.</div>
    </div>
    <div class="panel">
      <div class="detail"><span class="label">Pulses Per Litre</span><span>{{ water_pulses_per_litre }}</span></div>
      <div class="detail"><span class="label">Total Flow Pulses</span><span>{{ total_flow_pulses }}</span></div>
      <div class="detail"><span class="label">Calibration Status</span><span>{{ calibration_status }}</span></div>
      <div class="detail"><span class="label">Time Remaining</span><span>{{ calibration_remaining }}</span></div>
      <div class="detail"><span class="label">Pulse Count</span><span>{{ calibration_pulse_delta }}</span></div>
    </div>
    <div class="panel">
      <div class="sub">5 minute calibration</div>
      {% if calibration_can_start %}
      <form method="post" action="{{ url_for('start_water_calibration') }}">
        <button type="submit">Start 5 Minute Calibration</button>
      </form>
      {% elif calibration_active %}
      <form method="post" action="{{ url_for('cancel_water_calibration') }}">
        <button type="submit">Cancel Calibration</button>
      </form>
      {% endif %}
      <form method="post" action="{{ url_for('finish_water_calibration') }}">
        <div class="grid">
          <div>
            <label for="meter_litres">Physical meter litres</label>
            <input id="meter_litres" name="meter_litres" type="number" min="0.1" step="0.1" value="" inputmode="decimal">
          </div>
        </div>
        <button type="submit" {% if not calibration_ready %}disabled{% endif %}>Save New Pulses Per Litre</button>
      </form>
      <div class="hint">The calibration run stops automatically after 5 minutes. Enter the litres from the physical meter after the run completes.</div>
    </div>
  </div>
</body>
</html>
"""


BOREHOLE_COMMISSIONING_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Bore Hole Commissioning</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { margin:0; font-family:Arial,sans-serif; background:#5b5b5b; color:#ececec; }
    .wrap { max-width:1040px; margin:0 auto; padding:24px; }
    .topbar a { color:#ececec; text-decoration:none; }
    .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:16px; }
    .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:16px; }
    .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #818181; }
    .detail:last-child { border-bottom:0; }
    .label { color:#d2d2d2; }
    .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; word-break:break-all; }
    pre { background:#656565; border:1px solid #8a8a8a; border-radius:12px; padding:12px; white-space:pre-wrap; word-break:break-word; }
    @media (max-width:900px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar"><a href="{{ url_for('settings_view') }}">← Back to settings</a></div>
    <h1>Bore Hole Commissioning</h1>
    <div class="grid">
      <div class="panel">
        <div class="detail"><span class="label">Water L/PM</span><span>{{ water_lpm }}</span></div>
        <div class="detail"><span class="label">Flow Total Pulses</span><span>{{ flow_total_pulses }}</span></div>
        <div class="detail"><span class="label">Low Flow Threshold</span><span>{{ water_low_lpm }}</span></div>
        <div class="detail"><span class="label">Pulses Per Litre</span><span>{{ water_ppl }}</span></div>
        <div class="detail"><span class="label">Last Sensor</span><span>{{ last_sensor }} • {{ last_sensor_age }}</span></div>
        <div class="detail"><span class="label">Office Sync</span><span>{{ sync_short }}</span></div>
      </div>
      <div class="panel">
        <div class="detail"><span class="label">Controller Version</span><span class="mono">{{ app_version }}</span></div>
        <div class="detail"><span class="label">Pico Local</span><span class="mono">{{ pico_local }}</span></div>
        <div class="detail"><span class="label">Pico Deployed</span><span class="mono">{{ pico_deployed }}</span></div>
        <div class="detail"><span class="label">State Version</span><span>{{ state_version }}</span></div>
        <div class="detail"><span class="label">Alarm Count</span><span>{{ alarm_count }}</span></div>
      </div>
    </div>
    <div class="panel" style="margin-top:16px;">
      <h2>Raw Packet</h2>
      <pre>{{ raw_json }}</pre>
    </div>
  </div>
</body>
</html>
"""


HISTORY_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ metric_title }}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
  <style>
    :root { --bg:#5b5b5b; --panel:rgba(115,115,115,0.96); --line:#8a8a8a; --text:#ececec; --muted:#d2d2d2; }
    body { margin:0; color:var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background:var(--bg); }
    .wrap { max-width:1100px; margin:0 auto; padding:18px; }
    .topbar { margin-bottom:16px; }
    .topbar a { color:var(--text); text-decoration:none; font-size:18px; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:18px; margin-bottom:16px; }
    h1 { margin:0 0 8px 0; font-size:38px; }
    .sub { color:var(--muted); margin-bottom:16px; font-size:18px; }
    .chart-wrap { margin-top:10px; }
    .chart-box { position:relative; height:340px; }
    table { width:100%; border-collapse:collapse; }
    th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; }
    th { color:var(--muted); }
    .empty { color:var(--muted); font-size:18px; }
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
  <div class="wrap">
    <div class="topbar"><a href="{{ url_for('index') }}">← Back</a></div>
    <div class="panel">
      <h1>{{ metric_title }}</h1>
      <div class="sub">Recent hourly water history from the bore hole controller.</div>
      {% if rows %}
      <div class="chart-wrap">
        <div class="chart-box"><canvas id="historyChart"></canvas></div>
      </div>
      {% else %}
      <div class="empty">No hourly history available yet.</div>
      {% endif %}
    </div>
    <div class="panel">
      <h1 style="font-size:26px;">Hourly Table</h1>
      {% if rows %}
      <table>
        <thead><tr><th>Hour</th><th>{{ y_axis_title }}</th></tr></thead>
        <tbody>
          {% for row in rows %}
          <tr><td>{{ row.label }}</td><td>{{ row.value }}</td></tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div class="empty">No rows to display.</div>
      {% endif %}
    </div>
  </div>
  <script>
    const labels = {{ labels|tojson }};
    const values = {{ values|tojson }};
    const ctx = document.getElementById('historyChart');
    if (ctx) {
      new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [{
            label: {{ metric_title|tojson }},
            data: values,
            borderWidth: 2,
            pointRadius: 2,
            tension: 0.2,
            borderColor: {{ color|tojson }},
            backgroundColor: {{ color|tojson }}
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: { legend: { labels: { color: '#ececec' } } },
          scales: {
            x: { ticks: { color: '#d2d2d2' }, grid: { color: '#818181' } },
            y: { ticks: { color: '#d2d2d2' }, grid: { color: '#818181' } }
          }
        }
      });
    }
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    maybe_heartbeat_to_dashboard()
    ctx = home_context()
    ctx["hide_home_alerts"] = HIDE_HOME_ALERTS_DURING_SETUP and commissioning_mode_enabled(load_config())
    return render_template_string(HOME_HTML, msg=request.args.get("msg", ""), **ctx)


@app.route("/api/home-state")
def home_state_api():
    maybe_heartbeat_to_dashboard()
    return jsonify(home_context())


@app.route("/api/pico-ingest", methods=["POST"])
def pico_ingest_api():
    payload = request.get_json(silent=True) or {}

    def mutator(state):
        sensors = state.get("sensors", {})
        ts = int(payload.get("ts") or time.time())
        sensors["water_lpm"] = payload.get("water_lpm")
        sensors["flow_total_pulses"] = payload.get("total_flow_pulses")
        sensors["last_sensor_ts"] = ts
        sensors["device_status"] = "USB Connected"
        sensors["pico_connected"] = True
        sensors["raw"] = payload if isinstance(payload, dict) else {}
        sensors["controller_alarms"] = []
        state["sensors"] = sensors
        update_rollup_from_sample(state, payload.get("water_lpm"), payload.get("total_flow_pulses"), ts=ts)

    state = mutate_state(mutator)
    record_live_log(state.get("sensors", {}))
    push_current_state()
    return jsonify({"ok": True})


@app.route("/settings")
def settings_view():
    state = load_state()
    cfg = load_config()
    ctx = home_context()
    alarm_count = len(state.get("sensors", {}).get("controller_alarms", []))
    return render_template_string(
        SETTINGS_HTML,
        msg=request.args.get("msg", ""),
        update=check_for_update(),
        pico_status=state.get("last_pico_update_status", "Not run"),
        last_backup=fmt_ts(state.get("last_backup_ts")),
        last_backup_status=state.get("last_backup_status", "--"),
        alarm_count=alarm_count,
        water_lpm=ctx.get("water_lpm", "--"),
        last_sensor=fmt_ts(state.get("sensors", {}).get("last_sensor_ts")),
        last_sensor_age=fmt_age_seconds(state.get("sensors", {}).get("last_sensor_ts")),
        sync_short=ctx.get("sync_short", "--"),
        pico_short=ctx.get("pico_short", "--"),
        log_short=ctx.get("log_short", "--"),
        office_short=ctx.get("office_short", "--"),
        alarm_short=ctx.get("alarm_short", "--"),
        current_mode=current_mode_label(cfg),
        current_mode_key=cfg.get("deployment_mode", "commissioning"),
        next_mode_key="live" if commissioning_mode_enabled(cfg) else "commissioning",
        next_mode_label="Live" if commissioning_mode_enabled(cfg) else "Commissioning",
    )


@app.route("/commissioning")
def commissioning_view():
    state = load_state()
    sensors = state.get("sensors", {})
    cfg = load_config()
    ctx = home_context()
    return render_template_string(
        BOREHOLE_COMMISSIONING_HTML,
        water_lpm=fmt_value(sensors.get("water_lpm"), "f2"),
        flow_total_pulses=fmt_value(sensors.get("flow_total_pulses"), "i"),
        water_low_lpm=fmt_value(cfg.get("water_low_lpm", 0.1), "f2"),
        water_ppl=fmt_value(cfg.get("water_pulses_per_litre", 450.0), "f1"),
        last_sensor=fmt_ts(sensors.get("last_sensor_ts")),
        last_sensor_age=fmt_age_seconds(sensors.get("last_sensor_ts")),
        sync_short=ctx.get("sync_short", "--"),
        app_version=local_version_info().get("local_commit", "--"),
        pico_local=pico_firmware_hash(),
        pico_deployed=str(state.get("last_pico_deployed_hash", "") or "--"),
        state_version=state.get("state_version", 0),
        alarm_count=len(sensors.get("controller_alarms", [])),
        raw_json=json.dumps(sensors.get("raw", {}), indent=2, sort_keys=True),
    )


@app.route("/settings/water")
def water_settings_view():
    cfg = load_config()
    state = load_state()
    sensors = state.get("sensors", {})
    calib = state.get("water_calibration", {})
    now_ts = int(time.time())

    if isinstance(calib, dict) and calib.get("active"):
        try:
            end_ts = int(calib.get("end_ts"))
        except Exception:
            end_ts = None
        if end_ts is not None and now_ts >= end_ts:
            def mutator(state):
                calib_state = state.get("water_calibration", {})
                if not isinstance(calib_state, dict) or not calib_state.get("active"):
                    return
                calib_state["active"] = False
                calib_state["completed"] = True
                calib_state["latest_total_pulses"] = state.get("sensors", {}).get("flow_total_pulses")
                try:
                    start_total = int(calib_state.get("start_total_pulses"))
                    latest_total = int(calib_state.get("latest_total_pulses"))
                    calib_state["pulse_delta"] = max(0, latest_total - start_total)
                except Exception:
                    calib_state["pulse_delta"] = None
                state["water_calibration"] = calib_state
            state = mutate_state(mutator)
            calib = state.get("water_calibration", {})

    calibration_status = "Ready"
    calibration_remaining = "--"
    calibration_pulse_delta = "--"
    calibration_can_start = True
    calibration_active = False
    calibration_ready = False

    if isinstance(calib, dict):
        if calib.get("active"):
            calibration_status = "Running"
            calibration_active = True
            calibration_can_start = False
            try:
                remaining = max(0, int(calib.get("end_ts")) - now_ts)
                calibration_remaining = "%dm %02ds" % (remaining // 60, remaining % 60)
            except Exception:
                calibration_remaining = "--"
            try:
                start_total = int(calib.get("start_total_pulses"))
                latest_total = int(sensors.get("flow_total_pulses"))
                calibration_pulse_delta = fmt_value(max(0, latest_total - start_total), "i")
            except Exception:
                calibration_pulse_delta = "--"
        elif calib.get("completed"):
            calibration_status = "Complete"
            calibration_ready = True
            calibration_can_start = False
            calibration_remaining = "0m 00s"
            calibration_pulse_delta = fmt_value(calib.get("pulse_delta"), "i")

    return render_template_string(
        WATER_SETTINGS_HTML,
        current_value=fmt_value(sensors.get("water_lpm"), "f2"),
        water_low_lpm=fmt_value(cfg.get("water_low_lpm", 0.1), "f2"),
        water_pulses_per_litre=fmt_value(cfg.get("water_pulses_per_litre", 450.0), "f1"),
        total_flow_pulses=fmt_value(sensors.get("flow_total_pulses"), "i"),
        calibration_status=calibration_status,
        calibration_remaining=calibration_remaining,
        calibration_pulse_delta=calibration_pulse_delta,
        calibration_can_start=calibration_can_start,
        calibration_active=calibration_active,
        calibration_ready=calibration_ready,
    )


@app.route("/settings/water/save", methods=["POST"])
def save_water_settings():
    cfg = load_config()
    try:
        threshold_value = float(request.form.get("threshold_value", "").strip())
    except Exception:
        return redirect(url_for("water_settings_view"))
    cfg["water_low_lpm"] = threshold_value
    save_config(cfg)
    return redirect(url_for("water_settings_view"))


@app.route("/settings/water/calibration/start", methods=["POST"])
def start_water_calibration():
    state = load_state()
    sensors = state.get("sensors", {})
    try:
        total_pulses = int(sensors.get("flow_total_pulses"))
    except Exception:
        return redirect(url_for("water_settings_view"))

    def mutator(state):
        now_ts = int(time.time())
        state["water_calibration"] = {
            "active": True,
            "start_ts": now_ts,
            "end_ts": now_ts + (5 * 60),
            "start_total_pulses": total_pulses,
            "latest_total_pulses": total_pulses,
            "completed": False,
            "pulse_delta": None,
        }

    mutate_state(mutator)
    return redirect(url_for("water_settings_view"))


@app.route("/settings/water/calibration/cancel", methods=["POST"])
def cancel_water_calibration():
    def mutator(state):
        state["water_calibration"] = {
            "active": False,
            "start_ts": None,
            "end_ts": None,
            "start_total_pulses": None,
            "latest_total_pulses": None,
            "completed": False,
            "pulse_delta": None,
        }

    mutate_state(mutator)
    return redirect(url_for("water_settings_view"))


@app.route("/settings/water/calibration/finish", methods=["POST"])
def finish_water_calibration():
    try:
        meter_litres = float(request.form.get("meter_litres", "").strip())
        if meter_litres <= 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("water_settings_view"))

    state = load_state()
    calib = state.get("water_calibration", {})
    try:
        pulse_delta = int(calib.get("pulse_delta"))
    except Exception:
        pulse_delta = None
    if pulse_delta is None or pulse_delta <= 0:
        return redirect(url_for("water_settings_view"))

    cfg = load_config()
    cfg["water_pulses_per_litre"] = float(pulse_delta) / meter_litres
    save_config(cfg)

    def mutator(state):
        state["water_calibration"] = {
            "active": False,
            "start_ts": None,
            "end_ts": None,
            "start_total_pulses": None,
            "latest_total_pulses": None,
            "completed": False,
            "pulse_delta": None,
        }

    mutate_state(mutator)
    return redirect(url_for("water_settings_view"))


def render_metric_history(metric_title, y_axis_title, color, fmt):
    rows = get_hourly_history(max_points=168)
    view_rows = []
    labels = []
    values = []

    i = 0
    while i < len(rows):
        row = rows[i]
        raw_val = row.get("water")
        labels.append(row.get("label"))
        values.append(raw_val)
        view_rows.append({
            "label": row.get("label"),
            "value": fmt_value(raw_val, fmt),
        })
        i += 1

    return render_template_string(
        HISTORY_HTML,
        metric_title=metric_title,
        y_axis_title=y_axis_title,
        color=color,
        rows=view_rows,
        labels=labels,
        values=values,
    )


@app.route("/history/water")
def water_history_view():
    return render_metric_history("Water History", "Water L", "#4db6ff", "f1")


@app.route("/health")
def health_view():
    state = load_state()
    sensors = state.get("sensors", {})
    body = """
    <h1>Controller Health</h1>
    <div class="detail"><span class="label">IP Address</span><span>%s</span></div>
    <div class="detail"><span class="label">Dashboard URL</span><span>%s</span></div>
    <div class="detail"><span class="label">Last Sensor</span><span>%s</span></div>
    <div class="detail"><span class="label">Sensor Age</span><span>%s</span></div>
    <div class="detail"><span class="label">Last Backup</span><span>%s</span></div>
    <div class="detail"><span class="label">Backup Status</span><span>%s</span></div>
    <div class="detail"><span class="label">Office Link</span><span>%s</span></div>
    <div class="detail"><span class="label">Office Sync</span><span>%s</span></div>
    <div class="detail"><span class="label">Logging</span><span>%s</span></div>
    <div class="detail"><span class="label">Raw Status</span><span class="mono">%s</span></div>
    """ % (
        local_ip_address(),
        load_config().get("dashboard_url"),
        fmt_ts(sensors.get("last_sensor_ts")),
        fmt_age_seconds(sensors.get("last_sensor_ts")),
        fmt_ts(state.get("last_backup_ts")),
        state.get("last_backup_status", "--"),
        state.get("last_dashboard_status", "--"),
        state.get("last_sync_status", "--"),
        state.get("last_log_status", "--"),
        sensors.get("device_status", "--"),
    )
    return render_template_string(SIMPLE_PAGE_HTML, title="Health", back_url=url_for("settings_view"), body=body)


@app.route("/config")
def config_view():
    cfg = load_config()
    body = """
    <h1>Controller Config</h1>
    <form method="post" action="%s">
      <label>Office Dashboard URL</label>
      <input type="text" name="dashboard_url" value="%s">
      <div class="detail"><span class="label">This Device IP</span><span>%s</span></div>
      <label>Refresh Seconds</label>
      <input type="number" name="touch_refresh_seconds" min="1" step="1" value="%s">
      <label>Low Flow Alarm Threshold LPM</label>
      <input type="number" name="water_low_lpm" min="0" step="0.01" value="%s">
      <label>Pulses Per Litre</label>
      <input type="number" name="water_pulses_per_litre" min="1" step="0.1" value="%s">
      <button type="submit">Save Config</button>
    </form>
    """ % (
        url_for("save_config_view"),
        cfg.get("dashboard_url", ""),
        host_ipv4_display(),
        cfg.get("touch_refresh_seconds", 1),
        cfg.get("water_low_lpm", 0.1),
        cfg.get("water_pulses_per_litre", 450.0),
    )
    return render_template_string(SIMPLE_PAGE_HTML, title="Config", back_url=url_for("settings_view"), body=body)


@app.route("/config/save", methods=["POST"])
def save_config_view():
    cfg = load_config()
    cfg["dashboard_url"] = str(request.form.get("dashboard_url", cfg["dashboard_url"]) or "").strip().rstrip("/")
    try:
        cfg["touch_refresh_seconds"] = max(1, int(request.form.get("touch_refresh_seconds", cfg["touch_refresh_seconds"])))
    except Exception:
        pass
    try:
        cfg["water_low_lpm"] = float(request.form.get("water_low_lpm", cfg["water_low_lpm"]))
    except Exception:
        pass
    try:
        cfg["water_pulses_per_litre"] = float(request.form.get("water_pulses_per_litre", cfg["water_pulses_per_litre"]))
    except Exception:
        pass
    save_config(cfg)
    return redirect(url_for("settings_view", msg="Config saved"))


@app.route("/alarms")
def alarms_view():
    rows = load_state().get("sensors", {}).get("controller_alarms", [])
    body = "<h1>Alarms</h1>"
    if not rows:
        body += "<div class='detail'><span class='label'>Status</span><span>No active alarms</span></div>"
    else:
        for row in rows:
            body += "<div class='alarm'>%s</div>" % row.get("message", "Alarm")
    return render_template_string(SIMPLE_PAGE_HTML, title="Alarms", back_url=url_for("settings_view"), body=body)


@app.route("/events")
def events_view():
    rows = get_events(250)
    body = "<h1>Event Log</h1><table><thead><tr><th>Time</th><th>Event</th><th>Message</th><th>Detail</th></tr></thead><tbody>"
    for row in rows:
        body += "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            row.get("ts_label", "--"), row.get("event_type", ""), row.get("message", ""), row.get("detail", "")
        )
    body += "</tbody></table>"
    return render_template_string(SIMPLE_PAGE_HTML, title="Events", back_url=url_for("settings_view"), body=body)


@app.route("/backup/create")
def create_backup_view():
    create_backup_zip("manual")
    return redirect(url_for("settings_view", msg="Backup created"))


@app.route("/backup/latest")
def download_backup_view():
    auth_error = require_office_token()
    if auth_error:
        return auth_error
    rows = list_backup_files()
    if not rows:
        path = create_backup_zip("manual")
    else:
        path = rows[0]
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.route("/settings/update/check", methods=["POST"])
def check_update_view():
    status = check_for_update()
    wants_json = "application/json" in str(request.headers.get("Accept", "")).lower() or request.headers.get("X-Requested-With") == "fetch"
    if wants_json:
      return jsonify(status)
    return redirect(url_for("settings_view", msg=status.get("status", "Checked")))


@app.route("/settings/update/apply", methods=["POST"])
def apply_update_view():
    ok, msg = apply_update()
    if not ok:
        return redirect(url_for("settings_view", msg=msg if msg else "Update failed"))
    restart_self_delayed(1.0)
    return render_template_string(
        """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Updating Controller</title>
  <meta http-equiv="refresh" content="6; url={{ url_for('settings_view') }}">
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
  <style>
    body { margin:0; background:#5b5b5b; color:#ececec; font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; }
    .wrap { max-width:760px; margin:0 auto; padding:32px 18px; }
    .panel { background:rgba(115,115,115,0.96); border:1px solid #8a8a8a; border-radius:20px; padding:24px; }
    h1 { margin:0 0 12px 0; font-size:34px; }
    .sub { color:#d2d2d2; font-size:18px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <h1>Updating Controller</h1>
      <div class="sub">The latest code has been pulled. This controller is restarting now and will return to settings automatically.</div>
    </div>
  </div>
</body>
</html>
        """
    )


@app.route("/settings/pico/update", methods=["POST"])
def pico_update_view():
    path = os.path.join(APP_ROOT, "pico_firmware", "main.py")
    mpremote = mpremote_command()
    try:
        proc = subprocess.run(
            mpremote + ["connect", "auto", "fs", "cp", path, ":main.py"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0:
            local_hash = pico_firmware_hash()
            mutate_state(lambda state: state.update({"last_pico_update_status": "Pico update OK", "last_pico_deployed_hash": local_hash}))
            return redirect(url_for("settings_view", msg="Pico update OK"))
        msg = proc.stderr.strip() or proc.stdout.strip() or "Pico update failed"
    except Exception as exc:
        msg = str(exc)
    mutate_state(lambda state: state.update({"last_pico_update_status": msg}))
    return redirect(url_for("settings_view", msg=msg))


@app.route("/settings/pico/soft-reset", methods=["POST"])
def pico_soft_reset_view():
    mpremote = mpremote_command()
    try:
        proc = subprocess.run(
            mpremote + ["connect", "auto", "soft-reset"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            msg = "Pico soft reset OK"
            mutate_state(lambda state: state.update({"last_pico_update_status": msg}))
            return redirect(url_for("settings_view", msg=msg))
        msg = proc.stderr.strip() or proc.stdout.strip() or "Pico soft reset failed"
    except Exception as exc:
        msg = str(exc)
    mutate_state(lambda state: state.update({"last_pico_update_status": msg}))
    return redirect(url_for("settings_view", msg=msg))


@app.route("/settings/mode/switch", methods=["POST"])
def switch_mode_view():
    cfg = load_config()
    target_mode = str(request.form.get("target_mode", "") or "").strip().lower()
    entered_pin = str(request.form.get("mode_pin", "") or "").strip()
    expected_pin = str(cfg.get("mode_switch_pin", DEFAULT_CONFIG["mode_switch_pin"]) or DEFAULT_CONFIG["mode_switch_pin"]).strip()

    if target_mode not in ["commissioning", "live"]:
        return redirect(url_for("settings_view", msg="Invalid mode selection"))
    if not entered_pin or entered_pin != expected_pin:
        return redirect(url_for("settings_view", msg="Mode switch PIN incorrect"))

    cfg["deployment_mode"] = target_mode
    cfg["commissioning_mode"] = target_mode == "commissioning"
    save_config(cfg)
    return redirect(url_for("settings_view", msg="Controller switched to %s mode" % current_mode_label(cfg)))


@app.route("/settings/system/reboot", methods=["POST"])
def controller_reboot_view():
    ok, detail = run_system_action("reboot")
    if not ok:
        return redirect(url_for("settings_view", msg="Reboot failed: %s" % detail))
    record_event("system", "Controller reboot requested", "User initiated reboot from settings")
    return render_template_string(
        SIMPLE_PAGE_HTML,
        title="Rebooting",
        back_url=url_for("settings_view"),
        body="""
        <h1>↻ Rebooting Controller</h1>
        <div class="detail"><span class="label">Status</span><span>Restarting now</span></div>
        <p class="small">This Pi is restarting now. The bore hole screen should return automatically after boot.</p>
        """,
    )


@app.route("/settings/system/shutdown", methods=["POST"])
def controller_shutdown_view():
    ok, detail = run_system_action("shutdown")
    if not ok:
        return redirect(url_for("settings_view", msg="Shutdown failed: %s" % detail))
    record_event("system", "Controller shutdown requested", "User initiated shutdown from settings")
    return render_template_string(
        SIMPLE_PAGE_HTML,
        title="Shutting Down",
        back_url=url_for("settings_view"),
        body="""
        <h1>⏻ Shutting Down Controller</h1>
        <div class="detail"><span class="label">Status</span><span>Powering down now</span></div>
        <p class="small">Wait for the screen to go dark before disconnecting power.</p>
        """,
    )


if __name__ == "__main__":
    ensure_data_dir()
    if not os.path.exists(os.path.join(DATA_DIR, "controller_config.json")):
        save_config(dict(DEFAULT_CONFIG))
    if not os.path.exists(os.path.join(DATA_DIR, "controller_state.json")):
        save_state(default_state())
    threading.Thread(target=backup_worker, daemon=True).start()
    threading.Thread(target=background_sync_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(load_config().get("listen_port", 8092)))
