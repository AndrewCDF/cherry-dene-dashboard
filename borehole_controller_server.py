from flask import Flask, Response, jsonify, redirect, render_template_string, request, send_file, url_for
from markupsafe import Markup, escape
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
    "farm_id": "",
    "farm_name": "",
    "dashboard_url": "http://127.0.0.1:8090",
    "sync_token": "",
    "deployment_mode": "commissioning",
    "commissioning_mode": True,
    "mode_switch_pin": "1234",
    "listen_port": 8092,
    "touch_refresh_seconds": 1,
    "water_low_lpm": 0.1,
    "water_pulses_per_litre": 450.0,
    "backup_keep": 6,
    "shelly_host": "",
    "supply_fuse_amps": 100,
    "controller_phase": "",
}
PHASE_LOST_VOLTS = 100   # a phase reading below this has lost its supply (a blown fuse reads near 0 V)
PHASE_COLOURS = ["#8b5a2b", "#1f2933", "#8a96a3"]   # L1 brown, L2 black, L3 grey (UK wiring colours)
POWER_MINUTES_FILE = "power_minutes.ndjson"
POWER_MINUTES_KEEP = 8 * 24 * 60
# Shelly 3EM on the farm's three-phase incoming supply, read over the network.
SHELLY_POLL_SECONDS = 5
SHELLY_STALE_SECONDS = 60
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
STOCKSENSE_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CDF_APP_ICON_PATH = os.path.join(STOCKSENSE_ICON_DIR, "stocksense-icon-180.png")
FAVICON_PNG_PATH = os.path.join(STOCKSENSE_ICON_DIR, "stocksense-icon-64.png")


TOUCH_OPTIMIZE_HEAD = (
    '<link rel="icon" type="image/png" href="/favicon.png">'
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-title" content="StockSense">'
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
@app.route("/favicon.png")
@app.route("/favicon.svg")
def favicon_view():
    return send_file(FAVICON_PNG_PATH, mimetype="image/png", max_age=300)


@app.route("/apple-touch-icon.png")
@app.route("/apple-touch-icon-precomposed.png")
def apple_touch_icon_view():
    return send_file(CDF_APP_ICON_PATH, mimetype="image/png", max_age=300)


# Shared StockSense theme (static/stocksense-theme.css), linked after each page's own styles.
THEME_HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Semi+Condensed:wght@500;600;700&display=swap">'
    '<link id="cdf-theme" rel="stylesheet" href="/static/stocksense-theme.css?v=1">'
)


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
            if "</head>" in body and 'cdf-theme' not in body:
                body = body.replace("</head>", THEME_HEAD + "</head>", 1)
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


def power_alarms(state, cfg):
    """Supply alarms from the Shelly: a phase that has lost its voltage, or the Shelly going
    silent (it is powered from one phase too). These stay on during commissioning: a lost
    phase is real whatever mode the controller is in."""
    if not str(cfg.get("shelly_host", "") or "").strip():
        return []
    power = state.get("power") if isinstance(state.get("power"), dict) else {}
    try:
        age = int(time.time()) - int(power.get("ts")) if power.get("ts") else None
    except Exception:
        age = None
    if age is None or age > SHELLY_STALE_SECONDS:
        return [{"alarm_key": "shelly_silent",
                 "message": "Supply meter (Shelly) not responding. Check its phase has power."}]
    alarms = []
    for i, ph in enumerate((power.get("phases") or [])[:3]):
        v = _num(ph.get("v")) if isinstance(ph, dict) else None
        if v is not None and v < PHASE_LOST_VOLTS:
            alarms.append({"alarm_key": "phase_lost_l%d" % (i + 1),
                           "message": "L%d supply lost (%d V). Check the L%d fuse." % (i + 1, round(v), i + 1)})
    return alarms


def build_controller_alarms(state, cfg=None):
    cfg = cfg or load_config()
    supply = power_alarms(state, cfg)
    if commissioning_mode_enabled(cfg):
        return supply
    return supply + water_alarms(state, cfg)


def water_alarms(state, cfg):
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
    if dt_obj.hour < 6:
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


BACKUP_KEEP_ALL_HOURS = 24
BACKUP_KEEP_DAILY_DAYS = 14
BACKUP_KEEP_WEEKLY_WEEKS = 8
BACKUP_KEEP_MANUAL = 10
BACKUP_KEEP_NEWEST = 6
BACKUP_RETENTION_TEXT = "Hourly for 24 hours, then one a day for 14 days, then one a week for 8 weeks"


def backup_is_healthy(path):
    # A backup only counts as good if the zip opens cleanly and every JSON file in it parses.
    try:
        with zipfile.ZipFile(path) as zf:
            if zf.testzip() is not None:
                return False
            for name in zf.namelist():
                if name.endswith(".json"):
                    json.loads(zf.read(name).decode("utf-8") or "null")
        return True
    except Exception:
        return False


def backups_to_keep(paths, now_ts=None):
    # Layered retention: everything from the last 24 hours, the newest backup of each day
    # for 14 days, the newest of each week for 8 weeks, and the newest 10 manual backups.
    # Suspect (failed check) backups never count as a day's or week's keeper. The newest 6
    # good automatic backups are always kept, however old, so a Pi that has been switched
    # off for months doesn't lose them all on its first backup back.
    now_ts = int(now_ts or time.time())
    rows = []
    for path in paths:
        try:
            rows.append((int(os.path.getmtime(path)), path))
        except Exception:
            continue
    rows.sort(reverse=True)
    keep = set()
    days_seen = set()
    weeks_seen = set()
    manual_kept = 0
    newest_kept = 0
    for ts, path in rows:
        name = os.path.basename(path)
        age = now_ts - ts
        if "manual" in name:
            if manual_kept < BACKUP_KEEP_MANUAL:
                keep.add(path)
                manual_kept += 1
            continue
        if age <= BACKUP_KEEP_ALL_HOURS * 3600:
            keep.add(path)
            if "suspect" not in name:
                newest_kept += 1
            continue
        if "suspect" in name:
            continue
        if newest_kept < BACKUP_KEEP_NEWEST:
            newest_kept += 1
            keep.add(path)
            continue
        dt_obj = datetime.fromtimestamp(ts)
        day_key = dt_obj.strftime("%Y-%m-%d")
        week_key = dt_obj.strftime("%G-W%V")
        if age <= BACKUP_KEEP_DAILY_DAYS * 86400:
            if day_key not in days_seen:
                days_seen.add(day_key)
                keep.add(path)
            continue
        if age <= BACKUP_KEEP_WEEKLY_WEEKS * 7 * 86400 and week_key not in weeks_seen:
            weeks_seen.add(week_key)
            keep.add(path)
    return keep


def prune_backups_layered(paths, newest_path=None):
    # Never delete anything when the backup just made failed its check: an overnight
    # corruption must not push the last good copies out.
    if newest_path is not None and not backup_is_healthy(newest_path):
        return False
    keep = backups_to_keep(paths)
    for path in paths:
        if path not in keep:
            try:
                os.remove(path)
            except Exception:
                pass
    return True


def mark_backup_suspect_if_bad(path):
    # Renames a backup that fails its check to *_suspect.zip and returns the new path.
    if backup_is_healthy(path):
        return path, True
    suspect = path[:-4] + "_suspect.zip"
    try:
        os.replace(path, suspect)
        return suspect, False
    except Exception:
        return path, False


def prune_backup_files(newest_path=None):
    prune_backups_layered(list_backup_files(), newest_path=newest_path)


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
    path, healthy = mark_backup_suspect_if_bad(path)
    if healthy:
        prune_backup_files()
    mutate_state(lambda state: state.update({
        "last_backup_ts": int(time.time()),
        "last_backup_status": ("Backup OK: %s" if healthy else "Backup failed check, older backups kept: %s") % os.path.basename(path),
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
    power = power_summary(state)
    sent_minutes = []
    if power:
        payload["power"] = power["raw"]
        sent_minutes = list(state.get("power_unsent") or [])
        payload["power"]["minutes"] = sent_minutes
    ok, msg = push_to_dashboard_payload(payload, state)
    if ok and sent_minutes:
        sent_ts = set(r.get("ts") for r in sent_minutes)
        mutate_state(lambda s: s.update({"power_unsent": [r for r in (s.get("power_unsent") or []) if r.get("ts") not in sent_ts]}))
    return ok, msg


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


def _shelly_get(host, path):
    with urllib.request.urlopen("http://%s%s" % (host, path), timeout=4) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _num(value):
    try:
        return float(value) if value not in [None, ""] else None
    except Exception:
        return None


def read_shelly_3em(host):
    """One reading from a Shelly 3EM: the original 3EM (Gen1, /status) or the Pro 3EM /
    3EM Gen3 (/rpc/EM.GetStatus). Returns per-phase volts, amps, watts and power factor,
    total watts, and the meter's total energy in kWh."""
    try:
        em = _shelly_get(host, "/rpc/EM.GetStatus?id=0")
    except Exception:
        em = None
    if isinstance(em, dict) and "total_act_power" in em:
        phases = [{"v": _num(em.get(p + "_voltage")), "a": _num(em.get(p + "_current")),
                   "w": _num(em.get(p + "_act_power")), "pf": _num(em.get(p + "_pf"))} for p in ["a", "b", "c"]]
        total_kwh = None
        try:
            data = _shelly_get(host, "/rpc/EMData.GetStatus?id=0")
            wh = _num(data.get("total_act"))
            total_kwh = wh / 1000.0 if wh is not None else None
        except Exception:
            pass
        return {"phases": phases, "total_w": _num(em.get("total_act_power")), "total_kwh": total_kwh, "model": "Pro 3EM"}
    status = _shelly_get(host, "/status")
    meters = status.get("emeters") if isinstance(status, dict) else None
    if not isinstance(meters, list) or len(meters) < 3:
        raise ValueError("Not a Shelly 3EM")
    phases = [{"v": _num(m.get("voltage")), "a": _num(m.get("current")), "w": _num(m.get("power")), "pf": _num(m.get("pf"))} for m in meters[:3]]
    totals = [_num(m.get("total")) for m in meters[:3]]
    return {
        "phases": phases,
        "total_w": _num(status.get("total_power")) if status.get("total_power") is not None else sum(p["w"] or 0 for p in phases),
        "total_kwh": (sum(totals) / 1000.0) if all(t is not None for t in totals) else None,
        "model": "3EM",
    }


def poll_shelly_once():
    host = str(load_config().get("shelly_host", "") or "").strip()
    if not host:
        return
    host = host.replace("http://", "").replace("https://", "").strip("/")
    try:
        reading = read_shelly_3em(host)
        reading["ts"] = int(time.time())
        error = ""
    except Exception as exc:
        reading = None
        error = str(exc)

    finished_minutes = []

    def mutator(state):
        power = state.get("power") if isinstance(state.get("power"), dict) else {}
        if reading is None:
            power["error"] = error
            power["error_ts"] = int(time.time())
        else:
            power.update(reading)
            power["error"] = ""
            amps = [_num(ph.get("a")) for ph in reading.get("phases", [])][:3]
            # Highest amps on each phase today (fuses blow on the peaks).
            today_key = datetime.now().strftime("%Y-%m-%d")
            peak = power.get("peak_today") if isinstance(power.get("peak_today"), dict) else {}
            if peak.get("date") != today_key:
                peak = {"date": today_key, "a": [None, None, None], "at": [None, None, None]}
            for i, a in enumerate(amps):
                if a is not None and (peak["a"][i] is None or a > peak["a"][i]):
                    peak["a"][i] = a
                    peak["at"][i] = reading["ts"]
            power["peak_today"] = peak
            # Each minute's highest and average amps per phase, for the phase chart and the office.
            minute = reading["ts"] // 60
            bucket = power.get("minute") if isinstance(power.get("minute"), dict) else {}
            if bucket.get("m") != minute:
                if bucket.get("m") and bucket.get("n"):
                    rec = {"ts": bucket["m"] * 60,
                           "max_a": [round(x, 2) if x is not None else None for x in bucket["max"]],
                           "avg_a": [round(t / bucket["n"], 2) for t in bucket["sum"]]}
                    finished_minutes.append(rec)
                    unsent = state.get("power_unsent") if isinstance(state.get("power_unsent"), list) else []
                    state["power_unsent"] = (unsent + [rec])[-180:]
                bucket = {"m": minute, "max": [None, None, None], "sum": [0.0, 0.0, 0.0], "n": 0}
            for i, a in enumerate(amps):
                if a is not None:
                    bucket["max"][i] = a if bucket["max"][i] is None else max(bucket["max"][i], a)
                    bucket["sum"][i] += a
            bucket["n"] += 1
            power["minute"] = bucket
            # Today's use runs midnight to midnight from the meter's running total.
            today = datetime.now().strftime("%Y-%m-%d")
            if reading.get("total_kwh") is not None:
                day = power.get("day") if isinstance(power.get("day"), dict) else {}
                if day.get("date") != today:
                    if day.get("date") and day.get("start_kwh") is not None:
                        power["yesterday_kwh"] = round(reading["total_kwh"] - day["start_kwh"], 2)
                    day = {"date": today, "start_kwh": reading["total_kwh"]}
                power["day"] = day
                power["today_kwh"] = round(reading["total_kwh"] - day["start_kwh"], 2)
        state["power"] = power
    mutate_state(mutator)
    for rec in finished_minutes:
        append_named_json_line(POWER_MINUTES_FILE, rec)
    if finished_minutes and finished_minutes[-1]["ts"] % 3600 == 0:
        trim_power_minutes()


def trim_power_minutes():
    rows = read_all_json_lines(POWER_MINUTES_FILE)
    if len(rows) > POWER_MINUTES_KEEP:
        path = os.path.join(DATA_DIR, POWER_MINUTES_FILE)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            for rec in rows[-POWER_MINUTES_KEEP:]:
                f.write(json.dumps(rec) + "\n")
        os.replace(tmp, path)


def phase_chart_series(rows, hours, fuse_amps=0):
    """Line chart data for the last `hours`: each phase's highest amps per time slot."""
    now = int(time.time())
    slot = 300 if hours <= 24 else 1800
    if hours <= 6:
        slot = 60
    start = (now - hours * 3600) // slot * slot
    count = (now - start) // slot + 1
    peaks = [[None] * count for _ in range(3)]
    for rec in rows:
        try:
            idx = (int(rec["ts"]) - start) // slot
        except Exception:
            continue
        if 0 <= idx < count:
            for p in range(3):
                v = (rec.get("max_a") or [None, None, None])[p]
                if v is not None and (peaks[p][idx] is None or v > peaks[p][idx]):
                    peaks[p][idx] = v
    fmt = "%a %H:%M" if hours > 24 else "%H:%M"
    labels = [datetime.fromtimestamp(start + i * slot).strftime(fmt) for i in range(count)]
    series = [("L%d" % (p + 1), PHASE_COLOURS[p], peaks[p]) for p in range(3)]
    if fuse_amps:
        series.append(("Fuse %d A" % fuse_amps, "#d64545", [float(fuse_amps)] * count, True))
    return labels, series


def shelly_loop():
    while True:
        try:
            poll_shelly_once()
        except Exception:
            pass
        time.sleep(SHELLY_POLL_SECONDS)


def power_summary(state, cfg=None):
    """The incoming supply for the screen and the office, or None when no Shelly is set."""
    cfg = cfg or load_config()
    if not str(cfg.get("shelly_host", "") or "").strip():
        return None
    power = state.get("power") if isinstance(state.get("power"), dict) else {}
    try:
        age = int(time.time()) - int(power.get("ts")) if power.get("ts") else None
    except Exception:
        age = None
    live = age is not None and age <= SHELLY_STALE_SECONDS
    phases = power.get("phases") if isinstance(power.get("phases"), list) else []
    try:
        fuse = float(cfg.get("supply_fuse_amps") or 0)
    except Exception:
        fuse = 0.0
    peak = power.get("peak_today") if isinstance(power.get("peak_today"), dict) else {}
    if peak.get("date") != datetime.now().strftime("%Y-%m-%d"):
        peak = {}
    rows = []
    for i, name in enumerate(["L1", "L2", "L3"]):
        ph = phases[i] if i < len(phases) and isinstance(phases[i], dict) else {}
        w = _num(ph.get("w"))
        a = _num(ph.get("a")) if live else None
        peak_a = (peak.get("a") or [None, None, None])[i] if peak else None
        peak_at = (peak.get("at") or [None, None, None])[i] if peak else None
        rows.append({
            "name": name,
            "colour": PHASE_COLOURS[i],
            "v": fmt_value(ph.get("v"), "f0") if live else "--",
            "a": fmt_value(a, "f1"),
            "kw": fmt_value(w / 1000.0 if w is not None else None, "f2") if live else "--",
            "peak_a": fmt_value(peak_a, "f1"),
            "peak_at": datetime.fromtimestamp(peak_at).strftime("%H:%M") if peak_at else "",
            # Over 90% of the fuse rating shows red.
            "hot": bool(fuse and a is not None and a >= 0.9 * fuse),
        })
    total_w = _num(power.get("total_w"))
    return {
        "live": live,
        "status": "Live" if live else ("No reading" + (" (%s)" % power.get("error") if power.get("error") else "")),
        "total_kw": fmt_value(total_w / 1000.0 if (live and total_w is not None) else None, "f2"),
        "today_kwh": fmt_value(power.get("today_kwh"), "f1"),
        "yesterday_kwh": fmt_value(power.get("yesterday_kwh"), "f1"),
        "phases": rows,
        "fuse_amps": int(fuse) if fuse else 0,
        "ts": power.get("ts"),
        # Raw numbers for the office.
        "raw": {
            "total_w": total_w if live else None,
            "today_kwh": power.get("today_kwh"),
            "yesterday_kwh": power.get("yesterday_kwh"),
            "phases": [{k: _num(p.get(k)) for k in ["v", "a", "w", "pf"]} for p in phases if isinstance(p, dict)] if live else [],
            "peak_today": peak or None,
            "fuse_amps": int(fuse) if fuse else 0,
            "controller_phase": str(cfg.get("controller_phase", "") or ""),
            "ts": power.get("ts"),
        },
    }


def line_chart_svg(labels, series, unit="", height=280):
    """A simple line graph as inline SVG (no chart library, so it works on the shed screens
    and old TV browsers). series: [(name, colour, values[, dashed])], values line up with labels and may
    hold None for a missing day (the line joins the days either side)."""
    width, left, right, top, bottom = 1000, 52, 34, 34, 34
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [v for item in series for v in item[2] if v is not None]
    n = len(labels)
    if not values or n == 0:
        return Markup('<div class="chart-empty">No readings yet.</div>')
    lo, hi = min(values), max(values)
    if hi - lo < 4:
        mid = (hi + lo) / 2.0
        lo, hi = mid - 2, mid + 2
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    # A round step (1, 2, 5, 10, 20, 25, 50...) giving about five grid lines.
    rough = (hi - lo) / 5.0
    step = 1
    for nice in [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]:
        step = nice
        if nice >= rough:
            break
    first_tick = int(lo // step + 1) * step

    def x_of(i):
        return left + (plot_w / 2.0 if n == 1 else plot_w * i / float(n - 1))

    def y_of(v):
        return top + plot_h * (1 - (v - lo) / float(hi - lo))

    parts = ['<svg class="line-chart" viewBox="0 0 %d %d" role="img">' % (width, height)]
    tick = first_tick
    while tick < hi:
        y = y_of(tick)
        parts.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#dbe3ec" stroke-width="1"/>' % (left, width - right, y, y))
        parts.append('<text x="%d" y="%.1f" text-anchor="end" font-size="13" fill="#4a6078">%s%s</text>' % (left - 8, y + 4, tick, unit))
        tick += step
    every = max(1, int(round(n / 10.0)))
    for i, label in enumerate(labels):
        if i % every == 0 or i == n - 1:
            parts.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="13" fill="#4a6078">%s</text>' % (x_of(i), height - 10, escape(label)))
    lx = left
    for item in series:
        name, colour, vals = item[0], item[1], item[2]
        dashed = len(item) > 3 and item[3]
        dash = ' stroke-dasharray="8 6"' if dashed else ""
        parts.append('<line x1="%d" x2="%d" y1="10" y2="10" stroke="%s" stroke-width="4"%s/><text x="%d" y="15" font-size="14" font-weight="600" fill="#0d2b4a">%s</text>' % (lx, lx + 16, colour, ' stroke-dasharray="5 3"' if dashed else "", lx + 22, escape(name)))
        lx += 36 + 8 * len(name)
        run = ["%.1f,%.1f" % (x_of(i), y_of(v)) for i, v in enumerate(vals) if v is not None]
        if len(run) > 1:
            parts.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round" stroke-linecap="round"%s/>' % (" ".join(run), colour, "2" if dashed else "3", dash))
        for i, v in enumerate(vals):
            if v is not None and not dashed and n <= 60:
                parts.append('<circle cx="%.1f" cy="%.1f" r="3.5" fill="%s"/>' % (x_of(i), y_of(v), colour))
    parts.append("</svg>")
    return Markup("".join(parts))


# Page look shared with the shed controllers (their ENTRY_PAGE_HEAD).
PAGE_HEAD = """
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <meta name="cdf-theme-native" content="1">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Semi+Condensed:wght@500;600&display=swap">
    <style>
        :root {
            --page: #eef2f6; --card: #ffffff; --card-2: #f5f8fb; --rule: #d5dde6; --track: #dbe3ec;
            --navy: #0b3a6b; --text: #0d2b4a; --muted: #4a6078; --soft: #31475e;
            --green: #2f9e3a; --amber: #f08a12; --red: #d64545;
        }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { margin: 0; min-height: 100vh; background: var(--page); color: var(--text); font-family: "Barlow", "Helvetica Neue", Helvetica, sans-serif; }
        .cond { font-family: "Barlow Semi Condensed", "Barlow", "Helvetica Neue", Helvetica, sans-serif; }
        .topbar { min-height: 64px; background: #ffffff; padding: 10px 28px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--rule); }
        .back { display: flex; align-items: center; justify-content: center; min-height: 48px; padding: 0 16px; border-radius: 12px; border: 1px solid #c5d0dc; background: var(--card); color: var(--text); text-decoration: none; font-size: 17px; font-weight: 600; white-space: nowrap; }
        .title { margin-left: 6px; font-size: 34px; font-weight: 600; color: var(--navy); }
        .brand-logo { height: 44px; width: auto; display: block; margin-left: auto; }
        .wrap { max-width: 1200px; margin: 0 auto; padding: 16px 24px 24px; }
        .msg { margin-bottom: 14px; padding: 12px 16px; border-radius: 12px; background: #e3f4e1; border: 1px solid #9fd39a; color: #1e6b16; font-size: 17px; font-weight: 600; }
        .msg.error { background: #fdecec; border-color: #e3a0a0; color: #8f1f1f; }
        .section-title { margin: 0 0 8px 4px; font-size: 14px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
        section + section { margin-top: 20px; }
        .card { border-radius: 14px; background: var(--card); padding: 18px; }
        .hint { font-size: 15px; color: var(--muted); line-height: 1.35; }
        .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
        .stat { border-radius: 14px; background: var(--card); padding: 14px 18px; }
        .stat-label { font-size: 14px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
        .stat-value { margin-top: 2px; font-size: 32px; font-weight: 600; color: var(--navy); line-height: 1.1; }
        .stat-sub { font-size: 14px; color: var(--muted); }
        .pill { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; font-size: 14px; font-weight: 600; background: var(--card-2); color: var(--muted); }
        .pill::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
        .pill.on { background: #e3f4e1; color: #1e6b16; } .pill.on::before { background: var(--green); }
        .pill.wait { background: #fff4e5; color: #9a4b00; } .pill.wait::before { background: var(--amber); }
        .pill.bad { background: #fdecec; color: #8f1f1f; } .pill.bad::before { background: var(--red); }
        label.field { display: block; font-size: 14px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; margin: 0 0 6px 2px; }
        input[type="number"], input[type="text"], select {
            width: 100%; min-height: 60px; padding: 0 16px; border-radius: 12px; border: 1px solid #c5d0dc;
            background: var(--card-2); color: var(--text); font-family: inherit; font-size: 22px; font-weight: 600;
        }
        input[type="text"], select { font-size: 19px; font-weight: 500; }
        input:focus, select:focus { outline: none; border-color: var(--navy); background: #ffffff; }
        button {
            width: 100%; min-height: 60px; border-radius: 12px; border: 1px solid #c5d0dc; background: var(--card-2);
            color: var(--text); font-family: inherit; font-size: 18px; font-weight: 600; cursor: pointer; white-space: nowrap;
        }
        button:active { background: var(--track); }
        button:disabled { opacity: 0.4; cursor: default; }
        button.primary { background: var(--navy); color: #ffffff; border-color: var(--navy); }
        button.primary:active { background: var(--text); }
        button.go { background: var(--green); color: #ffffff; border-color: var(--green); }
        button.danger { background: #fdecec; border-color: #e3a0a0; color: #8f1f1f; }
        form { margin: 0; }
        .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
        .col { display: flex; flex-direction: column; gap: 20px; }
        .col > section + section { margin-top: 0; }
        .card.form { display: grid; gap: 12px; }
        .now { display: flex; align-items: baseline; gap: 8px; }
        .now b { font-size: 56px; font-weight: 600; color: var(--navy); line-height: 1; }
        .now span { font-size: 22px; color: var(--muted); font-weight: 600; }
        .now.ok b { color: var(--green); } .now.warn b { color: var(--amber); } .now.alarm b { color: var(--red); }
        .details { margin-top: 10px; }
        .detail { display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-top: 1px solid var(--track); font-size: 17px; }
        .detail > span:first-child { color: var(--muted); }
        .detail > span:last-child { font-weight: 600; text-align: right; }
        .inline { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: end; }
        .inline button { width: auto; min-width: 150px; padding: 0 22px; }
        .link-item { display: flex; align-items: center; justify-content: space-between; min-height: 54px; padding: 0 18px; border-radius: 14px; background: var(--card); color: var(--text); text-decoration: none; font-size: 18px; font-weight: 500; }
        .link-item span:last-child { color: var(--muted); font-size: 22px; }
        .table-wrap { overflow: auto; border-radius: 12px; border: 1px solid var(--track); }
        table { width: 100%; border-collapse: collapse; font-size: 15px; }
        th, td { padding: 9px 10px; border-top: 1px solid var(--track); text-align: left; vertical-align: top; }
        thead th { border-top: 0; background: var(--card-2); font-size: 13px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
        a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible { outline: 3px solid var(--navy); outline-offset: 2px; }
        @media (max-width: 860px) {
            .topbar { padding: 10px 16px; }
            .title { font-size: 26px; }
            .brand-logo { display: none; }
            .wrap { padding: 14px 16px 20px; }
            .stats { grid-template-columns: 1fr 1fr; }
            .cols { grid-template-columns: 1fr; }
        }
        .list { border-radius: 14px; background: var(--card); overflow: hidden; }
        .item { display: flex; align-items: center; gap: 12px; min-height: 50px; padding: 0 18px; color: var(--text); text-decoration: none; font-size: 18px; font-weight: 500; border-top: 1px solid var(--track); }
        .item:first-child { border-top: 0; }
        .item:active { background: var(--card-2); }
        .item-sub { margin-left: auto; font-size: 15px; color: var(--muted); }
        .chev { color: var(--muted); font-size: 22px; line-height: 1; }
        .badge { margin-left: auto; min-width: 26px; padding: 2px 8px; border-radius: 999px; background: var(--red); color: #ffffff; font-size: 14px; font-weight: 600; text-align: center; }
        .card.stack { display: flex; flex-direction: column; gap: 12px; }
        .row { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; font-size: 16px; }
        .row-label { color: var(--muted); }
        .status { font-size: 18px; font-weight: 600; }
        .status.is-busy { color: var(--amber); }
        .btns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .mode-chip { padding: 4px 12px; border-radius: 999px; font-size: 15px; font-weight: 600; color: #ffffff; background: var(--amber); }
        .mode-chip.live { background: var(--green); }
        details summary { cursor: pointer; color: var(--muted); font-size: 15px; min-height: 32px; display: flex; align-items: center; }
        details .row { margin-top: 6px; font-size: 15px; }
        .mono { font-family: ui-monospace, Menlo, monospace; font-size: 14px; word-break: break-all; }
        .ok-text { color: #1e6b16; } .bad-text { color: #8f1f1f; }
    </style>
"""


POWER_HISTORY_HTML = """
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Phase load</title>
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<style>
  body { margin:0; background:#eef2f6; color:#0d2b4a; font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; }
  .wrap { max-width:1100px; margin:0 auto; padding:14px 18px; }
  .top { display:flex; align-items:center; gap:12px; margin-bottom:12px; flex-wrap:wrap; }
  .top a { display:inline-flex; align-items:center; min-height:44px; padding:0 16px; border-radius:12px; border:1px solid #c5d0dc; background:#fff; color:#0d2b4a; text-decoration:none; font-weight:700; }
  .top a.on { background:#0b3a6b; color:#fff; border-color:#0b3a6b; }
  h1 { margin:0 8px 0 4px; font-size:28px; }
  .card { background:#fff; border-radius:14px; padding:14px 18px; margin-bottom:12px; }
  .line-chart { display:block; width:100%; height:auto; }
  .chart-empty { padding:30px 0; text-align:center; color:#4a6078; }
  .peaks { display:grid; grid-template-columns:repeat(3, 1fr); gap:10px; }
  .peaks div { border-radius:12px; background:#f5f8fb; padding:8px 12px; font-size:15px; color:#4a6078; }
  .peaks b { font-size:24px; color:#0d2b4a; }
  .hint { font-size:14px; color:#4a6078; }
</style></head><body><div class="wrap">
  <div class="top">
    <a href="{{ url_for('index') }}">← Back</a>
    <h1>Phase load</h1>
    {% for h in [6, 24, 168] %}<a class="{{ 'on' if h == hours else '' }}" href="{{ url_for('power_history_view', hours=h) }}">{{ '7 days' if h == 168 else (h|string ~ ' hours') }}</a>{% endfor %}
  </div>
  <div class="card">
    <div class="peaks">
      {% for ph in phases %}<div style="border-top:5px solid {{ ph.colour }}">{{ ph.name }} now <b>{{ ph.a }}</b> A<br>Peak today {{ ph.peak_a }} A {{ ph.peak_at }}</div>{% endfor %}
    </div>
  </div>
  <div class="card">
    <div class="hint" style="margin-bottom:6px">Highest amps on each phase{% if hours <= 6 %} each minute{% elif hours <= 24 %} in each 5 minutes{% else %} in each half hour{% endif %}.{% if fuse_amps %} Red dashed line is the {{ fuse_amps }} A fuse.{% endif %}</div>
    {{ chart }}
  </div>
</div></body></html>
"""


@app.route("/history/power")
def power_history_view():
    try:
        hours = int(request.args.get("hours", 24))
    except Exception:
        hours = 24
    hours = hours if hours in [6, 24, 168] else 24
    cfg = load_config()
    summary = power_summary(load_state(), cfg) or {"phases": [], "fuse_amps": 0}
    rows = read_all_json_lines(POWER_MINUTES_FILE)
    labels, series = phase_chart_series(rows, hours, summary.get("fuse_amps", 0))
    return render_template_string(
        POWER_HISTORY_HTML, hours=hours, phases=summary["phases"], fuse_amps=summary.get("fuse_amps", 0),
        chart=line_chart_svg(labels, series, unit=" A", height=340),
    )


def require_office_token():
    expected = str(load_config().get("sync_token", "") or "").strip()
    if not expected:
        return None
    provided = str(request.headers.get("X-Controller-Token", "") or "").strip()
    if provided != expected:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    return None


def water_week_total():
    # The last 7 completed 6am-to-6am days, from this controller's own hourly log.
    days = get_daily_history(max_days=7)
    if not days:
        return "--"
    return fmt_value(sum(float(d.get("water") or 0) for d in days), "f0")


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
        "clock_hm": datetime.now().strftime("%H:%M"),
        "clock_date": "%s %d %s" % (datetime.now().strftime("%a"), datetime.now().day, datetime.now().strftime("%b")),
        "water_week": water_week_total(),
        "alarm_count": len(alarms),
        "power": power_summary(state, cfg),
    }


HOME_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Water &amp; Power</title>
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
  <meta name="cdf-theme-native" content="1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Semi+Condensed:wght@500;600;700&display=swap">
  <style>
    :root { --page:#eef2f6; --card:#ffffff; --card-2:#f5f8fb; --rule:#d5dde6; --text:#0d2b4a; --muted:#4a6078; --soft:#31475e; --navy:#0b3a6b;
            --green:#2f9e3a; --amber:#f08a12; --red:#d64545; }
    * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
    body { margin:0; min-height:100vh; background:var(--page); color:var(--text); font-family:"Barlow","Helvetica Neue",Helvetica,sans-serif; }
    .cond { font-family:"Barlow Semi Condensed","Barlow","Helvetica Neue",Helvetica,sans-serif; }
    .page { display:flex; flex-direction:column; min-height:100vh; }
    /* Header: the same as the shed controllers. */
    .topbar { min-height:76px; padding:10px 28px; display:flex; align-items:center; gap:18px; border-bottom:1px solid var(--rule); background:#ffffff; flex-wrap:nowrap; }
    .brand-logo { height:48px; width:auto; display:block; }
    .hdr-div { flex:0 0 3px; width:3px; height:48px; background:#7f93a9; }
    .name-box { flex:1 1 auto; display:flex; align-items:center; justify-content:center; align-self:stretch; padding:0 18px; border-radius:12px; border:2px solid var(--rule);
                font-size:30px; font-weight:600; white-space:nowrap; transition:border-color .4s, box-shadow .4s; }
    .name-box.active { border-color:#2f9e3a; box-shadow:0 0 6px rgba(47,158,58,0.5), 0 0 14px rgba(47,158,58,0.25); }
    .name-box.inactive { border-color:#d64545; box-shadow:0 0 6px rgba(214,69,69,0.5), 0 0 14px rgba(214,69,69,0.25); }
    .hdr-when { display:flex; align-items:baseline; gap:12px; white-space:nowrap; }
    .hdr-date { font-size:20px; font-weight:600; }
    .clock { font-size:38px; font-weight:700; color:var(--navy); line-height:1; }
    .msg { margin:12px 24px 0; padding:10px 14px; border-radius:12px; background:var(--card); border:1px solid var(--rule); font-weight:600; }
    /* Water on the left, power on the right. */
    .split { flex:1; padding:14px 24px 12px; display:grid; grid-template-columns:1fr 1fr; gap:16px; min-height:0; }
    .split.no-power { grid-template-columns:1fr; }
    .col { display:flex; flex-direction:column; gap:8px; min-width:0; }
    .col-title { font-size:14px; letter-spacing:0.08em; text-transform:uppercase; font-weight:700; color:var(--muted); margin-left:4px; }
    .tile { flex:1; display:flex; flex-direction:column; gap:8px; border-radius:16px; padding:14px 18px; background:var(--card); border:2px solid var(--rule); color:var(--text); text-decoration:none; transition:border-color .3s, box-shadow .3s; }
    .tile.flow-green { border-color:#2f9e3a; box-shadow:0 0 8px rgba(47,158,58,0.6), 0 0 18px rgba(47,158,58,0.3); }
    .tile.flow-red { border-color:#d64545; box-shadow:0 0 8px rgba(214,69,69,0.6), 0 0 18px rgba(214,69,69,0.3); }
    .tile-label { font-size:15px; color:var(--soft); }
    .label-row { display:flex; justify-content:space-between; gap:10px; }
    .label-row span:last-child { color:var(--muted); }
    .big { font-size:52px; font-weight:600; line-height:1; white-space:nowrap; }
    .big small { font-size:22px; color:var(--muted); font-weight:500; }
    .rows { display:flex; flex-direction:column; }
    /* The big figures sit centred in the space between the tile label and the totals below. */
    .mid { margin:auto 0; } .mid-top { margin-top:auto; } .mid-bottom { margin-bottom:auto; }
    .row { display:flex; justify-content:space-between; align-items:baseline; padding:6px 0; border-top:1px solid #dbe3ec; font-size:16px; }
    .row span:first-child { color:var(--muted); }
    .row b { font-size:24px; font-weight:600; }
    .row b small { font-size:15px; color:var(--muted); font-weight:500; }
    .tile-sub { font-size:14px; color:var(--muted); }
    .phase-grid { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:8px; }
    .phase-grid.bottom { margin-top:0; }
    .phase { border-radius:12px; border:1px solid var(--rule); background:var(--card-2); padding:6px 10px; font-size:14px; color:var(--muted); line-height:1.25; }
    .phase-name { font-size:13px; letter-spacing:0.08em; text-transform:uppercase; font-weight:700; color:var(--navy); }
    .phase-amps b { font-size:26px; font-weight:600; color:var(--text); }
    .phase.hot { background:#fdecec; border-color:#d64545; }
    .phase.hot .phase-amps b { color:#c62828; }
    /* Bottom buttons, like the shed controllers. */
    .nav { padding:0 24px 16px; display:flex; gap:12px; }
    .nav a { flex:1 1 0; min-height:56px; display:flex; align-items:center; justify-content:center; gap:8px; border:1px solid #c5d0dc; border-radius:12px;
             background:var(--card); color:var(--text); font-size:18px; font-weight:500; text-decoration:none; }
    .nav a.alarm-on { background:var(--red); border-color:var(--red); color:#ffffff; font-weight:600; }
    .nav-badge { min-width:24px; padding:1px 7px; border-radius:999px; background:var(--red); color:#ffffff; font-size:14px; font-weight:600; text-align:center; }
    .nav a.alarm-on .nav-badge { background:#ffffff; color:var(--red); }
    @media (max-width:900px) { .split { grid-template-columns:1fr; } .topbar { flex-wrap:wrap; } .hdr-div { display:none; } }
  </style>
</head>
<body>
<div class="page">
  <header class="topbar">
    <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
    <span class="hdr-div" aria-hidden="true"></span>
    <div class="name-box cond {{ header_class }}" id="nameBox">Water &amp; Power</div>
    <span class="hdr-div" aria-hidden="true"></span>
    <div class="hdr-when"><span class="hdr-date" id="clockDate">{{ clock_date }}</span><span class="clock cond" id="clockValue">{{ clock_hm }}</span></div>
  </header>
  {% if msg and not hide_home_alerts %}<div class="msg">{{ msg }}</div>{% endif %}

  <main class="split{{ ' no-power' if not power else '' }}">
    <section class="col" aria-label="Water">
      <div class="col-title">Water</div>
      <a class="tile {{ water_glow }}" id="waterTile" href="{{ url_for('water_history_view') }}">
        <div class="tile-label">Water now</div>
        <div class="big cond mid"><span id="waterValue">{{ water_lpm }}</span> <small>L/min</small></div>
        <div class="rows">
          <div class="row"><span>Yesterday 6am to 6am</span><b class="cond"><span id="water7to7Value">{{ water_7to7 }}</span> <small>L</small></b></div>
          <div class="row"><span>Last 7 days</span><b class="cond"><span id="waterWeekValue">{{ water_week }}</span> <small>L</small></b></div>
        </div>
        <div class="tile-sub">Tap for water history</div>
      </a>
    </section>
    {% if power %}
    <section class="col" aria-label="Power">
      <div class="col-title">Power</div>
      <a class="tile {{ 'flow-green' if power.live else 'flow-red' }}" id="powerTile" href="{{ url_for('power_history_view') }}">
        <div class="tile-label label-row"><span>Incoming supply</span><span><span id="powerStatus">{{ power.status }}</span>{% if power.fuse_amps %} · {{ power.fuse_amps }} A fuse{% endif %}</span></div>
        <div class="big cond mid"><span id="powerTotal">{{ power.total_kw }}</span> <small>kW</small></div>
        <div class="rows">
          <div class="row"><span>Today since midnight</span><b class="cond"><span id="powerToday">{{ power.today_kwh }}</span> <small>kWh</small></b></div>
          <div class="row"><span>Yesterday</span><b class="cond"><span id="powerYesterday">{{ power.yesterday_kwh }}</span> <small>kWh</small></b></div>
        </div>
        <div class="phase-grid bottom">
          {% for ph in power.phases %}
          <div class="phase {{ 'hot' if ph.hot else '' }}" id="ph{{ loop.index0 }}box" style="border-top: 5px solid {{ ph.colour }}">
            <div class="phase-name">{{ ph.name }}</div>
            <div class="phase-amps"><b class="cond" id="ph{{ loop.index0 }}a">{{ ph.a }}</b> A</div>
            <div><span id="ph{{ loop.index0 }}v">{{ ph.v }}</span> V · <span id="ph{{ loop.index0 }}kw">{{ ph.kw }}</span> kW</div>
            <div>Peak <b id="ph{{ loop.index0 }}peak">{{ ph.peak_a }}</b> A <span id="ph{{ loop.index0 }}peakat">{{ ph.peak_at }}</span></div>
          </div>
          {% endfor %}
        </div>
        <div class="tile-sub">Tap for the phase chart</div>
      </a>
    </section>
    {% endif %}
  </main>

  <nav class="nav" aria-label="Pages">
    <a href="{{ url_for('alarms_view') }}" id="alarmNav" class="{{ 'alarm-on' if alarm_count else '' }}">Alarms <span class="nav-badge" id="alarmBadge" {% if not alarm_count %}style="display:none"{% endif %}>{{ alarm_count }}</span></a>
    <a href="{{ url_for('settings_view') }}">Settings</a>
  </nav>
</div>
<script>
  function setText(id, value) { const el = document.getElementById(id); if (el) el.textContent = (value === undefined || value === null) ? '--' : value; }
  function render(d) {
    setText('clockValue', d.clock_hm); setText('clockDate', d.clock_date);
    const nb = document.getElementById('nameBox');
    if (nb) { nb.classList.remove('active', 'inactive'); nb.classList.add(d.header_class || 'inactive'); }
    setText('waterValue', d.water_lpm); setText('water7to7Value', d.water_7to7); setText('waterWeekValue', d.water_week);
    const wt = document.getElementById('waterTile');
    if (wt) { wt.classList.remove('flow-green', 'flow-red'); if (d.water_glow) wt.classList.add(d.water_glow); }
    if (d.power) {
      setText('powerTotal', d.power.total_kw); setText('powerStatus', d.power.status);
      setText('powerToday', d.power.today_kwh); setText('powerYesterday', d.power.yesterday_kwh);
      (d.power.phases || []).forEach((ph, i) => {
        setText('ph' + i + 'v', ph.v); setText('ph' + i + 'a', ph.a); setText('ph' + i + 'kw', ph.kw);
        setText('ph' + i + 'peak', ph.peak_a); setText('ph' + i + 'peakat', ph.peak_at);
        const box = document.getElementById('ph' + i + 'box'); if (box) box.classList.toggle('hot', !!ph.hot);
      });
      const pt = document.getElementById('powerTile');
      if (pt) { pt.classList.remove('flow-green', 'flow-red'); pt.classList.add(d.power.live ? 'flow-green' : 'flow-red'); }
    }
    const badge = document.getElementById('alarmBadge');
    if (badge) { badge.style.display = d.alarm_count ? '' : 'none'; badge.textContent = d.alarm_count; }
    const an = document.getElementById('alarmNav'); if (an) an.classList.toggle('alarm-on', !!d.alarm_count);
  }
  // The flow figure is sized so 100.00 L/min would just fill the water tile's width;
  // the supply kW figure uses the same size so the two columns match.
  function fitBigFigures() {
    const tile = document.getElementById('waterTile');
    const big = tile && tile.querySelector('.big');
    if (!big) return;
    const probe = big.cloneNode(true);
    probe.removeAttribute('id');
    probe.querySelectorAll('[id]').forEach((el) => el.removeAttribute('id'));
    probe.firstElementChild.textContent = '100.00';
    probe.style.cssText = 'position:absolute; visibility:hidden; white-space:nowrap; font-size:100px; width:auto;';
    probe.querySelector('small').style.fontSize = '42px';
    tile.appendChild(probe);
    const width100 = probe.getBoundingClientRect().width;
    tile.removeChild(probe);
    const cs = getComputedStyle(tile);
    const room = tile.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    if (!width100 || room <= 0) return;
    let size = Math.min(160, 100 * room / width100);
    const apply = () => document.querySelectorAll('.big').forEach((el) => {
      el.style.fontSize = size + 'px';
      const small = el.querySelector('small'); if (small) small.style.fontSize = (size * 0.42) + 'px';
    });
    apply();
    // Never let the page scroll: on a short screen, step the figures down until it fits.
    while (size > 40 && document.documentElement.scrollHeight > window.innerHeight) { size -= 4; apply(); }
  }
  fitBigFigures();
  window.addEventListener('resize', fitBigFigures);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitBigFigures);

  setInterval(async () => {
    try {
      const resp = await fetch('/api/home-state', {cache: 'no-store'});
      if (resp.ok) render(await resp.json());
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
    <title>Water &amp; Power Settings</title>
""" + PAGE_HEAD + """
</head>
<body>
    <header class="topbar">
        <a class="back" href="{{ url_for('index') }}">← Back</a>
        <a class="back" href="{{ url_for('index') }}">⌂ Overview</a>
        <div class="title cond">Settings</div>
        <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
    </header>

    <div class="wrap">
        {% if msg %}<div class="msg auto-dismiss">{{ msg }}</div>{% endif %}
        <div class="cols">
            <div class="col">
                <section>
                    <h2 class="section-title">Water</h2>
                    <nav class="list" aria-label="Water">
                        <a class="item" href="{{ url_for('water_settings_view') }}"><span>Water meter</span><span class="item-sub">{{ water_lpm }} L/min</span><span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('water_history_view') }}"><span>Water history</span><span class="chev" style="margin-left: auto">›</span></a>
                    </nav>
                </section>
                <section>
                    <h2 class="section-title">Power</h2>
                    <nav class="list" aria-label="Power">
                        <a class="item" href="{{ url_for('power_history_view') }}"><span>Phase chart</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('config_view') }}"><span>Shelly and fuse</span><span class="item-sub">In Config</span><span class="chev">›</span></a>
                    </nav>
                </section>
                <section>
                    <h2 class="section-title">Controller</h2>
                    <nav class="list" aria-label="Controller tools">
                        <a class="item" href="{{ url_for('alarms_view') }}"><span>Alarms</span>{% if alarm_count %}<span class="badge">{{ alarm_count }}</span>{% else %}<span class="item-sub">None active</span>{% endif %}<span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('health_view') }}"><span>Health</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('events_view') }}"><span>Event log</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('config_view') }}"><span>Config</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('commissioning_view') }}"><span>Commissioning</span><span class="chev" style="margin-left: auto">›</span></a>
                    </nav>
                </section>
                <section>
                    <h2 class="section-title">Status</h2>
                    <div class="card">
                        <div class="detail" style="border-top: 0"><span>Alarm</span><span>{{ alarm_short }}</span></div>
                        <div class="detail"><span>Office link</span><span>{{ office_short }}</span></div>
                        <div class="detail"><span>Office sync</span><span>{{ sync_short }}</span></div>
                        <div class="detail"><span>Office update</span><span>{{ push_short }}</span></div>
                        <div class="detail"><span>Pico</span><span>{{ pico_short }}</span></div>
                        <div class="detail"><span>Logging</span><span>{{ log_short }}</span></div>
                        <div class="detail"><span>Last reading</span><span>{{ last_sensor }} ({{ last_sensor_age }})</span></div>
                    </div>
                </section>
            </div>

            <div class="col">
                <section>
                    <h2 class="section-title">Software</h2>
                    <div class="card stack">
                        <div class="row"><span class="status" id="controllerUpdateStatus">{{ update.status }}</span></div>
                        <div class="btns">
                            <form id="controllerUpdateCheckForm" method="post" action="{{ url_for('check_update_view') }}">
                                <button id="controllerUpdateCheckButton" type="submit">Check for update</button>
                            </form>
                            <form id="controllerUpdateApplyForm" method="post" action="{{ url_for('apply_update_view') }}" {% if not update.update_available %}style="display:none;"{% endif %}>
                                <button class="primary" type="submit">Install update</button>
                            </form>
                        </div>
                        <details>
                            <summary>Version details</summary>
                            <div class="row"><span class="row-label">Branch</span><span class="mono" id="controllerUpdateBranch">{{ update.branch }}</span></div>
                            <div class="row"><span class="row-label">Installed</span><span class="mono" id="controllerUpdateCurrent">{{ update.local_commit }}</span></div>
                            <div class="row"><span class="row-label">Latest</span><span class="mono" id="controllerUpdateLatest">{{ update.remote_commit }}</span></div>
                        </details>
                        <div class="row"><span class="row-label">Pico firmware</span><span>{{ pico_status }}</span></div>
                        <div class="btns">
                            <form method="post" action="{{ url_for('pico_update_view') }}"><button type="submit">Update Pico</button></form>
                            <form method="post" action="{{ url_for('pico_soft_reset_view') }}"><button type="submit">Soft reset Pico</button></form>
                        </div>
                    </div>
                </section>

                <section>
                    <h2 class="section-title">Mode</h2>
                    <div class="card stack">
                        <div class="row"><span class="row-label">Current mode</span><span class="mode-chip {% if current_mode_key == 'live' %}live{% endif %}">{{ current_mode }}</span></div>
                        <div class="hint">Use commissioning while wiring and proving sensors. Go live once it's ready for normal alarms. Switching needs the mode PIN.</div>
                        <form method="post" action="{{ url_for('switch_mode_view') }}" class="btns">
                            <input type="hidden" name="target_mode" value="{{ next_mode_key }}">
                            <input type="number" name="mode_pin" inputmode="numeric" enterkeyhint="done" placeholder="Mode PIN" aria-label="Mode PIN">
                            <button type="submit">{{ "Go live" if next_mode_key == "live" else "Back to commissioning" }}</button>
                        </form>
                    </div>
                </section>

                <section>
                    <h2 class="section-title">Backups</h2>
                    <div class="card stack">
                        <div class="row"><span class="row-label">Last backup</span><span>{{ last_backup }}</span></div>
                        <div class="row"><span class="row-label">Status</span><span>{{ last_backup_status }}</span></div>
                        <div class="btns">
                            <form method="get" action="{{ url_for('create_backup_view') }}"><button type="submit">Create backup now</button></form>
                            <form method="get" action="{{ url_for('download_backup_view') }}"><button type="submit">Download latest</button></form>
                        </div>
                    </div>
                </section>

                <section>
                    <h2 class="section-title">Power</h2>
                    <div class="card">
                        <div class="btns">
                            <form method="post" action="{{ url_for('controller_reboot_view') }}" onsubmit="return confirm('Reboot this controller Pi now?');">
                                <button type="submit">↻ Reboot</button>
                            </form>
                            <form method="post" action="{{ url_for('controller_shutdown_view') }}" onsubmit="return confirm('Shut down this controller Pi now? It will need power cycling to start again.');">
                                <button class="danger" type="submit">⏻ Shut down</button>
                            </form>
                        </div>
                    </div>
                </section>
            </div>
        </div>
    </div>
<script>
setTimeout(() => { document.querySelectorAll('.auto-dismiss').forEach((el) => { el.style.display = 'none'; }); }, 10000);
(function () {
    const form = document.getElementById('controllerUpdateCheckForm');
    if (!form) return;
    const button = document.getElementById('controllerUpdateCheckButton');
    const statusEl = document.getElementById('controllerUpdateStatus');
    const applyForm = document.getElementById('controllerUpdateApplyForm');
    const defaultLabel = button.textContent;
    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        button.disabled = true;
        button.textContent = 'Checking...';
        statusEl.textContent = 'Checking GitHub...';
        statusEl.classList.add('is-busy');
        try {
            const resp = await fetch(form.action, { method: 'POST', headers: { 'X-Requested-With': 'fetch', 'Accept': 'application/json' } });
            if (!resp.ok) throw new Error('Update check failed');
            const data = await resp.json();
            document.getElementById('controllerUpdateBranch').textContent = data.branch || '--';
            document.getElementById('controllerUpdateCurrent').textContent = data.local_commit || '--';
            document.getElementById('controllerUpdateLatest').textContent = data.remote_commit || '--';
            statusEl.textContent = data.status || '--';
            applyForm.style.display = data.update_available ? '' : 'none';
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
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ title }}</title>
""" + PAGE_HEAD + """
    <style>
        .card > h1:first-child { display: none; }   /* the page title is in the header */
        .card h1, .card h2 { margin: 18px 0 8px; font-family: "Barlow Semi Condensed", "Barlow", sans-serif; font-size: 22px; font-weight: 600; color: var(--navy); }
        .card .detail:first-of-type { border-top: 0; }
        .card label { display: block; font-size: 14px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; margin: 14px 0 6px 2px; }
        .card input[type="text"], .card input[type="number"] { margin-bottom: 4px; }
        .card form button { margin-top: 16px; background: var(--navy); color: #ffffff; border-color: var(--navy); }
        .card .label { color: var(--muted); }
        .card .alarm { padding: 10px 12px; border-radius: 12px; border: 1px solid #e3a0a0; background: #fdecec; color: #8f1f1f; margin-top: 10px; }
        .card table { margin-top: 6px; }
        .card .button-link { display: flex; align-items: center; justify-content: center; min-height: 56px; margin-top: 10px; border-radius: 12px; border: 1px solid #c5d0dc; background: var(--card-2); color: var(--text); text-decoration: none; font-size: 18px; font-weight: 600; }
    </style>
</head>
<body>
    <header class="topbar">
        <a class="back" href="{{ back_url }}">← Back</a>
        <a class="back" href="{{ url_for('index') }}">⌂ Overview</a>
        <div class="title cond">{{ title }}</div>
        <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
    </header>
    <div class="wrap">
        <div class="card">{{ body|safe }}</div>
    </div>
</body>
</html>
"""


WATER_SETTINGS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Water meter</title>
""" + PAGE_HEAD + """
</head>
<body>
    <header class="topbar">
        <a class="back" href="{{ url_for('settings_view') }}">← Back</a>
        <a class="back" href="{{ url_for('index') }}">⌂ Overview</a>
        <div class="title cond">Water meter</div>
        <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
    </header>

    <div class="wrap">
        {% if request.args.get('msg') %}<div class="msg auto-dismiss {% if request.args.get('ok') == '0' %}error{% endif %}">{{ request.args.get('msg') }}</div>{% endif %}
        <div class="cols">
            <div class="col">
                <section>
                    <h2 class="section-title">Flow now</h2>
                    <div class="card">
                        <div class="now"><b class="cond">{{ current_value }}</b><span>L/min</span></div>
                        <div class="details">
                            <div class="detail"><span>Low flow alarm below</span><span>{{ water_low_lpm }} L/min</span></div>
                            <div class="detail"><span>Pulses per litre</span><span>{{ water_pulses_per_litre }}</span></div>
                            <div class="detail"><span>Total flow pulses</span><span>{{ total_flow_pulses }}</span></div>
                        </div>
                    </div>
                </section>
            </div>
            <div class="col">
                <section>
                    <h2 class="section-title">Low flow alarm</h2>
                    <form class="card form" method="post" action="{{ url_for('save_water_settings') }}">
                        <div class="inline">
                            <div>
                                <label class="field" for="threshold_value">Alarm below (L/min)</label>
                                <input id="threshold_value" type="number" name="threshold_value" min="0" step="0.01" inputmode="decimal" enterkeyhint="done" value="{{ water_low_lpm }}">
                            </div>
                            <button class="primary" type="submit">Save</button>
                        </div>
                        <div class="hint">Green at or above this flow. Red below it, or when there's no reading.</div>
                    </form>
                </section>
                <section>
                    <h2 class="section-title">Meter calibration</h2>
                    <div class="card form">
                        <div class="hint">Run a 5 minute test against the bore hole's water meter:</div>
                        <div>
                            <div class="detail"><span>Test</span><span class="status">{{ calibration_status }}</span></div>
                            <div class="detail"><span>Pulses counted</span><span>{{ calibration_pulse_delta }}</span></div>
                            <div class="detail"><span>Time left</span><span>{{ calibration_remaining }}</span></div>
                        </div>
                        {% if calibration_can_start %}
                        <form method="post" action="{{ url_for('start_water_calibration') }}"><button class="go" type="submit">Start 5 minute test</button></form>
                        {% elif calibration_active %}
                        <form method="post" action="{{ url_for('cancel_water_calibration') }}"><button class="danger" type="submit">Cancel test</button></form>
                        {% endif %}
                        <form method="post" action="{{ url_for('finish_water_calibration') }}">
                            <div class="inline">
                                <div>
                                    <label class="field" for="meter_litres">Litres on the meter for the test</label>
                                    <input id="meter_litres" type="number" name="meter_litres" min="0.1" step="0.1" inputmode="decimal" enterkeyhint="done" value="" {% if not calibration_ready %}disabled{% endif %}>
                                </div>
                                <button class="primary" type="submit" {% if not calibration_ready %}disabled{% endif %}>Save</button>
                            </div>
                        </form>
                        <div class="hint">New pulses per litre = counted pulses divided by the litres from the physical meter.{% if not calibration_ready %} Complete the 5 minute test first to enable saving.{% endif %}</div>
                    </div>
                </section>
            </div>
        </div>
    </div>
<script>
setTimeout(() => { document.querySelectorAll('.auto-dismiss').forEach((el) => { el.style.display = 'none'; }); }, 10000);
{% if calibration_active %}setTimeout(() => window.location.reload(), 5000);{% endif %}
</script>
</body>
</html>
"""


BOREHOLE_COMMISSIONING_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Water &amp; Power Commissioning</title>
""" + PAGE_HEAD + """
    <style>
        pre { margin: 0; background: var(--card-2); border: 1px solid var(--track); border-radius: 12px; padding: 12px; white-space: pre-wrap; word-break: break-word; font-size: 13px; }
    </style>
</head>
<body>
    <header class="topbar">
        <a class="back" href="{{ url_for('settings_view') }}">← Back</a>
        <a class="back" href="{{ url_for('index') }}">⌂ Overview</a>
        <div class="title cond">Commissioning</div>
        <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
    </header>
    <div class="wrap">
        <div class="cols">
            <section>
                <h2 class="section-title">Water</h2>
                <div class="card">
                    <div class="detail" style="border-top: 0"><span>Water L/min</span><span>{{ water_lpm }}</span></div>
                    <div class="detail"><span>Flow total pulses</span><span>{{ flow_total_pulses }}</span></div>
                    <div class="detail"><span>Low flow threshold</span><span>{{ water_low_lpm }}</span></div>
                    <div class="detail"><span>Pulses per litre</span><span>{{ water_ppl }}</span></div>
                    <div class="detail"><span>Last sensor</span><span>{{ last_sensor }} · {{ last_sensor_age }}</span></div>
                    <div class="detail"><span>Office sync</span><span>{{ sync_short }}</span></div>
                </div>
            </section>
            <section>
                <h2 class="section-title">Controller</h2>
                <div class="card">
                    <div class="detail" style="border-top: 0"><span>Controller version</span><span class="mono">{{ app_version }}</span></div>
                    <div class="detail"><span>Pico local</span><span class="mono">{{ pico_local }}</span></div>
                    <div class="detail"><span>Pico deployed</span><span class="mono">{{ pico_deployed }}</span></div>
                    <div class="detail"><span>State version</span><span>{{ state_version }}</span></div>
                    <div class="detail"><span>Alarm count</span><span>{{ alarm_count }}</span></div>
                </div>
            </section>
        </div>
        <section style="margin-top: 20px">
            <h2 class="section-title">Raw packet</h2>
            <div class="card"><pre>{{ raw_json }}</pre></div>
        </section>
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
        :root {
            --bg: #5b5b5b;
            --panel: rgba(115, 115, 115, 0.96);
            --panel-2: rgba(104, 104, 104, 0.98);
            --line: #8a8a8a;
            --text: #ececec;
            --muted: #d2d2d2;
        }
        body {
            margin: 0;
            color: var(--text);
            font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
            background: #5b5b5b;
        }
        .wrap {
            max-width: 1100px;
            margin: 0 auto;
            padding: 18px;
        }
        .topbar {
            margin-bottom: 16px;
        }
        .topbar a {
            color: var(--text);
            text-decoration: none;
            font-size: 18px;
        }
        .panel {
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 20px;
            padding: 18px;
            margin-bottom: 16px;
        }
        .action-row {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 14px;
        }
        .action-link {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 44px;
            padding: 10px 14px;
            border-radius: 12px;
            border: 1px solid #d5dde6;
            background: var(--panel-2);
            color: var(--text);
            text-decoration: none;
            font-weight: 700;
        }
        h1 {
            margin: 0 0 8px 0;
            font-size: 38px;
        }
        .sub {
            color: var(--muted);
            margin-bottom: 16px;
            font-size: 18px;
        }
        .chart-wrap {
            background: var(--panel-2);
            border: 1px solid #d5dde6;
            border-radius: 16px;
            padding: 14px;
        }
        .chart-box {
            position: relative;
            height: 360px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 15px;
        }
        th, td {
            border-bottom: 1px solid #d5dde6;
            padding: 10px 8px;
            text-align: left;
        }
        th {
            color: var(--muted);
        }
        .empty {
            color: var(--muted);
            font-size: 18px;
        }
        .view-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
        .view-head .action-link { min-height: 48px; padding: 0 18px; font-size: 17px; cursor: pointer; }
        #allDaysBtn[hidden] { display: none !important; }
        .chart-scroll { overflow-x: auto; overflow-y: hidden; -webkit-overflow-scrolling: touch; }
        .day-link { all: unset; cursor: pointer; color: #1676b8; font-weight: 600; text-decoration: underline; text-underline-offset: 3px; min-height: 32px; display: inline-flex; align-items: center; }
        .day-link:focus-visible { outline: 3px solid #f08a12; outline-offset: 2px; }
        .table-controls {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
            margin-top: 12px;
        }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="wrap">
        <nav class="page-nav" aria-label="Page navigation"><a class="page-nav-btn" href="{{ url_for('settings_view') }}" data-nav-back>← Back</a><a class="page-nav-btn" href="{{ url_for('index') }}">⌂ Overview</a></nav>
        <div class="panel">
            <div class="view-head">
                <div>
                    <h1>{{ metric_title }}</h1>
                    <div class="sub" id="viewSub">Bore hole water, last 45 days. Daily totals, 6am to 6am. Tap a day to see its hours.</div>
                </div>
                <button type="button" id="allDaysBtn" class="action-link" hidden>← All days</button>
            </div>
            {% if rows %}
            <div class="chart-wrap">
                <div class="chart-scroll" id="chartScroll">
                    <div class="chart-box" id="chartInner"><canvas id="historyChart" aria-label="{{ metric_title }} chart"></canvas></div>
                </div>
            </div>
            {% else %}
            <div class="empty">No water history recorded yet.</div>
            {% endif %}
        </div>
        {% if rows %}
        <div class="panel">
            <h1 style="font-size:26px;" id="tableTitle">Daily totals</h1>
            <table>
                <thead><tr><th id="colWhen">Day</th><th id="colValue">{{ series[0].axis_title }}</th><th id="colMore"></th></tr></thead>
                <tbody id="historyBody"></tbody>
            </table>
        </div>
        {% endif %}
    </div>
    <script>
    const labels = {{ labels|tojson }};
    const epochs = {{ epochs|tojson }};
    const series = {{ series|tojson }};
    const metric = series.length ? series[0] : null;
    const unit = metric ? metric.axis_title.split(' ').pop().replace('KG', 'kg') : '';
    const DAY_START_HOUR = 6;   // farm day runs 6am to 6am, matching the yesterday figures

    function pad(n) { return String(n).padStart(2, '0'); }
    function fmt(v) { return v === null || v === undefined ? '--' : Number(v).toLocaleString('en-GB', { maximumFractionDigits: 1 }); }
    function dayKeyFor(epoch) {
        const d = new Date((epoch - DAY_START_HOUR * 3600) * 1000);
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    }

    // Group the hourly points into farm days.
    const days = [];
    const dayMap = {};
    if (metric) {
        epochs.forEach((epoch, i) => {
            if (epoch === null || epoch === undefined) return;
            const key = dayKeyFor(epoch);
            if (!dayMap[key]) {
                const parts = key.split('-').map(Number);
                const start = new Date(parts[0], parts[1] - 1, parts[2], DAY_START_HOUR, 0, 0);
                dayMap[key] = {
                    key: key,
                    start: start,
                    label: start.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short' }),
                    total: 0, seen: 0, hours: {}
                };
                days.push(dayMap[key]);
            }
            const v = metric.values[i];
            if (v !== null && v !== undefined) {
                dayMap[key].total += Number(v);
                dayMap[key].seen += 1;
            }
            dayMap[key].hours[epoch] = v;
        });
        days.sort((a, b) => a.start - b.start);
        if (days.length) days[days.length - 1].partial = (Date.now() - days[days.length - 1].start.getTime()) < 24 * 3600 * 1000;
    }

    // Writes each bar's figure on the bar: across the top when the bar is wide enough,
    // up the bar when it is narrow, or just above it when the bar is too short.
    // Writes each bar's figure up the bar, inside it when it fits, otherwise just above it.
    const barValueLabels = {
        id: 'barValueLabels',
        afterDatasetsDraw(c) {
            const meta = c.getDatasetMeta(0);
            const data = c.data.datasets[0].data;
            const g = c.ctx;
            g.save();
            g.font = '600 13px "Barlow Semi Condensed", Barlow, sans-serif';
            g.fillStyle = '#0d2b4a';
            meta.data.forEach((bar, i) => {
                const v = data[i];
                if (v === null || v === undefined) return;
                const text = fmt(v);
                const p = bar.getProps(['x', 'y', 'base'], true);
                const h = p.base - p.y;
                const inside = h >= g.measureText(text).width + 10;
                g.save();
                g.translate(p.x, inside ? p.y + 5 : p.y - 4);
                g.rotate(-Math.PI / 2);
                g.textAlign = inside ? 'right' : 'left';
                g.textBaseline = 'middle';
                g.fillText(text, 0, 0);
                g.restore();
            });
            g.restore();
        }
    };

    const MIN_BAR_PX = 38;   // bars never squeeze below this; the chart scrolls sideways instead
    let chart = null;
    function drawChart(type, chartLabels, values, onPick) {
        const el = document.getElementById('historyChart');
        if (!el) return;
        if (chart) chart.destroy();
        const scroller = document.getElementById('chartScroll');
        const inner = document.getElementById('chartInner');
        const needed = chartLabels.length * MIN_BAR_PX + 70;
        inner.style.width = needed > scroller.clientWidth ? needed + 'px' : '100%';
        chart = new Chart(el, {
            plugins: [barValueLabels],
            type: type,
            data: {
                labels: chartLabels,
                datasets: [{
                    label: metric.label + ' (' + unit + ')',
                    data: values,
                    borderWidth: 2,
                    pointRadius: 3,
                    tension: 0.2,
                    borderRadius: 4,
                    borderColor: metric.color,
                    backgroundColor: metric.color
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                onClick: (event, elements) => { if (onPick && elements.length) onPick(elements[0].index); },
                onHover: (event, elements) => { event.native.target.style.cursor = (onPick && elements.length) ? 'pointer' : 'default'; },
                layout: { padding: { top: 46 } },
                plugins: { legend: { labels: { color: '#0d2b4a' } } },
                scales: {
                    x: { ticks: { color: '#4a6078', autoSkip: false, maxRotation: 50, minRotation: 0 }, grid: { color: '#e3e9ef' } },
                    y: { beginAtZero: true, grace: '8%', ticks: { color: '#4a6078' }, grid: { color: '#e3e9ef' } }
                }
            }
        });
        scroller.scrollLeft = scroller.scrollWidth;   // open on the latest days
    }

    function showDays() {
        document.getElementById('allDaysBtn').hidden = true;
        document.getElementById('viewSub').textContent = 'Bore hole water, last 45 days. Daily totals, 6am to 6am. Tap a day to see its hours.';
        document.getElementById('tableTitle').textContent = 'Daily totals';
        document.getElementById('colWhen').textContent = 'Day';
        document.getElementById('colMore').textContent = '';
        drawChart('bar', days.map(d => d.label + (d.partial ? ' (so far)' : '')), days.map(d => d.seen ? Math.round(d.total * 10) / 10 : null), (i) => showDay(days[i].key));
        const body = document.getElementById('historyBody');
        body.innerHTML = '';
        days.slice().reverse().forEach((d) => {
            const tr = document.createElement('tr');
            const when = document.createElement('td');
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'day-link';
            btn.textContent = d.label + (d.partial ? ' (so far)' : '');
            btn.addEventListener('click', () => showDay(d.key));
            when.appendChild(btn);
            const val = document.createElement('td');
            val.textContent = d.seen ? fmt(d.total) + ' ' + unit : '--';
            const more = document.createElement('td');
            more.textContent = d.seen + ' h';
            more.style.color = '#4a6078';
            tr.append(when, val, more);
            body.appendChild(tr);
        });
    }

    function showDay(key) {
        const d = dayMap[key];
        if (!d) return;
        const slots = [];
        for (let h = 0; h < 24; h++) {
            const t = new Date(d.start.getTime() + h * 3600 * 1000);
            const epoch = Math.round(t.getTime() / 1000);
            slots.push({ label: pad(t.getHours()) + ':00', value: Object.prototype.hasOwnProperty.call(d.hours, epoch) ? d.hours[epoch] : null });
        }
        document.getElementById('allDaysBtn').hidden = false;
        document.getElementById('viewSub').textContent = d.label + ', 6am to 6am' + (d.partial ? ' (so far)' : '') + ' · ' + fmt(d.total) + ' ' + unit + ' in total';
        document.getElementById('tableTitle').textContent = 'Hourly, ' + d.label;
        document.getElementById('colWhen').textContent = 'Hour';
        document.getElementById('colMore').textContent = '';
        drawChart('bar', slots.map(s => s.label), slots.map(s => s.value), null);
        const body = document.getElementById('historyBody');
        body.innerHTML = '';
        slots.forEach((s) => {
            const tr = document.createElement('tr');
            const when = document.createElement('td'); when.textContent = s.label;
            const val = document.createElement('td'); val.textContent = s.value === null ? '--' : fmt(s.value) + ' ' + unit;
            tr.append(when, val, document.createElement('td'));
            body.appendChild(tr);
        });
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    document.getElementById('allDaysBtn').addEventListener('click', showDays);
    if (metric && days.length) showDays();
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
        push_short=ctx.get("push_short", "--"),
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
    # Same daily-bars page as the shed controllers' water log (tap a day for its hours).
    rows = get_hourly_history(max_points=24 * 45)
    return render_template_string(
        HISTORY_HTML,
        metric_title=metric_title,
        series=[{"label": metric_title, "axis_title": y_axis_title, "color": color, "values": [r.get("water") for r in rows]}],
        rows=[{"label": r.get("label"), "values": [fmt_value(r.get("water"), fmt)]} for r in rows],
        labels=[r.get("label") for r in rows],
        epochs=[r.get("epoch") for r in rows],
    )


@app.route("/history/water")
def water_history_view():
    return render_metric_history("Water History", "Water L", "#5fd0d8", "f1")


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
      <label>Shelly 3EM address (incoming supply)</label>
      <input type="text" name="shelly_host" placeholder="e.g. 192.168.1.60 (leave blank if none)" value="%s">
      <label>Supply fuse rating per phase (A, 0 for none)</label>
      <input type="number" name="supply_fuse_amps" min="0" step="1" value="%s">
      <label>Phase this controller is powered from</label>
      <select name="controller_phase">%s</select>
      <div class="hint" style="margin-top:6px">If that phase is lost the controller switches off too, so the office raises the alarm instead.</div>
      <button type="submit">Save Config</button>
    </form>
    """ % (
        url_for("save_config_view"),
        cfg.get("dashboard_url", ""),
        host_ipv4_display(),
        cfg.get("touch_refresh_seconds", 1),
        cfg.get("water_low_lpm", 0.1),
        cfg.get("water_pulses_per_litre", 450.0),
        escape(cfg.get("shelly_host", "") or ""),
        cfg.get("supply_fuse_amps", 0) or 0,
        "".join('<option value="%s"%s>%s</option>' % (v, " selected" if str(cfg.get("controller_phase", "") or "") == v else "", label)
                for v, label in [("", "Not set"), ("L1", "L1"), ("L2", "L2"), ("L3", "L3")]),
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
    try:
        cfg["supply_fuse_amps"] = max(0, int(float(request.form.get("supply_fuse_amps", cfg.get("supply_fuse_amps", 0)) or 0)))
    except Exception:
        pass
    if request.form.get("controller_phase", None) in ["", "L1", "L2", "L3"]:
        cfg["controller_phase"] = request.form.get("controller_phase")
    if "shelly_host" in request.form:
        cfg["shelly_host"] = str(request.form.get("shelly_host") or "").strip().replace("http://", "").replace("https://", "").strip("/")
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
    body { margin:0; background: #5b5b5b; color: #0d2b4a; font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; }
    .wrap { max-width:760px; margin:0 auto; padding:32px 18px; }
    .panel { background: #ffffff; border: 1px solid #d5dde6; border-radius:20px; padding:24px; }
    h1 { margin:0 0 12px 0; font-size:34px; }
    .sub { color: #0d2b4a; font-size:18px; }
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
    threading.Thread(target=shelly_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(load_config().get("listen_port", 8092)))
