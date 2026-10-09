from flask import Flask, render_template_string, request, redirect, url_for, jsonify, Response, send_file
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
from urllib.parse import urlparse

try:
    import serial
    import serial.tools.list_ports
except Exception:
    serial = None

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
    '.cdf-number-pad{position:fixed;right:12px;bottom:12px;z-index:9999;width:min(420px,calc(100vw - 24px));padding:10px;background:rgba(255,255,255,0.98);backdrop-filter:blur(8px);border:1px solid #d5dde6;border-radius:18px;box-shadow:0 18px 36px rgba(0,0,0,0.28);transform:translateY(calc(100% + 16px));transition:transform .12s ease-out;}'
    '.cdf-number-pad.is-open{transform:translateY(0);}'
    '.cdf-number-pad__panel{max-width:none;margin:0;}'
    '.cdf-number-pad__head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px;color:#0d2b4a;font:600 15px/1 "Barlow","Helvetica Neue",Helvetica,sans-serif;}'
    '.cdf-number-pad__value{color:#4a6078;font:600 13px/1 "Barlow","Helvetica Neue",Helvetica,sans-serif;min-height:14px;}'
    '.cdf-number-pad__grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;}'
    '.cdf-number-pad__key{min-height:52px;border-radius:12px;border:1px solid #c5d0dc;background:#f5f8fb;color:#0d2b4a;font:600 22px/1 "Barlow","Helvetica Neue",Helvetica,sans-serif;}'
    '.cdf-number-pad__key--wide{grid-column:span 2;}'
    '.cdf-number-pad__key--action{background:#dbe3ec;font-size:17px;}'
    '.cdf-number-pad__key--url{font-size:18px;}'
    '.cdf-number-pad__key[hidden]{display:none;}'
    '@media (max-width:700px){.cdf-number-pad{left:10px;right:10px;bottom:10px;width:auto;padding:10px;}.cdf-number-pad__key{min-height:54px;}}'
    '</style>'
)

# Shared look for every page not already built on the overview's theme (those carry
# the cdf-theme-native marker). Injected after each page's own styles so it wins.
THEME_HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Semi+Condensed:wght@500;600;700&display=swap">'
    '<link id="cdf-theme" rel="stylesheet" href="/static/stocksense-theme.css?v=1">'
)

# Back buttons (data-nav-back) return to the previous *different* page the viewer was on.
# Visited paths are remembered per browser session; a form save that reloads the same page
# doesn't count, so Back never lands on the page you just saved. The button's href is
# the fallback when there is no history (e.g. first page after the kiosk starts).
NAV_HISTORY_SCRIPT = """
<script id="cdf-nav-history">
(function () {
  var KEY = 'cdfNavStack';
  function load() { try { return JSON.parse(sessionStorage.getItem(KEY) || '[]'); } catch (e) { return []; } }
  function save(stack) { try { sessionStorage.setItem(KEY, JSON.stringify(stack.slice(-30))); } catch (e) {} }
  var stack = load();
  var here = location.pathname;
  if (stack.length && stack[stack.length - 1] === here) {
    // reload / form save on the same page
  } else if (stack.length > 1 && stack[stack.length - 2] === here) {
    stack.pop();
  } else {
    stack.push(here);
  }
  save(stack);
  document.addEventListener('click', function (event) {
    var btn = event.target.closest ? event.target.closest('[data-nav-back]') : null;
    if (!btn) return;
    var current = load();
    if (current.length > 1) {
      event.preventDefault();
      location.href = current[current.length - 2];
    }
  });
})();
</script>
"""

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
      <button type="button" id="cdfNumberPadHttp" class="cdf-number-pad__key cdf-number-pad__key--url cdf-number-pad__key--wide" data-key="http://">http://</button>
      <button type="button" id="cdfNumberPadColon" class="cdf-number-pad__key cdf-number-pad__key--url" data-key=":">:</button>
      <button type="button" id="cdfNumberPadSlash" class="cdf-number-pad__key cdf-number-pad__key--url" data-key="/">/</button>
      <button type="button" class="cdf-number-pad__key cdf-number-pad__key--action" data-action="backspace">Back</button>
      <button type="button" class="cdf-number-pad__key cdf-number-pad__key--action cdf-number-pad__key--wide" data-action="done">Done</button>
    </div>
  </div>
</div>
<script id="cdf-number-pad-script">
(function () {
  const pad = document.getElementById('cdfNumberPad');
  if (!pad) return;
  const HOME_PATH = '/';
  const INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000;
  const valueEl = document.getElementById('cdfNumberPadValue');
  const decimalBtn = document.getElementById('cdfNumberPadDecimal');
  const httpBtn = document.getElementById('cdfNumberPadHttp');
  const colonBtn = document.getElementById('cdfNumberPadColon');
  const slashBtn = document.getElementById('cdfNumberPadSlash');
  let activeInput = null;
  let dragScroll = null;
  let suppressClickUntil = 0;
  let inactivityTimer = null;

  function restartInactivityTimer() {
    if (inactivityTimer) {
      clearTimeout(inactivityTimer);
    }
    inactivityTimer = setTimeout(function () {
      if (window.location.pathname !== HOME_PATH) {
        window.location.href = HOME_PATH;
      }
    }, INACTIVITY_TIMEOUT_MS);
  }

  function isUrlPadInput(input) {
    return !!(input && input.matches && input.matches('input[data-cdf-urlpad]'));
  }

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
      const urlMode = isUrlPadInput(activeInput);
      decimalBtn.hidden = !urlMode && !supportsDecimal(activeInput);
      decimalBtn.textContent = '.';
      decimalBtn.setAttribute('data-key', '.');
      httpBtn.hidden = !urlMode;
      colonBtn.hidden = !urlMode;
      slashBtn.hidden = !urlMode;
    }
  }

  function openPad(input) {
    if (!input || input.disabled) return;
    activeInput = input;
    pad.classList.add('is-open');
    pad.setAttribute('aria-hidden', 'false');
    syncDisplay();
    restartInactivityTimer();
  }

  function closePad() {
    activeInput = null;
    pad.classList.remove('is-open');
    pad.setAttribute('aria-hidden', 'true');
    valueEl.textContent = '';
    restartInactivityTimer();
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
    if (target && target.matches && target.matches('input[type="number"], input[data-cdf-urlpad]')) {
      openPad(target);
      restartInactivityTimer();
    }
  });

  function isInteractiveTarget(target) {
    return !!(target && target.closest && target.closest('input, textarea, select, .cdf-number-pad'));
  }

  document.addEventListener('touchstart', function (event) {
    restartInactivityTimer();
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
    restartInactivityTimer();
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
    restartInactivityTimer();
  }, { passive: true });

  document.addEventListener('click', function (event) {
    restartInactivityTimer();
    if (Date.now() < suppressClickUntil) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);

  document.addEventListener('pointerdown', function (event) {
    restartInactivityTimer();
    const target = event.target;
    if (target && target.matches && target.matches('input[type="number"], input[data-cdf-urlpad]')) {
      openPad(target);
      return;
    }
    if (!pad.contains(target)) {
      closePad();
    }
  });

  pad.addEventListener('click', function (event) {
    restartInactivityTimer();
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
    if (!isUrlPadInput(activeInput) && key === '.' && (!supportsDecimal(activeInput) || current.includes('.'))) return;
    if (!isUrlPadInput(activeInput) && current === '0' && key !== '.') {
      commitValue(key);
      return;
    }
    commitValue(current + key);
  });

  document.addEventListener('keydown', restartInactivityTimer, true);
  document.addEventListener('wheel', restartInactivityTimer, { passive: true });
  window.addEventListener('scroll', restartInactivityTimer, { passive: true });
  window.addEventListener('mousemove', restartInactivityTimer, { passive: true });
  restartInactivityTimer();
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


@app.after_request
def inject_favicon(response):
    try:
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if (
            "text/html" in content_type
            or "application/json" in content_type
            or "javascript" in content_type
        ):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        if "text/html" in content_type and response.direct_passthrough is False:
            body = response.get_data(as_text=True)
            if "<head>" in body and 'cdf-touch-optimize' not in body:
                body = body.replace('<head>', '<head>' + TOUCH_OPTIMIZE_HEAD, 1)
            if "</head>" in body and 'cdf-theme' not in body:
                body = body.replace('</head>', THEME_HEAD + '</head>', 1)
            if "</body>" in body and 'cdf-number-pad-script' not in body:
                body = body.replace("</body>", NUMBER_PAD_BODY + "</body>", 1)
            if "</body>" in body and 'cdf-nav-history' not in body:
                body = body.replace("</body>", NAV_HISTORY_SCRIPT + "</body>", 1)
            response.set_data(body)
            response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception:
        pass
    return response

DATA_DIR = "controller_data"
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
SHED_NUMBERS = [1, 2, 3, 4, 6, 7, 8, 9, 10]
ENTRY_SHED_NUMBERS = [1, 2, 3, 4, 6, 61, 7, 8, 9, 10]
ENTRY_SHED_LABELS = {
    61: "Shed 6B",
}
SHED_DISPLAY_LABELS = {
    6: "Shed 6 & 6B",
}
DEFAULT_CONFIG = {
    "farm_id": "",
    "farm_name": "",
    "shed_no": 1,
    "dashboard_url": "http://127.0.0.1:8090",
    "sync_token": "",
    "deployment_mode": "commissioning",
    "commissioning_mode": True,
    "mode_switch_pin": "1234",
    "listen_port": 8091,
    "serial_port": "/dev/ttyACM0",
    "serial_baudrate": 115200,
    "serial_timeout": 1.0,
    "serial_enabled": True,
    "sync_on_sensor_update": True,
    "touch_refresh_seconds": 0.25,
    "temp_low_c": 18.0,
    "temp_high_c": 24.0,
    "temp_amber_margin_c": 1.0,
    "rh_low_pct": 40.0,
    "rh_high_pct": 80.0,
    "rh_amber_margin_pct": 5.0,
    "water_low_lpm": 0.1,
    "water_pulses_per_litre": 450.0,
    "feed_low_kg": 2000.0,
    "feed_capacity_kg": 16000.0,
    "feed_tare_raw": None,
    "feed_kg_per_raw_unit": None,
    "cross_auger_enabled": True,
    "auger_left_enabled": True,
    "auger_right_enabled": True,
    "lighting_enabled": False,
    "cross_auger_label": "Cross Auger",
    "auger_left_label": "Auger Left",
    "auger_right_label": "Auger Right",
    "lighting_label": "Lighting",
    "climate_limits_updated_ts": None,
    "auto_update_enabled": False,
    "layout_front_end": "left",
    "layout_bin_corner": "top-left",
    "layout_door_end": "left",
}

SHED_LAYOUT_ENDS = ["left", "right"]
SHED_LAYOUT_CORNERS = ["top-left", "top-right", "bottom-left", "bottom-right"]

SERIAL_THREAD = None
MONITOR_THREAD = None
SERIAL_STOP = threading.Event()
STATE_LOCK = threading.Lock()

AUGER_DEFS = [
    ("cross_auger", "Cross Auger"),
    ("auger_left", "Auger Left"),
    ("auger_right", "Auger Right"),
]
AUGER_PACKET_KEYS = {
    "cross_auger": ["cross_auger_on", "cross_auger"],
    "auger_left": ["auger_left_on", "auger_left"],
    "auger_right": ["auger_right_on", "auger_right"],
}
LIGHTING_PACKET_KEYS = ["lighting_on", "lighting"]
AUGER_OVERRUN_SECONDS = 20 * 60
BACKUP_INTERVAL_SECONDS = 3600
STALE_SENSOR_SECONDS = 30
STALE_OFFICE_SECONDS = 60
STALE_LOG_SECONDS = 30
WATER_LPM_AVERAGE_SECONDS = 12
WATER_ALARM_WINDOW_SECONDS = 10 * 60
WATER_ALARM_BASELINE_SECONDS = 60 * 60
WATER_ALARM_MIN_DROP_RATIO = 0.5
WATER_ALARM_HISTORY_KEEP_SECONDS = 2 * 60 * 60
WATER_ALARM_SNAPSHOT_SECONDS = 30
FEED_DISPLAY_AVERAGE_SECONDS = 60
FEED_DIAGNOSTIC_NOISE_SECONDS = 60
FEED_DIAGNOSTIC_HISTORY_SECONDS = 24 * 60 * 60
FEED_RAW_DISPLAY_SMOOTH_SECONDS = 10
FEED_REFILL_RISE_KG = 8.0
FEED_REFILL_SETTLING_SECONDS = 5 * 60
FEED_MOVEMENT_MIN_DROP_KG = 1.0
FEED_MOVEMENT_NOISE_FACTOR = 2.0
FEED_MOVEMENT_SESSION_GAP_SECONDS = 150
# A delivery can pause while the lorry swaps compartments; keep it as one fill-up.
FEED_FILL_SESSION_GAP_SECONDS = 20 * 60
FEED_STABLE_NOISE_KG = 2.0
PICO_AUTO_RECOVERY_FREEZE_SECONDS = 90
PICO_AUTO_RECOVERY_COOLDOWN_SECONDS = 10 * 60
PICO_POST_UPDATE_RECOVERY_WAIT_SECONDS = 20
PICO_REBOOT_SETTLE_SECONDS = 2.0
PICO_RECONNECT_TIMEOUT_SECONDS = 20.0
PICO_RECONNECT_PACKET_TIMEOUT_SECONDS = 4.0
SERIAL_READER_HEARTBEAT_SECONDS = 5
LOCAL_DASHBOARD_PULL_SECONDS = 1
LOCAL_DASHBOARD_HEARTBEAT_SECONDS = 10
LOCAL_BACKGROUND_SYNC_LOOP_SECONDS = 5
HIDE_HOME_ALERTS_DURING_SETUP = True
SYSTEM_ACTION_PATHS = {
    "shutdown": [("/sbin/shutdown", ["-h", "now"]), ("/usr/sbin/shutdown", ["-h", "now"])],
    "reboot": [("/sbin/reboot", []), ("/usr/sbin/reboot", [])],
    "restart_controller": [
        ("/bin/systemctl", ["restart", "shed-controller.service"]),
        ("/usr/bin/systemctl", ["restart", "shed-controller.service"]),
    ],
}


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


def crop_age_days(placement_epoch):
    if placement_epoch in [None, ""]:
        return None
    try:
        started_date = datetime.fromtimestamp(int(placement_epoch)).date()
        today = datetime.now().date()
    except Exception:
        return None
    return max(0, (today - started_date).days)


def shed_display_name_from_number(shed_no):
    try:
        shed_no = int(shed_no)
    except Exception:
        return "Shed --"
    return SHED_DISPLAY_LABELS.get(shed_no, "Shed %d" % shed_no)


def entry_shed_label(dest_shed):
    try:
        dest_shed = int(dest_shed)
    except Exception:
        return "Shed --"
    return ENTRY_SHED_LABELS.get(dest_shed, "Shed %d" % dest_shed)


def entry_home_shed_no(dest_shed):
    try:
        dest_shed = int(dest_shed)
    except Exception:
        return None
    if dest_shed == 61:
        return 6
    return dest_shed


def valid_entry_shed(dest_shed):
    try:
        return int(dest_shed) in ENTRY_SHED_NUMBERS
    except Exception:
        return False


def append_ndjson(path, payload):
    with open(path, "a") as f:
        f.write(json.dumps(payload) + "\n")


def auger_runs_path():
    ensure_data_dir()
    return os.path.join(DATA_DIR, "auger_runs.ndjson")


def update_status_path():
    ensure_data_dir()
    return os.path.join(DATA_DIR, "update_status.json")


def load_update_status():
    default = {
        "checked_at": None,
        "local_commit": "--",
        "remote_commit": "--",
        "branch": "main",
        "update_available": False,
        "ok": True,
        "status": "Not checked yet",
        "restart_required": False,
    }
    data = read_json_file(update_status_path(), default)
    if not isinstance(data, dict):
        return dict(default)
    merged = dict(default)
    merged.update(data)
    return merged


def save_update_status(payload):
    status = load_update_status()
    status.update(payload)
    write_json_file_atomic(update_status_path(), status)


def pico_update_status_path():
    ensure_data_dir()
    return os.path.join(DATA_DIR, "pico_update_status.json")


def load_pico_update_status():
    default = {
        "checked_at": None,
        "local_hash": "--",
        "last_deployed_hash": "--",
        "last_deployed_at": None,
        "ok": True,
        "status": "Not deployed yet",
    }
    data = read_json_file(pico_update_status_path(), default)
    if not isinstance(data, dict):
        return dict(default)
    merged = dict(default)
    merged.update(data)
    return merged


def save_pico_update_status(payload):
    status = load_pico_update_status()
    status.update(payload)
    write_json_file_atomic(pico_update_status_path(), status)


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


def pico_firmware_needs_deploy():
    local_hash = pico_firmware_hash()
    status = load_pico_update_status()
    last_deployed_hash = str(status.get("last_deployed_hash") or "--").strip() or "--"
    return local_hash != "--" and local_hash != last_deployed_hash


def mpremote_command():
    direct = shutil.which("mpremote")
    if direct:
        return [direct]
    user_local = os.path.join(os.path.expanduser("~"), ".local", "bin", "mpremote")
    if os.path.exists(user_local):
        return [user_local]
    return [sys.executable, "-m", "mpremote"]


def pause_sensor_threads(join_timeout=3.0):
    SERIAL_STOP.set()
    threads = [SERIAL_THREAD, MONITOR_THREAD]
    i = 0
    while i < len(threads):
        thread = threads[i]
        if thread is not None and thread.is_alive():
            try:
                thread.join(join_timeout)
            except Exception:
                pass
        i += 1
    time.sleep(0.4)


def resume_sensor_threads():
    SERIAL_STOP.clear()
    start_serial_thread()
    start_monitor_thread()


def wait_for_pico_serial_ready(timeout_seconds=PICO_RECONNECT_TIMEOUT_SECONDS, packet_timeout_seconds=PICO_RECONNECT_PACKET_TIMEOUT_SECONDS):
    if serial is None:
        time.sleep(PICO_REBOOT_SETTLE_SECONDS)
        return False, "pyserial not installed"

    cfg = load_config()
    deadline = time.time() + max(1.0, float(timeout_seconds))
    last_error = "Timed out waiting for Pico serial device"

    time.sleep(PICO_REBOOT_SETTLE_SECONDS)

    while time.time() < deadline:
        port = detect_serial_port()
        if not port:
            last_error = "Pico serial device not found yet"
            time.sleep(0.5)
            continue

        conn = None
        try:
            conn = serial.Serial(
                port=port,
                baudrate=cfg["serial_baudrate"],
                timeout=min(max(float(cfg["serial_timeout"]), 0.2), 1.0),
            )
            packet_deadline = time.time() + max(1.0, float(packet_timeout_seconds))
            while time.time() < packet_deadline:
                raw = conn.readline()
                if not raw:
                    continue
                try:
                    line = raw.decode("utf-8", errors="ignore").strip()
                except Exception:
                    continue
                if not line:
                    continue
                try:
                    packet = json.loads(line)
                except Exception:
                    last_error = "Pico serial returned non-JSON data"
                    continue
                if isinstance(packet, dict):
                    return True, "Pico serial ready on %s" % port
            last_error = "Pico serial reopened but no valid JSON packet arrived"
        except Exception as exc:
            last_error = str(exc) or "Pico serial reopen failed"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        time.sleep(0.5)

    return False, last_error


def perform_pico_reset(mpremote):
    commands = [
        ("soft-reset", mpremote + ["connect", "auto", "soft-reset"]),
        ("machine.reset()", mpremote + ["connect", "auto", "exec", "import machine; machine.reset()"]),
    ]

    last_detail = "Pico reset command failed"
    i = 0
    while i < len(commands):
        label, cmd = commands[i]
        i += 1
        try:
            proc = subprocess.run(
                cmd,
                cwd=APP_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:
            last_detail = "%s failed: %s" % (label, exc)
            continue

        if proc.returncode == 0:
            return True, "%s sent" % label

        detail = (proc.stderr or proc.stdout or "").strip()
        last_detail = "%s failed: %s" % (label, detail or "command returned non-zero")

    return False, last_detail


def run_git_command(args, timeout=20):
    proc = subprocess.run(
        ["git"] + args,
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def get_local_git_status():
    code, branch_out, branch_err = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch_out if code == 0 and branch_out else "main"
    code, commit_out, commit_err = run_git_command(["rev-parse", "--short", "HEAD"])
    commit = commit_out if code == 0 and commit_out else "--"
    ok = code == 0
    err = branch_err or commit_err
    return {"branch": branch, "local_commit": commit, "ok": ok, "error": err}


def check_for_update():
    local = get_local_git_status()
    status = {
        "checked_at": int(time.time()),
        "branch": local["branch"],
        "local_commit": local["local_commit"],
        "remote_commit": "--",
        "update_available": False,
        "ok": local["ok"],
        "status": "Up to date" if local["ok"] else (local["error"] or "Git status failed"),
        "restart_required": False,
    }
    if not local["ok"]:
        save_update_status(status)
        return status

    code, _, fetch_err = run_git_command(["fetch", "origin", local["branch"]], timeout=30)
    if code != 0:
        status["ok"] = False
        status["status"] = fetch_err or "Fetch failed"
        save_update_status(status)
        return status

    code, remote_out, remote_err = run_git_command(["rev-parse", "--short", "origin/%s" % local["branch"]])
    if code != 0 or not remote_out:
        status["ok"] = False
        status["status"] = remote_err or "Remote version lookup failed"
        save_update_status(status)
        return status

    status["remote_commit"] = remote_out
    status["update_available"] = remote_out != local["local_commit"]
    if status["update_available"]:
        status["status"] = "Update available"
    else:
        status["status"] = "Already on latest version"
    save_update_status(status)
    return status


def restart_self_delayed(delay_seconds=1.0, supervised_exit=True):
    def _restart():
        time.sleep(delay_seconds)
        if supervised_exit and (os.environ.get("INVOCATION_ID") or os.environ.get("JOURNAL_STREAM")):
            os._exit(0)
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])

    threading.Thread(target=_restart, daemon=True).start()


def restart_service_or_self(delay_seconds=1.0):
    def _restart_service():
        time.sleep(delay_seconds)
        ok, detail = run_system_action("restart_controller")
        if ok:
            try:
                record_controller_event(
                    "controller_restart",
                    "Controller restart requested",
                    "Restart handoff sent to shed-controller.service",
                    push_to_office=False,
                )
            except Exception:
                pass
            return
        try:
            record_controller_event(
                "controller_restart_fallback",
                "Controller service restart failed",
                str(detail or "Falling back to in-process restart"),
                push_to_office=False,
            )
        except Exception:
            pass
        restart_self_delayed(0.1, supervised_exit=False)

    threading.Thread(target=_restart_service, daemon=True).start()
    return True


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


def deploy_pico_firmware():
    local_hash = pico_firmware_hash()
    status = {
        "checked_at": int(time.time()),
        "local_hash": local_hash,
        "ok": False,
        "status": "Pico deploy failed",
    }
    if local_hash == "--":
        status["status"] = "Local pico_firmware/main.py not found"
        save_pico_update_status(status)
        return status

    source_path = pico_firmware_path()
    code, stdout, stderr = run_git_command(["rev-parse", "--short", "HEAD"])
    controller_commit = stdout if code == 0 and stdout else "--"
    mpremote = mpremote_command()
    proc = None
    reset_ok = False
    reset_status = "Pico reset not attempted"
    ready_ok = False
    ready_status = "Pico serial reconnect not attempted"

    pause_sensor_threads()
    try:
        proc = subprocess.run(
            mpremote + ["connect", "auto", "fs", "cp", source_path, ":main.py"],
            cwd=APP_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0:
            reset_ok, reset_status = perform_pico_reset(mpremote)
            if reset_ok:
                ready_ok, ready_status = wait_for_pico_serial_ready()
    finally:
        resume_sensor_threads()
    if proc.returncode != 0:
        status["status"] = (proc.stderr or proc.stdout or "Pico copy failed").strip()
        save_pico_update_status(status)
        return status
    if not reset_ok:
        status["status"] = "Pico copied, but reset failed: %s" % reset_status
        save_pico_update_status(status)
        return status
    status.update({
        "ok": ready_ok,
        "status": "Pico firmware deployed from controller %s. %s" % (
            controller_commit,
            ready_status if ready_ok else "Pico reset sent, but reconnect check timed out: %s" % ready_status,
        ),
        "last_deployed_hash": local_hash,
        "last_deployed_at": int(time.time()),
    })
    save_pico_update_status(status)
    return status


def soft_reset_pico():
    status = load_pico_update_status()
    status.update({
        "checked_at": int(time.time()),
        "ok": False,
        "status": "Pico soft reset failed",
    })
    mpremote = mpremote_command()
    reset_ok = False
    reset_status = "Pico reset not attempted"
    ready_ok = False
    ready_status = "Pico serial reconnect not attempted"
    pause_sensor_threads()
    try:
        reset_ok, reset_status = perform_pico_reset(mpremote)
        if reset_ok:
            ready_ok, ready_status = wait_for_pico_serial_ready()
    finally:
        resume_sensor_threads()
    if not reset_ok:
        status["status"] = reset_status
        save_pico_update_status(status)
        return status

    status.update({
        "ok": ready_ok,
        "status": "Pico soft reset OK. %s" % (
            ready_status if ready_ok else "Reconnect check timed out: %s" % ready_status,
        ),
    })
    save_pico_update_status(status)
    return status


def load_config():
    ensure_data_dir()
    path = os.path.join(DATA_DIR, "controller_config.json")
    data = read_json_file(path, DEFAULT_CONFIG)
    if not isinstance(data, dict):
        data = dict(DEFAULT_CONFIG)

    cfg = dict(DEFAULT_CONFIG)
    cfg.update(data)
    try:
        cfg["shed_no"] = int(cfg.get("shed_no", 1))
    except Exception:
        cfg["shed_no"] = 1
    try:
        cfg["listen_port"] = int(cfg.get("listen_port", 8091))
    except Exception:
        cfg["listen_port"] = 8091
    try:
        cfg["serial_baudrate"] = int(cfg.get("serial_baudrate", 115200))
    except Exception:
        cfg["serial_baudrate"] = 115200
    try:
        cfg["serial_timeout"] = float(cfg.get("serial_timeout", 1.0))
    except Exception:
        cfg["serial_timeout"] = 1.0
    raw_touch_refresh = cfg.get("touch_refresh_seconds", DEFAULT_CONFIG["touch_refresh_seconds"])
    if raw_touch_refresh in [None, "", 1, 1.0, "1", "1.0", 0.5, "0.5"]:
        raw_touch_refresh = DEFAULT_CONFIG["touch_refresh_seconds"]
    try:
        cfg["touch_refresh_seconds"] = max(0.25, float(raw_touch_refresh))
    except Exception:
        cfg["touch_refresh_seconds"] = DEFAULT_CONFIG["touch_refresh_seconds"]
    cfg["cross_auger_enabled"] = bool(cfg.get("cross_auger_enabled", True))
    cfg["auger_left_enabled"] = bool(cfg.get("auger_left_enabled", True))
    cfg["auger_right_enabled"] = bool(cfg.get("auger_right_enabled", True))
    cfg["lighting_enabled"] = bool(cfg.get("lighting_enabled", True))
    cfg["cross_auger_label"] = str(cfg.get("cross_auger_label", "Cross Auger") or "Cross Auger").strip()
    cfg["auger_left_label"] = str(cfg.get("auger_left_label", "Auger Left") or "Auger Left").strip()
    cfg["auger_right_label"] = str(cfg.get("auger_right_label", "Auger Right") or "Auger Right").strip()
    cfg["lighting_label"] = str(cfg.get("lighting_label", "Lighting") or "Lighting").strip()
    try:
        cfg["temp_low_c"] = float(cfg.get("temp_low_c", 18.0))
    except Exception:
        cfg["temp_low_c"] = 18.0
    try:
        cfg["temp_high_c"] = float(cfg.get("temp_high_c", 24.0))
    except Exception:
        cfg["temp_high_c"] = 24.0
    try:
        cfg["temp_amber_margin_c"] = float(cfg.get("temp_amber_margin_c", 1.0))
    except Exception:
        cfg["temp_amber_margin_c"] = 1.0
    try:
        cfg["rh_low_pct"] = float(cfg.get("rh_low_pct", 40.0))
    except Exception:
        cfg["rh_low_pct"] = 40.0
    try:
        cfg["rh_high_pct"] = float(cfg.get("rh_high_pct", 80.0))
    except Exception:
        cfg["rh_high_pct"] = 80.0
    try:
        cfg["rh_amber_margin_pct"] = float(cfg.get("rh_amber_margin_pct", 5.0))
    except Exception:
        cfg["rh_amber_margin_pct"] = 5.0
    try:
        cfg["water_low_lpm"] = float(cfg.get("water_low_lpm", 0.1))
    except Exception:
        cfg["water_low_lpm"] = 0.1
    try:
        cfg["water_pulses_per_litre"] = float(cfg.get("water_pulses_per_litre", 450.0))
    except Exception:
        cfg["water_pulses_per_litre"] = 450.0
    try:
        cfg["feed_low_kg"] = float(cfg.get("feed_low_kg", 2000.0))
    except Exception:
        cfg["feed_low_kg"] = 2000.0
    try:
        raw_capacity = cfg.get("feed_capacity_kg", 16000.0)
        cfg["feed_capacity_kg"] = float(raw_capacity) if raw_capacity not in [None, ""] else 16000.0
    except Exception:
        cfg["feed_capacity_kg"] = 16000.0
    try:
        raw_tare = cfg.get("feed_tare_raw")
        cfg["feed_tare_raw"] = float(raw_tare) if raw_tare not in [None, ""] else None
    except Exception:
        cfg["feed_tare_raw"] = None
    try:
        raw_scale = cfg.get("feed_kg_per_raw_unit")
        cfg["feed_kg_per_raw_unit"] = float(raw_scale) if raw_scale not in [None, ""] else None
    except Exception:
        cfg["feed_kg_per_raw_unit"] = None
    if cfg.get("layout_front_end") not in SHED_LAYOUT_ENDS:
        cfg["layout_front_end"] = "left"
    if cfg.get("layout_bin_corner") not in SHED_LAYOUT_CORNERS:
        cfg["layout_bin_corner"] = "top-left"
    if cfg.get("layout_door_end") not in SHED_LAYOUT_ENDS:
        cfg["layout_door_end"] = "left"
    cfg["auto_update_enabled"] = bool(cfg.get("auto_update_enabled", False))
    cfg["serial_enabled"] = bool(cfg.get("serial_enabled", True))
    cfg["sync_on_sensor_update"] = bool(cfg.get("sync_on_sensor_update", True))
    cfg["deployment_mode"] = str(cfg.get("deployment_mode", "commissioning") or "commissioning").strip().lower()
    if cfg["deployment_mode"] not in ["commissioning", "live"]:
        cfg["deployment_mode"] = "commissioning"
    cfg["commissioning_mode"] = bool(cfg.get("commissioning_mode", cfg["deployment_mode"] != "live"))
    cfg["deployment_mode"] = "commissioning" if cfg["commissioning_mode"] else "live"
    cfg["mode_switch_pin"] = str(cfg.get("mode_switch_pin", DEFAULT_CONFIG["mode_switch_pin"]) or DEFAULT_CONFIG["mode_switch_pin"]).strip()
    cfg["dashboard_url"] = str(cfg.get("dashboard_url", DEFAULT_CONFIG["dashboard_url"])).rstrip("/")
    cfg["serial_port"] = str(cfg.get("serial_port", DEFAULT_CONFIG["serial_port"]))
    return cfg


def commissioning_mode_enabled(cfg=None):
    cfg = cfg or load_config()
    return bool(cfg.get("commissioning_mode", True))


def current_mode_label(cfg=None):
    return "Commissioning" if commissioning_mode_enabled(cfg) else "Live"


def enabled_auger_keys(cfg):
    keys = []
    if cfg.get("cross_auger_enabled", True):
        keys.append("cross_auger")
    if cfg.get("auger_left_enabled", True):
        keys.append("auger_left")
    if cfg.get("auger_right_enabled", True):
        keys.append("auger_right")
    return keys


def lighting_enabled(cfg):
    return bool(cfg.get("lighting_enabled", True))


def lighting_label_for(cfg=None):
    cfg = cfg if isinstance(cfg, dict) else load_config()
    return str(cfg.get("lighting_label", "Lighting") or "Lighting").strip() or "Lighting"


def auger_label_for(cfg, auger_key, default_label):
    return str(cfg.get("%s_label" % auger_key, default_label) or default_label).strip()


def save_config(cfg):
    path = os.path.join(DATA_DIR, "controller_config.json")
    write_json_file_atomic(path, cfg)


def feed_calibration_history_path():
    ensure_data_dir()
    return os.path.join(DATA_DIR, "feed_calibration_history.json")


def load_feed_calibration_history():
    rows = read_json_file(feed_calibration_history_path(), [])
    return rows if isinstance(rows, list) else []


def save_feed_calibration_history(rows):
    write_json_file_atomic(feed_calibration_history_path(), rows[-50:] if isinstance(rows, list) else [])


def feed_calibration_snapshot(cfg):
    return {
        "feed_tare_raw": cfg.get("feed_tare_raw"),
        "feed_kg_per_raw_unit": cfg.get("feed_kg_per_raw_unit"),
    }


def append_feed_calibration_history(action, previous, updated, detail="", undoable=True):
    rows = load_feed_calibration_history()
    rows.append({
        "ts": int(time.time()),
        "action": str(action or "calibration"),
        "previous": previous if isinstance(previous, dict) else {},
        "updated": updated if isinstance(updated, dict) else {},
        "detail": str(detail or "").strip(),
        "undoable": bool(undoable),
        "undone_ts": None,
    })
    save_feed_calibration_history(rows)


def feed_calibration_undo_row():
    rows = load_feed_calibration_history()
    if not rows:
        return None
    row = rows[-1]
    if not isinstance(row, dict) or not bool(row.get("undoable", False)) or row.get("undone_ts") not in [None, ""]:
        return None
    return row


def feed_calibration_history_rows():
    rows = list(reversed(load_feed_calibration_history()))
    out = []
    i = 0
    while i < len(rows):
        rec = rows[i]
        i += 1
        if not isinstance(rec, dict):
            continue
        try:
            ts_label = datetime.fromtimestamp(int(rec.get("ts"))).strftime("%d %b %Y %H:%M")
        except Exception:
            ts_label = "--"
        previous = rec.get("previous", {}) if isinstance(rec.get("previous"), dict) else {}
        updated = rec.get("updated", {}) if isinstance(rec.get("updated"), dict) else {}
        out.append({
            "ts_label": ts_label,
            "action_label": str(rec.get("action") or "calibration").replace("_", " ").title(),
            "detail": str(rec.get("detail") or "").strip(),
            "previous_tare": fmt_value(previous.get("feed_tare_raw"), "f1"),
            "updated_tare": fmt_value(updated.get("feed_tare_raw"), "f1"),
            "previous_scale": fmt_value(previous.get("feed_kg_per_raw_unit"), "f6"),
            "updated_scale": fmt_value(updated.get("feed_kg_per_raw_unit"), "f6"),
        })
    return out


def backups_dir():
    ensure_data_dir()
    return os.path.join(DATA_DIR, "backups")


def local_ip_address():
    cfg = load_config()
    target_host = "127.0.0.1"
    try:
        parsed = urlparse(cfg.get("dashboard_url", ""))
        if parsed.hostname:
            target_host = parsed.hostname
    except Exception:
        pass

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((target_host, 80))
        return sock.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


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


def list_backup_files():
    # Newest first, by the time each backup was made (not alphabetically).
    base = backups_dir()
    out = []
    try:
        names = os.listdir(base)
    except Exception:
        return out
    for name in names:
        path = os.path.join(base, name)
        if os.path.isfile(path) and name.endswith(".zip"):
            out.append(path)
    out.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return out


def create_backup_zip(label="auto"):
    ensure_data_dir()
    ts = int(time.time())
    stamp = datetime.fromtimestamp(ts).strftime("%Y%m%d_%H%M%S")
    filename = "controller_%s_%s.zip" % (label, stamp)
    path = os.path.join(backups_dir(), filename)
    files = [
        os.path.join(DATA_DIR, "controller_config.json"),
        os.path.join(DATA_DIR, "controller_state.json"),
        os.path.join(DATA_DIR, "sensor_live.ndjson"),
        os.path.join(DATA_DIR, "auger_runs.ndjson"),
        os.path.join(DATA_DIR, "alarm_history.ndjson"),
        os.path.join(DATA_DIR, "feed_calibration_history.json"),
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        i = 0
        while i < len(files):
            src = files[i]
            if os.path.exists(src):
                zf.write(src, arcname=os.path.basename(src))
            i += 1
    path, healthy = mark_backup_suspect_if_bad(path)
    if healthy:
        prune_backups_layered(list_backup_files())
    return path


def maybe_auto_backup(state):
    now_ts = int(time.time())
    last_backup_ts = state.get("last_backup_ts")
    try:
        if last_backup_ts not in [None, ""] and (now_ts - int(last_backup_ts)) < BACKUP_INTERVAL_SECONDS:
            return
    except Exception:
        pass

    try:
        path = create_backup_zip("auto")
        state["last_backup_ts"] = now_ts
        if "suspect" in os.path.basename(path):
            state["last_backup_status"] = "Backup failed check, older backups kept: %s" % os.path.basename(path)
        else:
            state["last_backup_status"] = "Backup OK: %s" % os.path.basename(path)
    except Exception as exc:
        state["last_backup_ts"] = now_ts
        state["last_backup_status"] = "Backup failed: %s" % exc


def append_controller_event(payload):
    append_ndjson(os.path.join(DATA_DIR, "controller_events.ndjson"), payload)


def get_controller_events(limit=200):
    path = os.path.join(DATA_DIR, "controller_events.ndjson")
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        return []
    rows.sort(key=lambda r: int(r.get("ts", 0)), reverse=True)
    rows = rows[:limit]
    i = 0
    while i < len(rows):
        try:
            rows[i]["ts_label"] = datetime.fromtimestamp(int(rows[i].get("ts"))).strftime("%d %b %Y %H:%M:%S")
        except Exception:
            rows[i]["ts_label"] = "--"
        i += 1
    return rows


def append_alarm_history(payload):
    append_ndjson(os.path.join(DATA_DIR, "alarm_history.ndjson"), payload)


def get_alarm_history(limit=200):
    path = os.path.join(DATA_DIR, "alarm_history.ndjson")
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        return []
    rows.sort(key=lambda r: int(r.get("ts", 0)), reverse=True)
    rows = rows[:limit]
    i = 0
    while i < len(rows):
        row = rows[i]
        try:
            row["ts_label"] = datetime.fromtimestamp(int(row.get("ts"))).strftime("%d %b %Y %H:%M:%S")
        except Exception:
            row["ts_label"] = "--"
        event_type = str(row.get("event_type") or "").strip().lower()
        row["event_label"] = "Activated" if event_type == "activated" else ("Cleared" if event_type == "cleared" else "--")
        row["event_class"] = "bad" if event_type == "activated" else "ok"
        i += 1
    return rows


def get_auger_runs(limit=300):
    path = auger_runs_path()
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        return []
    rows = collate_auger_run_records(rows)
    rows = rows[:limit]

    out = []
    i = 0
    while i < len(rows):
        rec = rows[i]
        i += 1
        started_ts = rec.get("started_ts")
        stopped_ts = rec.get("stopped_ts") or rec.get("ts")
        duration_s = rec.get("duration_s")
        run_count = int(rec.get("run_count") or 1)
        out.append({
            "auger_label": str(rec.get("auger_label") or rec.get("auger_key") or "--"),
            "started_at": fmt_ts(started_ts),
            "stopped_at": fmt_ts(stopped_ts),
            "duration": fmt_duration_short(duration_s),
            "run_count": run_count,
            "run_count_label": "%d" % run_count,
        })
    return out


def collate_auger_run_records(records, short_max_seconds=15, gap_max_seconds=30):
    parsed = []
    if not isinstance(records, list):
        return parsed
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if not isinstance(rec, dict):
            continue
        try:
            started_ts = int(rec.get("started_ts"))
            stopped_ts = int(rec.get("stopped_ts") or rec.get("ts"))
        except Exception:
            continue
        try:
            duration_s = int(rec.get("duration_s"))
        except Exception:
            duration_s = max(0, stopped_ts - started_ts)
        parsed.append({
            "auger_label": str(rec.get("auger_label") or rec.get("auger_key") or "--"),
            "started_ts": started_ts,
            "stopped_ts": stopped_ts,
            "duration_s": max(0, duration_s),
            "run_count": int(rec.get("run_count") or 1),
        })

    parsed.sort(key=lambda r: (r["auger_label"], r["started_ts"]))
    groups = []
    current = None
    i = 0
    while i < len(parsed):
        rec = parsed[i]
        i += 1
        is_short = rec["duration_s"] <= short_max_seconds
        can_merge = (
            current is not None
            and current["auger_label"] == rec["auger_label"]
            and is_short
            and current.get("all_short", False)
            and (rec["started_ts"] - current["stopped_ts"]) <= gap_max_seconds
        )
        if can_merge:
            current["stopped_ts"] = max(current["stopped_ts"], rec["stopped_ts"])
            current["duration_s"] += rec["duration_s"]
            current["run_count"] += rec["run_count"]
            continue
        if current is not None:
            groups.append(current)
        current = dict(rec)
        current["all_short"] = is_short
    if current is not None:
        groups.append(current)

    groups.sort(key=lambda r: r["stopped_ts"], reverse=True)
    return groups


def post_event_to_dashboard(payload):
    try:
        with dashboard_request("/api/event", method="POST", payload=payload, timeout=4) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def record_controller_event(event_type, message, detail="", push_to_office=False):
    cfg = load_config()
    payload = {
        "ts": int(time.time()),
        "source": "controller",
        "event_type": str(event_type or "event"),
        "message": str(message or ""),
        "detail": str(detail or ""),
        "shed_no": cfg["shed_no"],
    }
    append_controller_event(payload)
    if push_to_office:
        post_event_to_dashboard(payload)


def default_augers_state():
    out = {}
    i = 0
    while i < len(AUGER_DEFS):
        key, label = AUGER_DEFS[i]
        out[key] = {
            "label": label,
            "on": False,
            "started_ts": None,
            "last_started_ts": None,
            "last_stopped_ts": None,
            "last_duration_s": None,
            "overrun": False,
        }
        i += 1
    return out


def default_sensor_state():
    return {
        "temp_c": None,
        "rh_pct": None,
        "climate_days": [],
        "water_lpm": None,
        "water_lpm_raw": None,
        "water_last_pulse_delta": None,
        "water_last_elapsed_s": None,
        "feed_kg": None,
        "lighting_on": None,
        "lighting_last_changed_ts": None,
        "lighting_last_on_ts": None,
        "lighting_last_off_ts": None,
        "device_status": "Waiting for Pico",
        "pico_connected": False,
        "pico_boot_count": None,
        "pico_reset_cause": "",
        "pico_packet_kind": "",
        "pico_checkpoint": "",
        "pico_checkpoint_ts": None,
        "serial_reader_status": "",
        "serial_reader_heartbeat_ts": None,
        "serial_reader_error": "",
        "serial_reader_error_ts": None,
        "serial_reader_port": "",
        "last_sensor_ts": None,
        "last_serial_line": "",
        "raw": {},
        "alarms": [],
        "controller_alarms": [],
        "augers": default_augers_state(),
        "flow_total_pulses": None,
        "flow_prev_total_pulses": None,
        "flow_prev_ts": None,
        "flow_rate_samples": [],
        "water_history_samples": [],
        "feed_raw_units": None,
        "feed_raw_display_units": None,
        "feed_raw_display_samples": [],
        "feed_raw_samples": [],
        "feed_average_raw_units": None,
        "hx711_dout": None,
        "hx711_sck": None,
        "hx711_ready": None,
        "hx711_dout_before": None,
        "hx711_sck_before": None,
        "hx711_ready_before": None,
        "feed_kg_live": None,
        "feed_kg_updated_ts": None,
        "feed_minute_change_kg": None,
        "feed_noise_raw_units": None,
        "feed_noise_kg": None,
        "feed_stability_label": "Waiting for samples",
        "feed_refill_settling_until_ts": None,
        "feed_published_samples": [],
        "feed_movement": {},
    }


def clean_feed_movement_state(rec):
    rec = rec if isinstance(rec, dict) else {}

    def float_or_none(key):
        try:
            return float(rec.get(key)) if rec.get(key) not in [None, ""] else None
        except Exception:
            return None

    def int_or_none(key):
        try:
            return int(rec.get(key)) if rec.get(key) not in [None, ""] else None
        except Exception:
            return None

    out = {
        "baseline_kg": float_or_none("baseline_kg"),
        "low_kg": float_or_none("low_kg"),
        "last_feed_kg": float_or_none("last_feed_kg"),
        "last_sample_ts": int_or_none("last_sample_ts"),
        "updated_ts": int_or_none("updated_ts"),
        "out_of_crop_feed_out_kg": float_or_none("out_of_crop_feed_out_kg") or 0.0,
        "out_of_crop_feed_in_kg": float_or_none("out_of_crop_feed_in_kg") or 0.0,
        "in_crop_feed_out_kg": float_or_none("in_crop_feed_out_kg") or 0.0,
        "in_crop_feed_in_kg": float_or_none("in_crop_feed_in_kg") or 0.0,
        "last_crop_state": str(rec.get("last_crop_state") or "").strip(),
        "last_crop_id": int_or_none("last_crop_id"),
        "last_movement": str(rec.get("last_movement") or "").strip(),
    }
    for key in ["out_of_crop_feed_out_kg", "out_of_crop_feed_in_kg", "in_crop_feed_out_kg", "in_crop_feed_in_kg"]:
        out[key] = round(max(0.0, float(out.get(key) or 0.0)), 3)
    events = rec.get("events", [])
    if not isinstance(events, list):
        events = []
    clean_events = []
    i = 0
    while i < len(events):
        event = events[i]
        i += 1
        if not isinstance(event, dict):
            continue
        try:
            event_ts = int(event.get("ts"))
            event_kg = round(float(event.get("kg")), 3)
        except Exception:
            continue
        try:
            start_ts = int(event.get("start_ts") or event_ts)
        except Exception:
            start_ts = event_ts
        try:
            end_ts = int(event.get("end_ts") or event_ts)
        except Exception:
            end_ts = event_ts
        if event_kg < 0.5:
            continue
        try:
            crop_id = int(event.get("crop_id")) if event.get("crop_id") not in [None, ""] else None
        except Exception:
            crop_id = None
        try:
            feed_kg_after = round(float(event.get("feed_kg_after")), 3) if event.get("feed_kg_after") not in [None, ""] else None
        except Exception:
            feed_kg_after = None
        clean_events.append({
            "id": str(event.get("id") or "%d-%d" % (event_ts, i)),
            "ts": event_ts,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "movement": str(event.get("movement") or "").strip(),
            "kg": event_kg,
            "crop_state": str(event.get("crop_state") or "").strip(),
            "crop_id": crop_id,
            "feed_kg_after": feed_kg_after,
        })
    clean_events.sort(key=lambda row: int(row.get("ts") or 0))
    out["events"] = clean_events[-500:]
    return out


def append_feed_movement_event(events, event, session_gap_seconds=FEED_MOVEMENT_SESSION_GAP_SECONDS):
    if not isinstance(events, list):
        events = []
    event = dict(event or {})
    try:
        event_ts = int(event.get("ts"))
    except Exception:
        event_ts = int(time.time())
    event["ts"] = event_ts
    event["start_ts"] = int(event.get("start_ts") or event_ts)
    event["end_ts"] = int(event.get("end_ts") or event_ts)
    try:
        event["kg"] = round(float(event.get("kg") or 0.0), 3)
    except Exception:
        event["kg"] = 0.0

    if event["kg"] < 0.5:
        return events[-500:]

    i = len(events) - 1
    while i >= 0:
        prev = events[i]
        i -= 1
        if not isinstance(prev, dict):
            continue
        try:
            prev_end_ts = int(prev.get("end_ts") or prev.get("ts") or 0)
        except Exception:
            prev_end_ts = 0
        if prev_end_ts <= 0:
            continue
        if event_ts - prev_end_ts > session_gap_seconds:
            break
        same_session = (
            str(prev.get("movement") or "") == str(event.get("movement") or "")
            and str(prev.get("crop_state") or "") == str(event.get("crop_state") or "")
            and str(prev.get("crop_id") or "") == str(event.get("crop_id") or "")
        )
        if not same_session:
            continue
        try:
            prev["kg"] = round(float(prev.get("kg") or 0.0) + float(event["kg"]), 3)
        except Exception:
            prev["kg"] = event["kg"]
        prev["ts"] = int(prev.get("start_ts") or prev.get("ts") or event_ts)
        prev["start_ts"] = int(prev.get("start_ts") or prev.get("ts") or event_ts)
        prev["end_ts"] = event_ts
        prev["feed_kg_after"] = event.get("feed_kg_after")
        return events[-500:]

    event["id"] = str(event.get("id") or "%s-%s" % (event_ts, event.get("movement") or "feed"))
    events.append(event)
    return events[-500:]


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ["1", "true", "on", "yes", "running"]:
            return True
        if text in ["0", "false", "off", "no", "waiting", "idle"]:
            return False
    return None


def normalize_controller_alarms(items):
    out = []
    if not isinstance(items, list):
        return out

    i = 0
    while i < len(items):
        item = items[i]
        if isinstance(item, dict):
            message = str(item.get("message", "")).strip()
            alarm_key = str(item.get("alarm_key", "")).strip()
            if message:
                out.append({
                    "alarm_key": alarm_key or "controller_alarm",
                    "message": message,
                })
        elif item not in [None, ""]:
            out.append({
                "alarm_key": "controller_alarm",
                "message": str(item),
            })
        i += 1
    return out


def ensure_augers_state(sensors):
    defaults = default_augers_state()
    incoming = sensors.get("augers", {})
    out = {}

    i = 0
    while i < len(AUGER_DEFS):
        key, label = AUGER_DEFS[i]
        rec = defaults[key]
        incoming_rec = incoming.get(key, {}) if isinstance(incoming, dict) else {}
        if isinstance(incoming_rec, dict):
            rec["label"] = str(incoming_rec.get("label", label) or label)
            rec["on"] = bool(incoming_rec.get("on", False))
            try:
                started_ts = incoming_rec.get("started_ts")
                if started_ts not in [None, ""]:
                    rec["started_ts"] = int(started_ts)
            except Exception:
                rec["started_ts"] = None
            try:
                last_started_ts = incoming_rec.get("last_started_ts")
                if last_started_ts not in [None, ""]:
                    rec["last_started_ts"] = int(last_started_ts)
            except Exception:
                rec["last_started_ts"] = None
            try:
                last_stopped_ts = incoming_rec.get("last_stopped_ts")
                if last_stopped_ts not in [None, ""]:
                    rec["last_stopped_ts"] = int(last_stopped_ts)
            except Exception:
                rec["last_stopped_ts"] = None
            try:
                last_duration_s = incoming_rec.get("last_duration_s")
                if last_duration_s not in [None, ""]:
                    rec["last_duration_s"] = int(last_duration_s)
            except Exception:
                rec["last_duration_s"] = None
            rec["overrun"] = bool(incoming_rec.get("overrun", False))
        out[key] = rec
        i += 1

    sensors["augers"] = out
    return out


def update_auger_state(auger_key, auger, is_on, now_ts, cfg=None):
    changed = False

    if is_on:
        if not auger.get("on"):
            auger["on"] = True
            auger["started_ts"] = now_ts
            auger["last_started_ts"] = now_ts
            changed = True
        elif auger.get("started_ts") in [None, ""]:
            auger["started_ts"] = now_ts
            auger["last_started_ts"] = now_ts
            changed = True
    else:
        if auger.get("on") or auger.get("started_ts") is not None or auger.get("overrun"):
            started_ts = auger.get("started_ts")
            duration_s = None
            try:
                if started_ts not in [None, ""]:
                    duration_s = max(0, int(now_ts) - int(started_ts))
            except Exception:
                duration_s = None
            auger["on"] = False
            auger["last_stopped_ts"] = now_ts
            auger["last_duration_s"] = duration_s
            auger["started_ts"] = None
            auger["overrun"] = False
            record_auger_run(auger_key, auger, now_ts, cfg=cfg)
            changed = True

    return changed


def update_lighting_state(sensors, is_on, now_ts):
    bool_value = bool(is_on)
    previous = normalize_bool(sensors.get("lighting_on"))
    changed = previous is None or previous != bool_value
    sensors["lighting_on"] = bool_value
    if changed:
        sensors["lighting_last_changed_ts"] = now_ts
        if bool_value:
            sensors["lighting_last_on_ts"] = now_ts
        else:
            sensors["lighting_last_off_ts"] = now_ts
    return changed


def lighting_status_text(sensors):
    state = normalize_bool(sensors.get("lighting_on"))
    if state is None:
        return "Waiting"
    return "On" if state else "Off"


def lighting_runtime_text(sensors, now_ts=None):
    if now_ts is None:
        now_ts = int(time.time())
    if not normalize_bool(sensors.get("lighting_on")):
        return ""
    try:
        started_ts = int(sensors.get("lighting_last_on_ts"))
    except Exception:
        return "On"
    return "On %ss" % max(0, int(now_ts) - started_ts)


def lighting_last_change_text(sensors):
    if normalize_bool(sensors.get("lighting_on")):
        if sensors.get("lighting_last_on_ts") not in [None, ""]:
            return "Last On %s" % fmt_clock_ts(sensors.get("lighting_last_on_ts"))
        return "Last On --"
    if sensors.get("lighting_last_off_ts") not in [None, ""]:
        return "Last Off %s" % fmt_clock_ts(sensors.get("lighting_last_off_ts"))
    return "Last Off --"


def lighting_glow_class(sensors):
    state = normalize_bool(sensors.get("lighting_on"))
    if state is None:
        return "state-warn"
    return "state-green" if state else "state-warn"


def evaluate_augers(sensors, now_ts=None):
    if now_ts is None:
        now_ts = int(time.time())

    augers = ensure_augers_state(sensors)
    changed = False
    controller_alarms = []
    cfg = load_config()
    active_auger_keys = enabled_auger_keys(cfg)

    i = 0
    while i < len(AUGER_DEFS):
        key, label = AUGER_DEFS[i]
        auger = augers[key]
        overrun = False

        if auger.get("on"):
            try:
                started_ts = int(auger.get("started_ts"))
            except Exception:
                started_ts = now_ts
                auger["started_ts"] = started_ts
                changed = True
            if now_ts - started_ts >= AUGER_OVERRUN_SECONDS:
                overrun = True

        if bool(auger.get("overrun")) != overrun:
            auger["overrun"] = overrun
            changed = True

        if overrun and not augers_look_floating(augers, active_auger_keys, cfg=cfg):
            controller_alarms.append({
                "alarm_key": "%s_overrun" % key,
                "message": "%s overrun: running longer than 20 minutes" % label,
            })
        i += 1

    if augers_look_floating(augers, active_auger_keys, cfg=cfg):
        i = 0
        while i < len(active_auger_keys):
            active_key = active_auger_keys[i]
            auger = augers.get(active_key, {})
            if auger.get("overrun"):
                auger["overrun"] = False
                changed = True
            i += 1

    normalized = normalize_controller_alarms(controller_alarms)
    if sensors.get("controller_alarms") != normalized:
        sensors["controller_alarms"] = normalized
        changed = True

    sensors["augers"] = augers
    return changed


def augers_look_floating(augers, active_auger_keys, cfg=None):
    if not commissioning_mode_enabled(cfg):
        return False
    if not active_auger_keys:
        return False

    i = 0
    while i < len(active_auger_keys):
        active_key = active_auger_keys[i]
        auger = augers.get(active_key, {})
        if not auger.get("on"):
            return False
        if auger.get("last_stopped_ts") not in [None, ""]:
            return False
        if auger.get("last_duration_s") not in [None, ""]:
            return False
        i += 1
    return True


def auger_is_waiting_override(auger_key, augers, active_auger_keys, cfg=None):
    if auger_key not in active_auger_keys:
        return False
    return augers_look_floating(augers, active_auger_keys, cfg=cfg)


def auger_status_text(auger):
    if auger.get("overrun"):
        return "Overrun"
    if auger.get("on"):
        return "On"
    return "Waiting"


def auger_glow_class(auger):
    if auger.get("overrun"):
        return "state-red"
    if auger.get("on"):
        return "state-green"
    return "state-warn"


def auger_runtime_text(auger, now_ts=None):
    if now_ts is None:
        now_ts = int(time.time())

    if not auger.get("on"):
        return ""

    try:
        started_ts = int(auger.get("started_ts"))
    except Exception:
        return "Running"

    runtime_seconds = max(0, int(now_ts) - started_ts)
    return "Running %ss" % runtime_seconds


def fmt_clock_ts(ts_value):
    if ts_value in [None, ""]:
        return "--"
    try:
        return datetime.fromtimestamp(int(ts_value)).strftime("%H:%M")
    except Exception:
        return "--"


def fmt_duration_short(seconds_value):
    if seconds_value in [None, ""]:
        return "--"
    try:
        total_seconds = max(0, int(seconds_value))
    except Exception:
        return "--"

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return "%dh %02dm" % (hours, minutes)
    if minutes > 0:
        return "%dm %02ds" % (minutes, seconds)
    return "%ss" % seconds


def record_auger_run(auger_key, auger, stopped_ts, cfg=None):
    cfg = cfg if isinstance(cfg, dict) else load_config()
    try:
        stopped_ts = int(stopped_ts)
    except Exception:
        return
    try:
        started_ts = int(auger.get("last_started_ts"))
    except Exception:
        started_ts = None
    try:
        duration_s = int(auger.get("last_duration_s"))
    except Exception:
        duration_s = None

    payload = {
        "ts": stopped_ts,
        "shed_no": cfg.get("shed_no"),
        "auger_key": auger_key,
        "auger_label": auger_label_for(cfg, auger_key, auger_key.replace("_", " ").title()),
        "started_ts": started_ts,
        "stopped_ts": stopped_ts,
        "duration_s": duration_s,
    }
    append_ndjson(auger_runs_path(), payload)


def auger_last_run_text(auger):
    if auger.get("last_started_ts") in [None, ""] or auger.get("last_duration_s") in [None, ""]:
        return "Last Run --"
    return "Last Run %s • %s" % (
        fmt_clock_ts(auger.get("last_started_ts")),
        fmt_duration_short(auger.get("last_duration_s")),
    )


def load_state():
    ensure_data_dir()
    path = os.path.join(DATA_DIR, "controller_state.json")
    data = read_json_file(path, {})
    if not isinstance(data, dict):
        data = {}

    state = {
        "shed_no": load_config()["shed_no"],
        "entries": {},
        "sensors": default_sensor_state(),
        "dashboard_summary": {
            "water_7to7": None,
            "feed_7to7": None,
            "mortality_total": None,
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
        "last_auto_sync_signature": "",
        "state_version": 0,
        "state_updated_ts": None,
        "entries_updated_ts": None,
        "last_seen_office_sync_version": 0,
        "last_seen_office_sync_ts": None,
        "last_sync_ts": None,
        "last_sync_status": "",
        "last_push_ts": None,
        "last_push_status": "",
        "last_dashboard_contact_ts": None,
        "last_dashboard_status": "",
        "last_log_ts": None,
        "last_log_status": "",
        "last_backup_ts": None,
        "last_backup_status": "",
        "last_alarm_snapshot": [],
        "last_pico_recovery_attempt_ts": None,
        "last_pico_recovery_result_ts": None,
        "last_pico_recovery_status": "",
        "pending_pico_update_recovery": False,
        "pending_pico_update_recovery_set_ts": None,
    }
    state.update(data)

    if not isinstance(state.get("entries"), dict):
        state["entries"] = {}
    if not isinstance(state.get("sensors"), dict):
        state["sensors"] = default_sensor_state()
    state.pop("feed_tracking", None)
    if not isinstance(state.get("dashboard_summary"), dict):
        state["dashboard_summary"] = {
            "water_7to7": None,
            "feed_7to7": None,
            "mortality_total": None,
        }
    if not isinstance(state.get("water_calibration"), dict):
        state["water_calibration"] = {
            "active": False,
            "start_ts": None,
            "end_ts": None,
            "start_total_pulses": None,
            "latest_total_pulses": None,
            "completed": False,
            "pulse_delta": None,
        }
    if not isinstance(state.get("last_auto_sync_signature"), str):
        state["last_auto_sync_signature"] = ""
    try:
        state["state_version"] = int(state.get("state_version", 0) or 0)
    except Exception:
        state["state_version"] = 0
    if state.get("state_updated_ts") in [""]:
        state["state_updated_ts"] = None
    if state.get("entries_updated_ts") in [""]:
        state["entries_updated_ts"] = None
    try:
        state["last_seen_office_sync_version"] = int(state.get("last_seen_office_sync_version", 0) or 0)
    except Exception:
        state["last_seen_office_sync_version"] = 0
    if state.get("last_seen_office_sync_ts") in [""]:
        state["last_seen_office_sync_ts"] = None
    if state.get("last_push_ts") in [""]:
        state["last_push_ts"] = None
    if not isinstance(state.get("last_push_status"), str):
        state["last_push_status"] = ""
    if state.get("last_dashboard_contact_ts") in [""]:
        state["last_dashboard_contact_ts"] = None
    if not isinstance(state.get("last_dashboard_status"), str):
        state["last_dashboard_status"] = ""
    if state.get("last_log_ts") in [""]:
        state["last_log_ts"] = None
    if not isinstance(state.get("last_log_status"), str):
        state["last_log_status"] = ""
    if state.get("last_backup_ts") in [""]:
        state["last_backup_ts"] = None
    if not isinstance(state.get("last_backup_status"), str):
        state["last_backup_status"] = ""
    if not isinstance(state.get("last_alarm_snapshot"), list):
        state["last_alarm_snapshot"] = []
    if state.get("last_pico_recovery_attempt_ts") in [""]:
        state["last_pico_recovery_attempt_ts"] = None
    if state.get("last_pico_recovery_result_ts") in [""]:
        state["last_pico_recovery_result_ts"] = None
    if not isinstance(state.get("last_pico_recovery_status"), str):
        state["last_pico_recovery_status"] = ""
    state["pending_pico_update_recovery"] = bool(state.get("pending_pico_update_recovery", False))
    if state.get("pending_pico_update_recovery_set_ts") in [""]:
        state["pending_pico_update_recovery_set_ts"] = None

    sensors = default_sensor_state()
    sensors.update(state["sensors"])
    if not isinstance(sensors.get("raw"), dict):
        sensors["raw"] = {}
    if not isinstance(sensors.get("alarms"), list):
        sensors["alarms"] = []
    if not isinstance(sensors.get("water_history_samples"), list):
        sensors["water_history_samples"] = []
    if not isinstance(sensors.get("climate_days"), list):
        sensors["climate_days"] = []
    if not isinstance(sensors.get("feed_raw_display_samples"), list):
        sensors["feed_raw_display_samples"] = []
    if sensors.get("feed_raw_display_units") in [""] and sensors.get("feed_raw_units") not in [None, ""]:
        sensors["feed_raw_display_units"] = sensors.get("feed_raw_units")
    if not isinstance(sensors.get("feed_raw_samples"), list):
        sensors["feed_raw_samples"] = []
    if not isinstance(sensors.get("feed_published_samples"), list):
        sensors["feed_published_samples"] = []
    sensors["feed_movement"] = clean_feed_movement_state(sensors.get("feed_movement", {}))
    if sensors.get("feed_kg_updated_ts") in [""]:
        sensors["feed_kg_updated_ts"] = None
    if sensors.get("feed_refill_settling_until_ts") in [""]:
        sensors["feed_refill_settling_until_ts"] = None
    sensors["controller_alarms"] = normalize_controller_alarms(sensors.get("controller_alarms", []))
    try:
        sensors["pico_boot_count"] = int(sensors.get("pico_boot_count")) if sensors.get("pico_boot_count") not in [None, ""] else None
    except Exception:
        sensors["pico_boot_count"] = None
    sensors["pico_reset_cause"] = str(sensors.get("pico_reset_cause") or "")
    sensors["pico_packet_kind"] = str(sensors.get("pico_packet_kind") or "")
    sensors["pico_checkpoint"] = str(sensors.get("pico_checkpoint") or "")
    if sensors.get("pico_checkpoint_ts") in [""]:
        sensors["pico_checkpoint_ts"] = None
    sensors["serial_reader_status"] = str(sensors.get("serial_reader_status") or "")
    sensors["serial_reader_error"] = str(sensors.get("serial_reader_error") or "")
    sensors["serial_reader_port"] = str(sensors.get("serial_reader_port") or "")
    if sensors.get("serial_reader_heartbeat_ts") in [""]:
        sensors["serial_reader_heartbeat_ts"] = None
    if sensors.get("serial_reader_error_ts") in [""]:
        sensors["serial_reader_error_ts"] = None
    ensure_augers_state(sensors)
    evaluate_augers(sensors)
    state["sensors"] = sensors
    return state


def save_state(state):
    path = os.path.join(DATA_DIR, "controller_state.json")
    write_json_file_atomic(path, state)


def mutate_state(mutator):
    with STATE_LOCK:
        state = load_state()
        mutator(state)
        try:
            state["state_version"] = int(state.get("state_version", 0) or 0) + 1
        except Exception:
            state["state_version"] = 1
        state["state_updated_ts"] = int(time.time())
        save_state(state)
        return state


def clean_entry_record(rec):
    if not isinstance(rec, dict):
        rec = {}

    try:
        bird_count = int(rec.get("bird_count", 0) or 0)
    except Exception:
        bird_count = 0

    try:
        placed_bird_count = rec.get("placed_bird_count", rec.get("placed_count", None))
        if placed_bird_count not in [None, ""]:
            placed_bird_count = int(placed_bird_count)
        else:
            placed_bird_count = bird_count
    except Exception:
        placed_bird_count = bird_count

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

    updated_by = str(rec.get("updated_by", "controller") or "controller")
    pens = normalize_pens(rec.get("pens", []))

    if pens:
        bird_count = 0
        i = 0
        while i < len(pens):
            bird_count += pens[i]["bird_count"]
            i += 1
        if placed_bird_count <= 0:
            placed_bird_count = bird_count

    if bird_count <= 0:
        bird_count = 0
        placed_bird_count = 0
        crop_active = 0
        placement_epoch = None
        crop_id = None
        pens = []
    elif placed_bird_count < bird_count:
        placed_bird_count = bird_count

    return {
        "bird_count": bird_count,
        "placed_bird_count": placed_bird_count,
        "crop_active": crop_active,
        "placement_epoch": placement_epoch,
        "crop_id": crop_id,
        "updated_ts": updated_ts,
        "updated_by": updated_by,
        "pens": pens,
    }


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


def get_entry(state):
    shed_no = load_config()["shed_no"]
    rec = state.get("entries", {}).get(str(shed_no), {})
    return clean_entry_record(rec)


def get_entry_for_dest(state, dest_shed):
    rec = state.get("entries", {}).get(str(dest_shed), {})
    return clean_entry_record(rec)


def set_entry(state, rec):
    shed_no = load_config()["shed_no"]
    state["entries"][str(shed_no)] = clean_entry_record(rec)


def set_entry_for_dest(state, dest_shed, rec):
    state["entries"][str(dest_shed)] = clean_entry_record(rec)


def clear_entry(state):
    shed_no = load_config()["shed_no"]
    if str(shed_no) in state.get("entries", {}):
        del state["entries"][str(shed_no)]


def clear_entry_for_dest(state, dest_shed):
    if str(dest_shed) in state.get("entries", {}):
        del state["entries"][str(dest_shed)]


def total_birds_from_entries(entries):
    total = 0
    for key in entries:
        rec = clean_entry_record(entries.get(key, {}))
        total += rec["bird_count"]
    return total


def total_placed_birds_from_entries(entries):
    total = 0
    for key in entries:
        rec = clean_entry_record(entries.get(key, {}))
        total += int(rec.get("placed_bird_count") or rec["bird_count"])
    return total


def active_crop_id_from_entries(entries):
    active_crop_id = None
    for key in entries:
        rec = clean_entry_record(entries.get(key, {}))
        if rec["crop_active"] != 1 or rec["bird_count"] <= 0 or rec["crop_id"] is None:
            continue
        if active_crop_id is None or int(rec["crop_id"]) > active_crop_id:
            active_crop_id = int(rec["crop_id"])
    return active_crop_id


def active_crop_epoch_from_entries(entries, crop_id=None):
    if crop_id in [None, ""]:
        crop_id = active_crop_id_from_entries(entries)
    if crop_id in [None, ""]:
        return None
    earliest = None
    for key in entries:
        rec = entries.get(key, {})
        try:
            rec_crop_id = int(rec.get("crop_id"))
            crop_active = 1 if int(rec.get("crop_active", 0) or 0) == 1 else 0
            bird_count = int(rec.get("bird_count", 0) or 0)
        except Exception:
            continue
        if rec_crop_id != int(crop_id) or crop_active != 1 or bird_count <= 0:
            continue
        try:
            placement_epoch = int(rec.get("placement_epoch"))
        except Exception:
            continue
        if earliest is None or placement_epoch < earliest:
            earliest = placement_epoch
    return earliest


def oldest_bird_age_days(entries):
    oldest_days = None

    for key in entries:
        rec = clean_entry_record(entries.get(key, {}))
        if rec["bird_count"] <= 0:
            continue

        placement_epoch = rec.get("placement_epoch")
        if placement_epoch in [None, ""]:
            continue

        age_days = crop_age_days(placement_epoch)
        if age_days is None:
            continue

        if oldest_days is None or age_days > oldest_days:
            oldest_days = age_days

    return oldest_days


def build_allocation_rows(state):
    rows = []
    i = 0
    while i < len(ENTRY_SHED_NUMBERS):
        dest_shed = ENTRY_SHED_NUMBERS[i]
        rec = get_entry_for_dest(state, dest_shed)
        rows.append({
            "dest_shed": dest_shed,
            "dest_shed_label": entry_shed_label(dest_shed),
            "bird_count": rec["bird_count"],
            "placed_bird_count": rec.get("placed_bird_count") or rec["bird_count"],
            "crop_active": rec["crop_active"],
            "crop_id": rec["crop_id"],
            "crop_code": fmt_crop_code(rec["crop_id"], rec["placement_epoch"]),
            "updated_ts": rec["updated_ts"],
            "placement_epoch": rec["placement_epoch"],
        })
        i += 1
    return rows


def allocation_summary_text(current_shed_no, entries):
    parts = []
    keys = []
    for key in entries:
        try:
            keys.append(int(key))
        except Exception:
            pass
    keys.sort()

    if len(keys) == 1 and keys[0] == int(current_shed_no):
        rec = clean_entry_record(entries.get(str(keys[0]), {}))
        if rec["bird_count"] > 0:
            return ""

    i = 0
    while i < len(keys):
        rec = clean_entry_record(entries.get(str(keys[i]), {}))
        if rec["bird_count"] > 0:
            parts.append("%s: %s" % (entry_shed_label(keys[i]), fmt_value(rec["bird_count"], "i")))
        i += 1

    return " - ".join(parts)


def sync_payload(state):
    cfg = load_config()
    shed_no = cfg["shed_no"]
    version = get_local_git_status()
    pico_status = load_pico_update_status()
    entries = {}
    for key in state.get("entries", {}):
        entries[str(key)] = clean_entry_record(state["entries"].get(key, {}))
    payload = {
        "shed_no": shed_no,
        "entries": entries,
        # Front-to-rear pen order, so the office can show and set which end each pen is at.
        "pen_order": {"order": [str(k) for k in (state.get("pen_order") or [])], "updated_ts": state.get("pen_order_ts"), "now": int(time.time())},
    }

    sensors = state.get("sensors", {})
    water_total_litres = None
    try:
        total_pulses = sensors.get("flow_total_pulses")
        pulses_per_litre = float(cfg.get("water_pulses_per_litre", 450.0))
        if total_pulses not in [None, ""] and pulses_per_litre > 0:
            water_total_litres = round(float(total_pulses) / pulses_per_litre, 3)
    except Exception:
        water_total_litres = None
    climate_days = sensors.get("climate_days") or []
    climate_today = climate_days[-1] if climate_days and climate_days[-1].get("date") == datetime.now().strftime("%Y-%m-%d") else {}
    payload["controller_meta"] = {
        "temp_c": sensors.get("temp_c"),
        "rh_pct": sensors.get("rh_pct"),
        # Today's (midnight to midnight) high and low, for the office tiles.
        "climate_today": {
            "date": climate_today.get("date"),
            "temp_max": climate_today.get("temp_max"),
            "temp_min": climate_today.get("temp_min"),
            "rh_max": climate_today.get("rh_max"),
            "rh_min": climate_today.get("rh_min"),
        } if climate_today else None,
        "temp_low_c": cfg.get("temp_low_c"),
        "temp_high_c": cfg.get("temp_high_c"),
        "temp_amber_margin_c": cfg.get("temp_amber_margin_c"),
        "rh_low_pct": cfg.get("rh_low_pct"),
        "rh_high_pct": cfg.get("rh_high_pct"),
        "rh_amber_margin_pct": cfg.get("rh_amber_margin_pct"),
        "climate_limits_updated_ts": cfg.get("climate_limits_updated_ts"),
        "water_lpm": sensors.get("water_lpm"),
        "water_low_lpm": cfg.get("water_low_lpm"),
        "water_total_litres": water_total_litres,
        "feed_kg": sensors.get("feed_kg"),
        "feed_kg_updated_ts": sensors.get("feed_kg_updated_ts"),
        "feed_noise_kg": sensors.get("feed_noise_kg"),
        "feed_movement": clean_feed_movement_state(sensors.get("feed_movement", {})),
        "feed_low_kg": cfg.get("feed_low_kg"),
        "feed_capacity_kg": cfg.get("feed_capacity_kg"),
        "lighting_on": sensors.get("lighting_on"),
        "lighting_enabled": lighting_enabled(cfg),
        "lighting_label": lighting_label_for(cfg),
        "lighting_last_changed_ts": sensors.get("lighting_last_changed_ts"),
        "last_sensor_ts": sensors.get("last_sensor_ts"),
        "device_status": sensors.get("device_status"),
        "pico_connected": sensors.get("pico_connected"),
        "augers": sensors.get("augers", {}),
        "auger_enabled": {
            "cross_auger": cfg.get("cross_auger_enabled", True),
            "auger_left": cfg.get("auger_left_enabled", True),
            "auger_right": cfg.get("auger_right_enabled", True),
        },
        "controller_alarms": sensors.get("controller_alarms", []),
        "controller_sync_version": state.get("state_version", 0),
        "controller_state_updated_ts": state.get("state_updated_ts"),
        "controller_entries_updated_ts": state.get("entries_updated_ts"),
        "last_seen_office_sync_version": state.get("last_seen_office_sync_version", 0),
        "last_backup_ts": state.get("last_backup_ts"),
        "last_backup_status": state.get("last_backup_status"),
        "app_branch": version.get("branch", "main"),
        "app_version": version.get("local_commit", "--"),
        "pico_local_hash": pico_status.get("local_hash", "--"),
        "pico_deployed_hash": pico_status.get("last_deployed_hash", "--"),
    }
    return payload


def sync_signature_payload(state):
    payload = sync_payload(state)
    controller_meta = payload.get("controller_meta")
    if isinstance(controller_meta, dict):
        filtered_meta = dict(controller_meta)
        volatile_keys = [
            "last_sensor_ts",
            "controller_sync_version",
            "controller_state_updated_ts",
        ]
        i = 0
        while i < len(volatile_keys):
            filtered_meta.pop(volatile_keys[i], None)
            i += 1
        payload["controller_meta"] = filtered_meta
    return payload


def sync_signature(state):
    try:
        return json.dumps(sync_signature_payload(state), sort_keys=True, separators=(",", ":"))
    except Exception:
        return ""


def dashboard_request(path, method="GET", payload=None, timeout=4):
    cfg = load_config()
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    token = str(cfg.get("sync_token", "") or "").strip()
    if token:
        headers["X-Controller-Token"] = token

    req = urllib.request.Request(
        cfg["dashboard_url"] + path,
        data=body,
        headers=headers,
        method=method,
    )
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_current_crop_hourly_history(shed_no, hourly=False):
    try:
        path = "/api/shed/%d/current-crop/hourly" % shed_no + ("?bucket=1" if hourly else "")
        with dashboard_request(path, method="GET") as resp:
            if not (200 <= int(resp.status) < 300):
                return {}
            payload = json.loads(resp.read().decode("utf-8"))
            mutate_state(lambda state: state.update({
                "last_dashboard_contact_ts": int(time.time()),
                "last_dashboard_status": "Office Reachable",
            }))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def post_move_to_dashboard(from_shed_no, dest_shed):
    try:
        with dashboard_request(
            "/shed/%d/entry/%d/move" % (from_shed_no, dest_shed),
            method="POST",
            payload={},
            timeout=6,
        ) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def fetch_mortality_from_dashboard(shed_no):
    try:
        with dashboard_request("/api/shed/%d/mortality" % shed_no, method="GET", timeout=6) as resp:
            if not (200 <= int(resp.status) < 300):
                return {}
            payload = json.loads(resp.read().decode("utf-8"))
            mutate_state(lambda state: state.update({
                "last_dashboard_contact_ts": int(time.time()),
                "last_dashboard_status": "Office Reachable",
            }))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def post_mortality_to_dashboard(shed_no, dest_shed, bird_loss, note="", date_text=""):
    try:
        with dashboard_request(
            "/api/shed/%d/mortality" % shed_no,
            method="POST",
            payload={
                "dest_shed": dest_shed,
                "bird_loss": bird_loss,
                "note": note,
                "date": date_text,
            },
            timeout=6,
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            ok = 200 <= int(resp.status) < 300 and isinstance(payload, dict) and bool(payload.get("ok"))
            if ok:
                mutate_state(lambda state: state.update({
                    "last_dashboard_contact_ts": int(time.time()),
                    "last_dashboard_status": "Office Reachable",
                }))
            return ok, (payload.get("message") if isinstance(payload, dict) else "")
    except Exception as exc:
        return False, "Mortality failed: %s" % exc


CLIMATE_LIMIT_KEYS = ["temp_low_c", "temp_high_c", "temp_amber_margin_c", "rh_low_pct", "rh_high_pct", "rh_amber_margin_pct"]


def adopt_office_climate_limits(limits):
    # Temperature / humidity limits match the office's: whichever side changed them
    # last wins. Applies the office's limits if they are newer than this controller's.
    if not isinstance(limits, dict):
        return False
    try:
        office_ts = int(limits.get("updated_ts"))
    except Exception:
        return False
    cfg = load_config()
    local_ts = cfg.get("climate_limits_updated_ts")
    if local_ts not in [None, ""] and office_ts <= int(local_ts):
        return False
    try:
        values = {key: float(limits.get(key)) for key in CLIMATE_LIMIT_KEYS}
    except Exception:
        return False
    if values["temp_low_c"] >= values["temp_high_c"] or values["rh_low_pct"] >= values["rh_high_pct"]:
        return False
    if values["temp_amber_margin_c"] < 0 or values["rh_amber_margin_pct"] < 0:
        return False
    cfg.update(values)
    cfg["climate_limits_updated_ts"] = office_ts
    save_config(cfg)
    record_controller_event("climate_limits_from_office", "Temperature / humidity limits updated from office", "")
    return True


def sync_climate_limits_to_office():
    # Send changed limits to the office straight away, without holding up the page.
    threading.Thread(target=lambda: auto_sync_if_changed(load_state()), daemon=True).start()


def adopt_office_pen_order(state, incoming):
    # A pen started on the office at a chosen end; take it when it is newer than ours.
    if not isinstance(incoming, dict) or not isinstance(incoming.get("order"), list):
        return
    try:
        office_ts = int(incoming.get("updated_ts") or 0)
        # Put the office's time on this Pi's clock, in case either clock is out.
        if incoming.get("now"):
            office_ts += int(time.time()) - int(incoming.get("now"))
        local_ts = int(state.get("pen_order_ts") or 0)
    except Exception:
        return
    order = [str(k) for k in incoming["order"]]
    if order != state.get("pen_order") and office_ts > local_ts + 2:
        state["pen_order"] = order
        state["pen_order_ts"] = office_ts


def pull_from_dashboard(state):
    cfg = load_config()

    try:
        with dashboard_request("/api/shed/%d/sync" % cfg["shed_no"], method="GET") as resp:
            if not (200 <= int(resp.status) < 300):
                state["last_sync_ts"] = int(time.time())
                state["last_sync_status"] = "Pull HTTP %d" % int(resp.status)
                state["last_dashboard_contact_ts"] = int(time.time())
                state["last_dashboard_status"] = "Office HTTP %d" % int(resp.status)
                save_state(state)
                return False, state["last_sync_status"]

            payload = json.loads(resp.read().decode("utf-8"))
            adopt_office_climate_limits(payload.get("climate_limits"))
            incoming = payload.get("entries", {})
            if isinstance(incoming, dict):
                state["entries"] = {}
                for key in incoming:
                    state["entries"][str(key)] = clean_entry_record(incoming.get(key, {}))
                state["entries_updated_ts"] = int(time.time())
            adopt_office_pen_order(state, payload.get("pen_order"))
            summary = payload.get("summary", {})
            if isinstance(summary, dict):
                state["dashboard_summary"] = {
                    "water_7to7": summary.get("water_7to7"),
                    "feed_7to7": summary.get("feed_7to7"),
                    "mortality_total": summary.get("mortality_total"),
                }
            try:
                state["last_seen_office_sync_version"] = int(payload.get("sync_version") or 0)
            except Exception:
                state["last_seen_office_sync_version"] = 0
            state["last_seen_office_sync_ts"] = payload.get("generated_ts")
            state["last_sync_ts"] = int(time.time())
            state["last_sync_status"] = "Pull OK"
            state["last_dashboard_contact_ts"] = int(time.time())
            state["last_dashboard_status"] = "Office Reachable"
            save_state(state)
            record_controller_event("office_pull", "Pulled latest office state", "Sync version %s" % state.get("last_seen_office_sync_version", 0))
            return True, state["last_sync_status"]
    except urllib.error.URLError as exc:
        state["last_sync_ts"] = int(time.time())
        state["last_sync_status"] = "Pull failed: %s" % exc
        state["last_dashboard_contact_ts"] = int(time.time())
        state["last_dashboard_status"] = "Office Unreachable"
        save_state(state)
        record_controller_event("office_pull_failed", "Office pull failed", str(exc), push_to_office=False)
        return False, state["last_sync_status"]
    except Exception as exc:
        state["last_sync_ts"] = int(time.time())
        state["last_sync_status"] = "Pull failed: %s" % exc
        state["last_dashboard_contact_ts"] = int(time.time())
        state["last_dashboard_status"] = "Office Unreachable"
        save_state(state)
        record_controller_event("office_pull_failed", "Office pull failed", str(exc), push_to_office=False)
        return False, state["last_sync_status"]


def maybe_refresh_from_dashboard(min_age_seconds=LOCAL_DASHBOARD_PULL_SECONDS):
    state = load_state()
    last_contact_ts = state.get("last_dashboard_contact_ts")
    now_ts = int(time.time())
    try:
        last_contact_ts = int(last_contact_ts) if last_contact_ts not in [None, ""] else None
    except Exception:
        last_contact_ts = None

    if last_contact_ts is None or (now_ts - last_contact_ts) >= int(min_age_seconds):
        pull_from_dashboard(state)


def maybe_heartbeat_to_dashboard(min_age_seconds=LOCAL_DASHBOARD_HEARTBEAT_SECONDS):
    state = load_state()
    last_push_ts = state.get("last_push_ts")
    now_ts = int(time.time())
    try:
        last_push_ts = int(last_push_ts) if last_push_ts not in [None, ""] else None
    except Exception:
        last_push_ts = None

    if last_push_ts is None or (now_ts - last_push_ts) >= int(min_age_seconds):
        push_to_dashboard(state, pull_back=False)


def background_sync_loop():
    while True:
        try:
            maybe_refresh_from_dashboard()
        except Exception:
            pass
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


def push_to_dashboard(state, pull_back=True):
    cfg = load_config()
    signature = sync_signature(state)

    try:
        with dashboard_request(
            "/api/shed/%d/sync" % cfg["shed_no"],
            method="POST",
            payload=sync_payload(state),
        ) as resp:
            ok = 200 <= int(resp.status) < 300
            state["last_sync_ts"] = int(time.time())
            state["last_sync_status"] = "Push OK" if ok else "Push HTTP %d" % int(resp.status)
            state["last_push_ts"] = int(time.time())
            state["last_push_status"] = state["last_sync_status"]
            state["last_dashboard_contact_ts"] = int(time.time())
            state["last_dashboard_status"] = "Office Reachable" if ok else "Office HTTP %d" % int(resp.status)
            if ok:
                state["last_auto_sync_signature"] = signature
            save_state(state)
            if ok:
                record_controller_event("office_push", "Pushed controller state", "State version %s" % state.get("state_version", 0))
    except urllib.error.URLError as exc:
        state["last_sync_ts"] = int(time.time())
        state["last_sync_status"] = "Push failed: %s" % exc
        state["last_push_ts"] = int(time.time())
        state["last_push_status"] = state["last_sync_status"]
        state["last_dashboard_contact_ts"] = int(time.time())
        state["last_dashboard_status"] = "Office Unreachable"
        save_state(state)
        record_controller_event("office_push_failed", "Office push failed", str(exc), push_to_office=False)
        return False, state["last_sync_status"]
    except Exception as exc:
        state["last_sync_ts"] = int(time.time())
        state["last_sync_status"] = "Push failed: %s" % exc
        state["last_push_ts"] = int(time.time())
        state["last_push_status"] = state["last_sync_status"]
        state["last_dashboard_contact_ts"] = int(time.time())
        state["last_dashboard_status"] = "Office Unreachable"
        save_state(state)
        record_controller_event("office_push_failed", "Office push failed", str(exc), push_to_office=False)
        return False, state["last_sync_status"]

    if ok and pull_back:
        pull_ok, pull_msg = pull_from_dashboard(state)
        if pull_ok:
            return True, "Push OK"
        return False, pull_msg

    return ok, state["last_sync_status"]


def auto_sync_if_changed(state, pull_back=False):
    signature = sync_signature(state)
    if not signature:
        return False, "No sync payload"
    if signature == state.get("last_auto_sync_signature", ""):
        return True, "No change"
    return push_to_dashboard(state, pull_back=pull_back)


def serial_available_ports():
    if serial is None:
        return []
    try:
        ports = serial.tools.list_ports.comports()
    except Exception:
        return []
    return [p.device for p in ports]


def serial_port_infos():
    if serial is None:
        return []
    try:
        return list(serial.tools.list_ports.comports())
    except Exception:
        return []


def port_looks_like_pico(port_info):
    if port_info is None:
        return False
    try:
        vid = int(getattr(port_info, "vid", 0) or 0)
    except Exception:
        vid = 0
    if vid == 0x2E8A:
        return True

    fields = [
        getattr(port_info, "manufacturer", ""),
        getattr(port_info, "product", ""),
        getattr(port_info, "description", ""),
        getattr(port_info, "interface", ""),
        getattr(port_info, "hwid", ""),
    ]
    blob = " ".join(str(field or "") for field in fields).lower()
    pico_markers = [
        "raspberry pi pico",
        "raspberry pi",
        " pico",
        "pico ",
        "rp2",
        "2e8a",
    ]
    return any(marker in blob for marker in pico_markers)


def detect_serial_port():
    cfg = load_config()
    configured = cfg["serial_port"]
    port_infos = serial_port_infos()
    configured_info = None
    pico_ports = []
    generic_serial_ports = []

    i = 0
    while i < len(port_infos):
        info = port_infos[i]
        device = getattr(info, "device", "")
        if device == configured:
            configured_info = info
        if "ttyACM" in device or "ttyUSB" in device or "cu.usbmodem" in device:
            generic_serial_ports.append(device)
            if port_looks_like_pico(info):
                pico_ports.append(device)
        i += 1

    if configured_info and port_looks_like_pico(configured_info):
        return configured
    if pico_ports:
        return pico_ports[0]
    return None if generic_serial_ports else configured


def fmt_ts(ts_value):
    if ts_value in [None, ""]:
        return "--"
    try:
        return datetime.fromtimestamp(int(ts_value)).strftime("%d %b %Y %H:%M:%S")
    except Exception:
        return "--"


def fmt_age_seconds(ts_value):
    if ts_value in [None, ""]:
        return "--"
    try:
        age = max(0, int(time.time()) - int(ts_value))
    except Exception:
        return "--"
    if age < 60:
        return "%ds ago" % age
    if age < 3600:
        return "%dm ago" % (age // 60)
    return "%dh %02dm ago" % (age // 3600, (age % 3600) // 60)


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
        if fmt == "f4":
            return f"{float(value):,.4f}"
        if fmt == "i":
            return f"{int(value):,d}"
        return str(value)
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


def feed_movement_display_context(sensors, entries):
    movement = clean_feed_movement_state((sensors or {}).get("feed_movement", {}))
    active_crop_id = active_crop_id_from_entries(entries if isinstance(entries, dict) else {})
    active_crop_epoch = active_crop_epoch_from_entries(entries if isinstance(entries, dict) else {}, active_crop_id)
    in_crop = active_crop_id not in [None, ""]
    out_feed_out = float(movement.get("out_of_crop_feed_out_kg") or 0.0)
    in_feed_out = float(movement.get("in_crop_feed_out_kg") or 0.0)
    out_feed_in = float(movement.get("out_of_crop_feed_in_kg") or 0.0)
    in_feed_in = float(movement.get("in_crop_feed_in_kg") or 0.0)
    total = out_feed_out + in_feed_out + out_feed_in + in_feed_in
    event_rows = []
    events = list(movement.get("events", []))
    events.sort(key=lambda row: int(row.get("ts") or 0), reverse=True)
    i = 0
    while i < len(events) and i < 100:
        event = events[i]
        i += 1
        movement_kind = str(event.get("movement") or "")
        crop_state = str(event.get("crop_state") or "")
        start_ts = event.get("start_ts") or event.get("ts")
        end_ts = event.get("end_ts") or event.get("ts")
        ts_label = fmt_ts(start_ts)
        try:
            if int(end_ts or 0) > int(start_ts or 0):
                ts_label = "%s - %s" % (fmt_ts(start_ts), fmt_ts(end_ts))
        except Exception:
            pass
        event_rows.append({
            "ts_label": ts_label,
            "movement_label": "Feed out" if movement_kind == "feed_out" else ("Feed in" if movement_kind == "bin_fill" else "--"),
            "kg_label": fmt_value(event.get("kg"), "f1"),
            "crop_state_label": "In Crop" if crop_state == "in_crop" else "Out Of Crop",
            "crop_state_class": "in-crop" if crop_state == "in_crop" else "out-crop",
            "crop_label": fmt_crop_code(event.get("crop_id")) if event.get("crop_id") not in [None, ""] else "--",
            "feed_kg_after_label": fmt_value(event.get("feed_kg_after"), "f0"),
        })
    return {
        "state_label": "In Crop" if in_crop else "Out Of Crop",
        "state_class": "in-crop" if in_crop else "out-crop",
        "crop_code": fmt_crop_code(active_crop_id, active_crop_epoch),
        "out_of_crop_feed_out": fmt_value(out_feed_out if out_feed_out >= 0.5 else None, "f1"),
        "in_crop_feed_out": fmt_value(in_feed_out if in_feed_out >= 0.5 else None, "f1"),
        "out_of_crop_feed_in": fmt_value(out_feed_in if out_feed_in >= 0.5 else None, "f1"),
        "in_crop_feed_in": fmt_value(in_feed_in if in_feed_in >= 0.5 else None, "f1"),
        "last_feed_kg": fmt_value(movement.get("last_feed_kg"), "f0"),
        "updated_age": fmt_age_seconds(movement.get("last_sample_ts") or movement.get("updated_ts")),
        "last_movement_label": {
            "feed_out": "Feed out",
            "bin_fill": "Feed in",
        }.get(str(movement.get("last_movement") or ""), "--"),
        "event_rows": event_rows,
        "has_activity": total >= 0.5,
    }


OVERVIEW_STAGE_WIDTH = 836


def shed_plan_layout(cfg):
    # Pixel positions for the overview's shed plan (836 px wide stage), worked out
    # from the layout chosen in Controller Config. "left"/"right" are as seen on screen.
    corner = cfg.get("layout_bin_corner", "top-left")
    bin_left = corner.endswith("left")
    bin_top = corner.startswith("top")
    door_left = cfg.get("layout_door_end", "left") == "left"
    front_left = cfg.get("layout_front_end", "left") == "left"

    bin_margin, other_margin = 170, 72
    shed_w = OVERVIEW_STAGE_WIDTH - bin_margin - other_margin
    shed_x = bin_margin if bin_left else other_margin
    shed_y, shed_h = 106, 330
    shed_right = shed_x + shed_w

    bin_size = 124
    bin_x = 16 if bin_left else OVERVIEW_STAGE_WIDTH - 16 - bin_size
    # Top-corner bins overhang the shed's top edge by 40px; bottom-corner bins mirror that
    # below the bottom edge, with their label above instead of below.
    bin_y = shed_y - 40 if bin_top else shed_y + shed_h - bin_size + 40
    pipe_y = bin_y + 59
    pipe_x = bin_x + bin_size - 2 if bin_left else shed_right - 4
    bin_label_x = min(max(0, bin_x + bin_size // 2 - 78), OVERVIEW_STAGE_WIDTH - 156)
    bin_label_y = bin_y + bin_size + 12 if bin_top else bin_y - 52

    # The door is always centred on its end wall.
    door_h = 100
    door_y = shed_y + (shed_h - door_h) // 2
    if door_left:
        door_x = shed_x - 2
        tick_x = shed_x - 18
        label_x = shed_x - 24 - 126
        label_align = "right"
    else:
        door_x = shed_right - 8
        tick_x = shed_right + 8
        label_x = shed_right + 24
        label_align = "left"

    cards_gap = 14
    temp_w = 200
    rh_w = 168
    water_w = shed_w - temp_w - rh_w - 2 * cards_gap

    return {
        "front_left": front_left,
        "shed_x": shed_x, "shed_y": shed_y, "shed_w": shed_w, "shed_h": shed_h,
        "inner_w": shed_w - 12,
        "bin_x": bin_x, "bin_y": bin_y,
        "pipe_x": pipe_x, "pipe_y": pipe_y,
        "bin_label_x": bin_label_x, "bin_label_y": bin_label_y,
        "door_x": door_x, "door_y": door_y, "door_h": door_h,
        "tick_x": tick_x, "label_x": label_x, "label_y": door_y + door_h // 2 - 11, "label_align": label_align,
        "temp_x": shed_x, "temp_w": temp_w,
        "rh_x": shed_x + temp_w + cards_gap, "rh_w": rh_w,
        "water_x": shed_x + temp_w + rh_w + 2 * cards_gap, "water_w": water_w,
        "front_label_x": shed_x + 6 if front_left else shed_right - 6 - 80,
        "rear_label_x": shed_right - 6 - 80 if front_left else shed_x + 6,
        "end_label_y": shed_y + shed_h + 8,
    }


def ordered_entry_keys(entries, pen_order, home_shed_no=None):
    # Pens keep the front-to-rear order they were added in; anything the office
    # added without a position goes to the rear in shed-number order. The shed's own
    # birds always sit at the rear: the pens nearest the door are the ones that move out.
    keys = [str(k) for k in (pen_order or []) if str(k) in entries]
    rest = sorted([k for k in entries.keys() if str(k) not in keys], key=lambda k: int(k) if str(k).isdigit() else 0)
    ordered = keys + rest
    if home_shed_no is not None:
        own = [k for k in ordered if entry_home_shed_no(k) == int(home_shed_no)]
        ordered = [k for k in ordered if k not in own] + own
    return ordered


def overview_pens(cfg, entries, pen_order=None, layout=None):
    layout = layout or shed_plan_layout(cfg)
    pen_area = layout["inner_w"]
    rows = []
    for key in ordered_entry_keys(entries, pen_order, cfg.get("shed_no")):
        try:
            dest_shed = int(key)
        except Exception:
            continue
        rec = clean_entry_record(entries.get(key, {}))
        if rec["bird_count"] <= 0:
            continue
        rows.append({
            "dest_shed": dest_shed,
            "name": entry_shed_label(dest_shed),
            # Shed number order for lists (Shed 6B sits straight after Shed 6).
            "number_order": (entry_home_shed_no(dest_shed) or dest_shed) * 1000 + dest_shed,
            "birds": rec["bird_count"],
            "birds_text": fmt_value(rec["bird_count"], "i"),
            "placed": max(int(rec.get("placed_bird_count") or 0), rec["bird_count"]),
            "placed_text": fmt_value(max(int(rec.get("placed_bird_count") or 0), rec["bird_count"]), "i"),
            "mortality_text": fmt_value(max(0, int(rec.get("placed_bird_count") or 0) - rec["bird_count"]), "i"),
            "can_move": entry_home_shed_no(dest_shed) != cfg["shed_no"] and rec["crop_active"] == 1,
        })
    # Pens are sized by birds placed, so the split stays put as mortality comes off,
    # and run wall to wall so each label sits in the middle of the pen you see.
    total = sum(row["placed"] for row in rows)
    x = 0.0
    i = 0
    while i < len(rows):
        width = pen_area * rows[i]["placed"] / total if total > 0 else 0
        left = x if layout["front_left"] else layout["inner_w"] - x - width
        rows[i]["left"] = int(round(left))
        rows[i]["width"] = int(round(width))
        # Dashed divider on the right of every pen except the one against the right wall.
        rows[i]["divided"] = i != (len(rows) - 1 if layout["front_left"] else 0)
        x += width
        i += 1
    return rows


def overview_pen_add_options(cfg, pens):
    present = set(pen["dest_shed"] for pen in pens)
    rows = []
    for dest_shed in ENTRY_SHED_NUMBERS:
        if dest_shed in present:
            continue
        rows.append({
            "dest_shed": dest_shed,
            "label": entry_shed_label(dest_shed),
            "is_home": entry_home_shed_no(dest_shed) == cfg["shed_no"],
        })
    return rows


def mortality_day_options(crop_epoch, now_ts=None):
    now = datetime.fromtimestamp(now_ts or time.time())
    today = now.date()
    start = today
    if crop_epoch not in [None, ""]:
        try:
            start = min(today, datetime.fromtimestamp(int(crop_epoch)).date())
        except Exception:
            start = today
    rows = []
    day = today
    while day >= start:
        offset = (today - day).days
        if offset == 0:
            label = "Today"
        elif offset == 1:
            label = "Yesterday"
        else:
            label = day.strftime("%a %d %b")
        if crop_epoch not in [None, ""]:
            label = "%s · day %d" % (label, (day - start).days)
        rows.append({"value": "" if offset == 0 else day.strftime("%Y-%m-%d"), "label": label})
        day = day - timedelta(days=1)
    return rows


def overview_climate(cfg, temp_c, sensors, now_ts):
    low = float(cfg.get("temp_low_c", 18.0))
    high = float(cfg.get("temp_high_c", 24.0))
    scale_low = low - 5.0
    scale_high = high + 5.0
    span = max(0.1, scale_high - scale_low)
    if temp_c is None:
        status = "none"
    elif temp_c < low:
        status = "low"
    elif temp_c > high:
        status = "high"
    else:
        status = "ok"
    dev = 0.0
    if status == "low":
        dev = low - temp_c
    elif status == "high":
        dev = temp_c - high
    colors = {
        "ok": ("#2f9e3a", "#1e6b16"),
        "low": ("#1676b8", "#0b5ea8"),
        "high": ("#f08a12", "#9a4b00"),
        "none": ("#9aa8b6", "#4a6078"),
    }
    if status == "low":
        short = "%.1f° low" % dev
        advice = "%.1f °C below target. Check the heaters." % dev
    elif status == "high":
        short = "%.1f° high" % dev
        advice = "%.1f °C above target. Check ventilation and heater settings." % dev
    elif status == "ok":
        short = "On target"
        advice = "Sensor updated %s." % fmt_age_seconds(sensors.get("last_sensor_ts"))
    else:
        short = "No reading"
        advice = "No temperature reading from the Pico."
    return {
        "temp_status": status,
        "temp_status_color": colors[status][0],
        "temp_status_text_color": colors[status][1],
        "temp_status_short": short,
        "temp_advice": advice,
        "temp_advice_color": "#4a6078" if status == "ok" else colors[status][1],
        "temp_scale_low": "%.0f °C" % scale_low,
        "temp_scale_high": "%.0f °C" % scale_high,
        "temp_target_text": "Target %s to %s °C" % (fmt_value(low, "f1"), fmt_value(high, "f1")),
        "temp_band_left": round((low - scale_low) * 100.0 / span, 1),
        "temp_band_width": round((high - low) * 100.0 / span, 1),
        "temp_marker_pct": None if temp_c is None else round(max(0.0, min(100.0, (temp_c - scale_low) * 100.0 / span)), 1),
    }


def overview_rh_gauge(cfg, rh_pct):
    low = float(cfg.get("rh_low_pct", 40.0))
    high = float(cfg.get("rh_high_pct", 80.0))
    scale_low = max(0.0, low - 15.0)
    scale_high = min(100.0, high + 15.0)
    span = max(0.1, scale_high - scale_low)
    if rh_pct is None:
        advice = ""
        short, short_color = "No reading", "#4a6078"
    elif rh_pct < low:
        advice = "Humidity %.0f%% below target." % (low - rh_pct)
        short, short_color = "%.0f%% low" % (low - rh_pct), "#0b5ea8"
    elif rh_pct > high:
        advice = "Humidity %.0f%% above target. Check ventilation." % (rh_pct - high)
        short, short_color = "%.0f%% high" % (rh_pct - high), "#9a4b00"
    else:
        advice = ""
        short, short_color = "On target", "#1e6b16"
    return {
        "rh_status_short": short,
        "rh_status_text_color": short_color,
        "rh_ok": rh_pct is not None and low <= rh_pct <= high,
        "rh_advice": advice,
        "rh_scale_low": "%.0f%%" % scale_low,
        "rh_scale_high": "%.0f%%" % scale_high,
        "rh_target_text": "Target %.0f to %.0f%% RH" % (low, high),
        "rh_band_left": round((low - scale_low) * 100.0 / span, 1),
        "rh_band_width": round((high - low) * 100.0 / span, 1),
        "rh_marker_pct": None if rh_pct is None else round(max(0.0, min(100.0, (rh_pct - scale_low) * 100.0 / span)), 1),
    }


def feed_fill_pct(feed_kg, capacity_kg):
    try:
        feed_kg = float(feed_kg)
        capacity_kg = float(capacity_kg)
    except Exception:
        return None
    if capacity_kg <= 0:
        return None
    return max(0.0, min(100.0, feed_kg * 100.0 / capacity_kg))


def build_home_context():
    cfg = load_config()
    state = load_state()
    entry = get_entry_for_dest(state, cfg["shed_no"])
    total_birds = total_birds_from_entries(state.get("entries", {}))
    active_crop_id = active_crop_id_from_entries(state.get("entries", {}))
    active_crop_epoch = active_crop_epoch_from_entries(state.get("entries", {}), active_crop_id)
    oldest_age_days = oldest_bird_age_days(state.get("entries", {}))
    allocation_summary = allocation_summary_text(cfg["shed_no"], state.get("entries", {}))
    sensors = state.get("sensors", default_sensor_state())
    now_ts = int(time.time())
    augers = ensure_augers_state(sensors)
    dashboard_summary = state.get("dashboard_summary", {})
    try:
        mortality_total_raw = int(dashboard_summary.get("mortality_total") or 0)
    except Exception:
        mortality_total_raw = 0
    birds_remaining_raw = total_birds if total_birds > 0 else 0
    birds_placed_raw = total_placed_birds_from_entries(state.get("entries", {})) if birds_remaining_raw > 0 else 0
    if birds_remaining_raw > 0 and mortality_total_raw > 0 and birds_placed_raw <= birds_remaining_raw:
        birds_placed_raw = birds_remaining_raw + mortality_total_raw
    elif birds_placed_raw <= 0 and birds_remaining_raw > 0:
        birds_placed_raw = birds_remaining_raw + mortality_total_raw
    birds_display = fmt_value(birds_remaining_raw if birds_remaining_raw > 0 else None, "i")
    if birds_placed_raw > 0:
        # Always placed first, live in brackets.
        birds_display = "%s (%s)" % (
            fmt_value(birds_placed_raw, "i"),
            fmt_value(birds_remaining_raw, "i"),
        )
    sync_status = state.get("last_sync_status", "") or "No sync yet"
    sync_class = "ok" if "OK" in sync_status else ("warn" if "No sync" in sync_status else "bad")
    push_status = state.get("last_push_status", "") or "Waiting"
    push_ok = "OK" in push_status
    push_class = recent_ok_class(state.get("last_push_ts"), push_ok, 60)
    ethernet_status = state.get("last_dashboard_status", "") or "Waiting"
    ethernet_ok = ethernet_status.startswith("Office Reachable")
    ethernet_class = recent_ok_class(state.get("last_dashboard_contact_ts"), ethernet_ok, 60)
    log_status = state.get("last_log_status", "") or "Waiting"
    log_ok = log_status.startswith("Log OK")
    log_class = recent_ok_class(state.get("last_log_ts"), log_ok, 15)

    try:
        water_lpm_f = float(sensors.get("water_lpm")) if sensors.get("water_lpm") is not None else None
    except Exception:
        water_lpm_f = None

    try:
        temp_c_f = float(sensors.get("temp_c")) if sensors.get("temp_c") is not None else None
    except Exception:
        temp_c_f = None
    try:
        rh_pct_f = float(sensors.get("rh_pct")) if sensors.get("rh_pct") is not None else None
    except Exception:
        rh_pct_f = None

    try:
        feed_kg_f = float(sensors.get("feed_kg")) if sensors.get("feed_kg") is not None else None
    except Exception:
        feed_kg_f = None

    temp_low_c = float(cfg.get("temp_low_c", 18.0))
    temp_high_c = float(cfg.get("temp_high_c", 24.0))
    temp_amber_margin_c = max(0.0, float(cfg.get("temp_amber_margin_c", 1.0)))
    rh_low_pct = float(cfg.get("rh_low_pct", 40.0))
    rh_high_pct = float(cfg.get("rh_high_pct", 80.0))
    rh_amber_margin_pct = max(0.0, float(cfg.get("rh_amber_margin_pct", 5.0)))
    if temp_c_f is None:
        temp_glow = "temp-red"
    elif temp_c_f < temp_low_c or temp_c_f > temp_high_c:
        temp_glow = "temp-red"
    elif abs(temp_c_f - temp_low_c) <= temp_amber_margin_c or abs(temp_c_f - temp_high_c) <= temp_amber_margin_c:
        temp_glow = "temp-warn"
    else:
        temp_glow = "temp-green"
    if rh_pct_f is None:
        rh_glow = "temp-red"
    elif rh_pct_f < rh_low_pct or rh_pct_f > rh_high_pct:
        rh_glow = "temp-red"
    elif abs(rh_pct_f - rh_low_pct) <= rh_amber_margin_pct or abs(rh_pct_f - rh_high_pct) <= rh_amber_margin_pct:
        rh_glow = "temp-warn"
    else:
        rh_glow = "temp-green"
    water_low_lpm = float(cfg.get("water_low_lpm", 0.1))
    feed_low_kg = float(cfg.get("feed_low_kg", 2000.0))

    water_glow = "flow-red" if (water_lpm_f is None or water_lpm_f < water_low_lpm) else "flow-green"
    feed_glow = "feed-red" if (feed_kg_f is None or feed_kg_f < feed_low_kg) else "feed-green"

    lighting_tile = None
    if lighting_enabled(cfg):
        lighting_tile = {
            "key": "lighting",
            "label": lighting_label_for(cfg),
            "status": lighting_status_text(sensors),
            "runtime": "",
            "last_run": "",
            "glow": lighting_glow_class(sensors),
        }
    auger_tiles = []
    active_auger_keys = enabled_auger_keys(cfg)
    i = 0
    while i < len(AUGER_DEFS):
        auger_key, label = AUGER_DEFS[i]
        label = auger_label_for(cfg, auger_key, label)
        if auger_key in active_auger_keys:
            auger = augers.get(auger_key, {})
            waiting_override = auger_is_waiting_override(auger_key, augers, active_auger_keys, cfg=cfg)
            tile = {
                "key": auger_key,
                "label": label,
                "status": "Waiting" if waiting_override else auger_status_text(auger),
                "runtime": "Off / waiting" if waiting_override else auger_runtime_text(auger, now_ts=now_ts),
                "last_run": auger_last_run_text(auger),
                "glow": "state-warn" if waiting_override else auger_glow_class(auger),
            }
            auger_tiles.append(tile)
        i += 1
    alarm_rows = build_alarm_rows(state)
    controller_alerts = []
    i = 0
    while i < len(alarm_rows):
        detail = alarm_rows[i].get("detail", "")
        title = alarm_rows[i].get("title", "")
        controller_alerts.append(("%s: %s" % (title, detail)).strip(": "))
        i += 1
    alarm_class = "bad" if alarm_rows else "ok"
    alarm_short = "Active" if alarm_rows else "OK"
    crop_class = "active" if active_crop_id is not None else "inactive"
    office_stale = not ethernet_ok or state.get("last_dashboard_contact_ts") in [None, ""]
    offline_banner = ""
    if office_stale:
        offline_banner = "Office sync is stale. Controller is running on local cached state."
    pico_warning_banner = pico_warning_banner_text(sensors, now_ts=now_ts)
    pico_recovery_banner = pico_recovery_banner_text(state, now_ts=now_ts)
    lighting_visible = True
    lighting_on = normalize_bool(sensors.get("lighting_on"))
    lighting_badge_class = "lighting-on" if lighting_on else "lighting-off"
    lighting_badge_text = "💡"

    layout = shed_plan_layout(cfg)
    pens = overview_pens(cfg, state.get("entries", {}), state.get("pen_order", []), layout)
    climate = overview_climate(cfg, temp_c_f, sensors, now_ts)
    climate.update(overview_rh_gauge(cfg, rh_pct_f))

    ctx = {
        "shed_no": cfg["shed_no"],
        "shed_display_name": shed_display_name_from_number(cfg["shed_no"]),
        "host_ips": host_ipv4_display(),
        "dashboard_url": cfg["dashboard_url"],
        "serial_port": detect_serial_port(),
        "refresh_seconds": max(0.25, float(cfg["touch_refresh_seconds"])),
        "sync_status": sync_status,
        "sync_class": sync_class,
        # Status only: the seconds-ago counter flickered on every poll. Sync timing is on the Health page.
        "sync_short": short_status_text("sync", sync_status),
        "push_status": push_status,
        "push_class": push_class,
        "push_short": short_status_text("push", push_status),
        "ethernet_status": ethernet_status,
        "ethernet_class": ethernet_class,
        "ethernet_short": short_status_text("ethernet", ethernet_status),
        "log_status": log_status,
        "log_class": log_class,
        "log_short": short_status_text("log", log_status),
        "sensor_class": sensor_status_class(sensors),
        "sensor_status_text": sensor_status_text(sensors),
        "sensor_status_short": short_status_text("pico", sensor_status_text(sensors)),
        "last_sync": fmt_ts(state.get("last_sync_ts")),
        "last_sync_age": fmt_age_seconds(state.get("last_sync_ts")),
        "last_sensor": fmt_ts(sensors.get("last_sensor_ts")),
        "last_sensor_age": fmt_age_seconds(sensors.get("last_sensor_ts")),
        "last_backup": fmt_ts(state.get("last_backup_ts")),
        "last_backup_age": fmt_age_seconds(state.get("last_backup_ts")),
        "last_office_age": fmt_age_seconds(state.get("last_dashboard_contact_ts")),
        "updated_at": fmt_ts(entry.get("updated_ts")),
        "started_at": fmt_ts(entry.get("placement_epoch")),
        "total_birds": fmt_value(total_birds if total_birds > 0 else None, "i"),
        "birds_display": birds_display,
        "oldest_bird_age": fmt_value(oldest_age_days, "i"),
        "allocation_summary": allocation_summary,
        "active_crop_id": active_crop_id,
        "active_crop_code": fmt_crop_code(active_crop_id, active_crop_epoch),
        "current_datetime": datetime.now().strftime("%d %b %Y %H:%M:%S"),
        "crop_class": crop_class,
        "temp_c": fmt_value(sensors.get("temp_c"), "f1"),
        "rh_pct": fmt_value(sensors.get("rh_pct"), "f0"),
        "temp_glow": temp_glow,
        "rh_glow": rh_glow,
        "water_lpm": fmt_value(sensors.get("water_lpm"), "f2"),
        "feed_kg": fmt_value(sensors.get("feed_kg"), "f0"),
        "water_7to7": fmt_value(dashboard_summary.get("water_7to7"), "f0"),
        "feed_7to7": fmt_value(dashboard_summary.get("feed_7to7"), "f1"),
        "mortality_total": fmt_value(dashboard_summary.get("mortality_total") if total_birds > 0 else None, "i"),
        "water_glow": water_glow,
        "feed_glow": feed_glow,
        "last_serial_line": sensors.get("last_serial_line", ""),
        "sensors": sensors,
        "entry": entry,
        "auger_tiles": auger_tiles,
        "auger_count": len(auger_tiles),
        "lighting_tile": lighting_tile,
        "pens": pens,
        "pens_signature": ",".join("%s:%s" % (pen["dest_shed"], pen["can_move"]) for pen in pens),
        "pen_add_options": overview_pen_add_options(cfg, pens),
        "mortality_days": mortality_day_options(active_crop_epoch, now_ts),
        "layout": layout,
        "feed_kg_live_display": fmt_value(sensors.get("feed_kg_live") if sensors.get("feed_kg_live") is not None else sensors.get("feed_kg"), "f0"),
        "feed_live_pct": feed_fill_pct(sensors.get("feed_kg_live") if sensors.get("feed_kg_live") is not None else feed_kg_f, cfg.get("feed_capacity_kg")),
        "clock_hm": datetime.now().strftime("%H:%M"),
        "crop_subtitle": ("%s birds · Day %s" % (birds_display, fmt_value(oldest_age_days, "i"))) if active_crop_id is not None else "No active crop",
        "header_birds": ("%s birds" % birds_display) if active_crop_id is not None else "No active crop",
        "header_day": ("Day %s" % fmt_value(oldest_age_days, "i")) if active_crop_id is not None else "",
        "overview_chip_ok": not alarm_rows and climate["temp_status"] == "ok",
        "overview_chip_text": ("Shed on target" if not alarm_rows and climate["temp_status"] == "ok" else ("%d alarm%s active" % (len(alarm_rows), "" if len(alarm_rows) == 1 else "s") if alarm_rows else "Shed needs a look")),
        "climate_today": climate_today_display(sensors, now_ts),
        "feed_capacity_kg": fmt_value(cfg.get("feed_capacity_kg"), "f0"),
        "controller_alerts": controller_alerts,
        "alarm_count": len(alarm_rows),
        "alarm_class": alarm_class,
        "alarm_short": alarm_short,
        "offline_banner": offline_banner,
        "pico_warning_banner": pico_warning_banner,
        "pico_recovery_banner": pico_recovery_banner,
        "lighting_visible": lighting_visible,
        "lighting_on": lighting_on,
        "lighting_badge_class": lighting_badge_class,
        "lighting_badge_text": lighting_badge_text,
        "office_stale": office_stale,
        "state_version": state.get("state_version", 0),
        "state_updated_at": fmt_ts(state.get("state_updated_ts")),
        "state_updated_age": fmt_age_seconds(state.get("state_updated_ts")),
        "last_seen_office_sync_version": state.get("last_seen_office_sync_version", 0),
        "last_seen_office_sync_at": fmt_ts(state.get("last_seen_office_sync_ts")),
        "last_seen_office_sync_age": fmt_age_seconds(state.get("last_seen_office_sync_ts")),
    }
    ctx.update(climate)
    return ctx


def build_water_stream_payload():
    cfg = load_config()
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())

    try:
        water_lpm_f = float(sensors.get("water_lpm")) if sensors.get("water_lpm") is not None else None
    except Exception:
        water_lpm_f = None

    water_low_lpm = float(cfg.get("water_low_lpm", 0.1))
    water_glow = "flow-red" if (water_lpm_f is None or water_lpm_f < water_low_lpm) else "flow-green"

    return {
        "water_lpm": fmt_value(sensors.get("water_lpm"), "f2"),
        "water_glow": water_glow,
        "last_sensor": fmt_ts(sensors.get("last_sensor_ts")),
        "ts": int(time.time()),
    }


def sensor_status_class(sensors):
    if pico_frozen(sensors):
        return "bad"
    if sensors.get("pico_connected"):
        return "ok"
    if sensors.get("last_sensor_ts"):
        return "warn"
    return "bad"


def sensor_status_text(sensors):
    if pico_frozen(sensors):
        if serial_error_is_current(sensors):
            return "Pico USB Error"
        reader_age = serial_reader_age_seconds(sensors)
        if reader_age is None or reader_age > max(STALE_SENSOR_SECONDS, SERIAL_READER_HEARTBEAT_SECONDS * 3):
            return "Serial Reader Stalled"
        return "Pico Frozen"
    if sensors.get("pico_connected"):
        return "USB Connected"
    return "USB Disconnected"


def sensor_age_seconds(sensors, now_ts=None):
    if now_ts is None:
        now_ts = int(time.time())
    last_sensor_ts = sensors.get("last_sensor_ts")
    if last_sensor_ts in [None, ""]:
        return None
    try:
        return max(0, int(now_ts) - int(last_sensor_ts))
    except Exception:
        return None


def serial_reader_age_seconds(sensors, now_ts=None):
    if now_ts is None:
        now_ts = int(time.time())
    heartbeat_ts = sensors.get("serial_reader_heartbeat_ts")
    if heartbeat_ts in [None, ""]:
        return None
    try:
        return max(0, int(now_ts) - int(heartbeat_ts))
    except Exception:
        return None


def serial_error_is_current(sensors):
    error_ts = sensors.get("serial_reader_error_ts")
    last_sensor_ts = sensors.get("last_sensor_ts")
    try:
        error_ts = int(error_ts) if error_ts not in [None, ""] else None
    except Exception:
        error_ts = None
    try:
        last_sensor_ts = int(last_sensor_ts) if last_sensor_ts not in [None, ""] else None
    except Exception:
        last_sensor_ts = None
    return error_ts is not None and (last_sensor_ts is None or error_ts >= last_sensor_ts)


def pico_frozen(sensors, stale_after_s=STALE_SENSOR_SECONDS, now_ts=None):
    sensor_age = sensor_age_seconds(sensors, now_ts=now_ts)
    return sensor_age is not None and sensor_age > int(stale_after_s)


def pico_freeze_diagnosis(sensors, now_ts=None):
    if now_ts is None:
        now_ts = int(time.time())
    if not pico_frozen(sensors, now_ts=now_ts):
        return ""

    status = str(sensors.get("serial_reader_status") or "").strip()
    error = str(sensors.get("serial_reader_error") or "").strip()
    port = str(sensors.get("serial_reader_port") or "").strip()
    reader_age = serial_reader_age_seconds(sensors, now_ts=now_ts)

    if serial_error_is_current(sensors) and error:
        return "Pi serial reader hit %s%s." % (error, (" on %s" % port) if port else "")
    if reader_age is None:
        return "Pi serial reader has not reported a heartbeat yet."
    if reader_age > max(STALE_SENSOR_SECONDS, SERIAL_READER_HEARTBEAT_SECONDS * 3):
        return "Pi serial reader heartbeat is stale for %s." % fmt_duration_short(reader_age)
    if status:
        return "Pi serial reader is alive: %s." % status
    return ""


def pico_warning_banner_text(sensors, now_ts=None):
    sensor_age = sensor_age_seconds(sensors, now_ts=now_ts)
    if sensor_age is None or sensor_age <= STALE_SENSOR_SECONDS:
        return ""
    diagnosis = pico_freeze_diagnosis(sensors, now_ts=now_ts)
    suffix = " %s" % diagnosis if diagnosis else ""
    return "Pico frozen. No sensor update received for %s.%s" % (fmt_age_seconds(sensors.get("last_sensor_ts")), suffix)


def pico_trace_summary(sensors):
    parts = []
    checkpoint = str(sensors.get("pico_checkpoint") or "").strip()
    if checkpoint:
        checkpoint_ts = fmt_ts(sensors.get("pico_checkpoint_ts"))
        if checkpoint_ts != "--":
            parts.append("Last checkpoint %s at %s" % (checkpoint, checkpoint_ts))
        else:
            parts.append("Last checkpoint %s" % checkpoint)
    reset_cause = str(sensors.get("pico_reset_cause") or "").strip()
    if reset_cause:
        parts.append("Reset %s" % reset_cause)
    boot_count = sensors.get("pico_boot_count")
    if boot_count not in [None, ""]:
        parts.append("Boot %s" % boot_count)
    reader_status = str(sensors.get("serial_reader_status") or "").strip()
    if reader_status:
        reader_age = fmt_age_seconds(sensors.get("serial_reader_heartbeat_ts"))
        parts.append("Serial %s%s" % (reader_status, (" %s" % reader_age) if reader_age != "--" else ""))
    reader_error = str(sensors.get("serial_reader_error") or "").strip()
    if serial_error_is_current(sensors) and reader_error:
        parts.append("Serial error %s" % reader_error)
    return " • ".join(parts)


def pico_recovery_detail(state, reason):
    sensors = state.get("sensors", default_sensor_state())
    parts = [str(reason or "").strip()]
    sensor_age = fmt_age_seconds(sensors.get("last_sensor_ts"))
    if sensor_age != "--":
        parts.append("Last sensor %s" % sensor_age)
    trace = pico_trace_summary(sensors)
    if trace:
        parts.append(trace)
    diagnosis = pico_freeze_diagnosis(sensors)
    if diagnosis:
        parts.append(diagnosis)
    last_line = str(sensors.get("last_serial_line") or "").strip()
    if last_line:
        if len(last_line) > 240:
            last_line = last_line[:237] + "..."
        parts.append("Last serial line: %s" % last_line)
    return " | ".join([part for part in parts if part])


def pico_recovery_banner_text(state, now_ts=None):
    now_ts = int(time.time()) if now_ts is None else int(now_ts)
    status = str(state.get("last_pico_recovery_status") or "").strip()
    result_ts = state.get("last_pico_recovery_result_ts")
    sensors = state.get("sensors", default_sensor_state())
    if not status or result_ts in [None, ""]:
        return ""
    if not bool(state.get("pending_pico_update_recovery")) and not pico_frozen(sensors, now_ts=now_ts):
        return ""
    try:
        result_ts = int(result_ts)
    except Exception:
        return ""
    if max(0, now_ts - result_ts) > 24 * 60 * 60:
        return ""
    return "Pico auto recovery at %s. %s" % (fmt_ts(result_ts), status)


def pico_auto_recovery_due(state, now_ts=None):
    now_ts = int(time.time()) if now_ts is None else int(now_ts)
    sensors = state.get("sensors", default_sensor_state())
    if not pico_frozen(sensors, stale_after_s=PICO_AUTO_RECOVERY_FREEZE_SECONDS, now_ts=now_ts):
        return False
    last_attempt_ts = state.get("last_pico_recovery_attempt_ts")
    try:
        last_attempt_ts = int(last_attempt_ts) if last_attempt_ts not in [None, ""] else None
    except Exception:
        last_attempt_ts = None
    if last_attempt_ts is None:
        return True
    return (now_ts - last_attempt_ts) >= int(PICO_AUTO_RECOVERY_COOLDOWN_SECONDS)


def pico_post_update_recovery_due(state, now_ts=None):
    now_ts = int(time.time()) if now_ts is None else int(now_ts)
    if not bool(state.get("pending_pico_update_recovery")):
        return False
    set_ts = state.get("pending_pico_update_recovery_set_ts")
    try:
        set_ts = int(set_ts) if set_ts not in [None, ""] else None
    except Exception:
        set_ts = None
    if set_ts is None:
        return False
    if (now_ts - set_ts) < int(PICO_POST_UPDATE_RECOVERY_WAIT_SECONDS):
        return False

    sensors = state.get("sensors", default_sensor_state())
    last_sensor_ts = sensors.get("last_sensor_ts")
    try:
        last_sensor_ts = int(last_sensor_ts) if last_sensor_ts not in [None, ""] else None
    except Exception:
        last_sensor_ts = None
    if last_sensor_ts is not None and last_sensor_ts >= set_ts:
        return False
    return True


def update_water_history_samples(sensors, total_pulses, now_ts):
    samples = sensors.get("water_history_samples")
    if not isinstance(samples, list):
        samples = []

    clean_samples = []
    cutoff_ts = int(now_ts) - WATER_ALARM_HISTORY_KEEP_SECONDS
    i = 0
    while i < len(samples):
        sample = samples[i]
        i += 1
        if not isinstance(sample, dict):
            continue
        try:
            sample_ts = int(sample.get("ts"))
            sample_total = int(sample.get("total_pulses"))
        except Exception:
            continue
        if sample_ts < cutoff_ts:
            continue
        clean_samples.append({
            "ts": sample_ts,
            "total_pulses": sample_total,
        })

    append_sample = True
    if clean_samples:
        last_sample = clean_samples[-1]
        if (
            int(now_ts) - int(last_sample.get("ts", 0)) < WATER_ALARM_SNAPSHOT_SECONDS
            and int(total_pulses) == int(last_sample.get("total_pulses", 0))
        ):
            append_sample = False

    if append_sample:
        clean_samples.append({
            "ts": int(now_ts),
            "total_pulses": int(total_pulses),
        })

    sensors["water_history_samples"] = clean_samples


def water_window_stats(sensors, start_ts, end_ts, pulses_per_litre):
    if start_ts >= end_ts or pulses_per_litre <= 0:
        return None

    samples = sensors.get("water_history_samples")
    if not isinstance(samples, list) or len(samples) < 2:
        return None

    clean_samples = []
    i = 0
    while i < len(samples):
        sample = samples[i]
        i += 1
        if not isinstance(sample, dict):
            continue
        try:
            sample_ts = int(sample.get("ts"))
            sample_total = int(sample.get("total_pulses"))
        except Exception:
            continue
        clean_samples.append({
            "ts": sample_ts,
            "total_pulses": sample_total,
        })

    if len(clean_samples) < 2:
        return None

    start_sample = None
    end_sample = None
    i = 0
    while i < len(clean_samples):
        sample = clean_samples[i]
        sample_ts = sample["ts"]
        if sample_ts <= start_ts:
            start_sample = sample
        if sample_ts <= end_ts:
            end_sample = sample
        else:
            if end_sample is None:
                end_sample = sample
            break
        i += 1

    if start_sample is None:
        start_sample = clean_samples[0]
    if end_sample is None:
        end_sample = clean_samples[-1]

    try:
        observed_elapsed_s = max(0, int(end_sample["ts"]) - int(start_sample["ts"]))
        pulse_delta = max(0, int(end_sample["total_pulses"]) - int(start_sample["total_pulses"]))
    except Exception:
        return None

    requested_elapsed_s = max(1, int(end_ts) - int(start_ts))
    if observed_elapsed_s < int(requested_elapsed_s * 0.8):
        return None

    litres = float(pulse_delta) / float(pulses_per_litre)
    avg_lpm = (litres / float(observed_elapsed_s)) * 60.0 if observed_elapsed_s > 0 else 0.0
    return {
        "litres": litres,
        "avg_lpm": avg_lpm,
        "elapsed_s": observed_elapsed_s,
    }


def water_alarm_metrics(sensors, cfg, now_ts=None):
    if now_ts is None:
        now_ts = int(time.time())
    if pico_frozen(sensors, now_ts=now_ts):
        return None

    try:
        pulses_per_litre = float(cfg.get("water_pulses_per_litre", 450.0))
    except Exception:
        pulses_per_litre = 450.0
    if pulses_per_litre <= 0:
        return None

    try:
        water_low_lpm = float(cfg.get("water_low_lpm", 0.1))
    except Exception:
        water_low_lpm = 0.1

    recent_stats = water_window_stats(
        sensors,
        int(now_ts) - WATER_ALARM_WINDOW_SECONDS,
        int(now_ts),
        pulses_per_litre,
    )
    if not recent_stats:
        return None

    baseline_stats = water_window_stats(
        sensors,
        int(now_ts) - WATER_ALARM_WINDOW_SECONDS - WATER_ALARM_BASELINE_SECONDS,
        int(now_ts) - WATER_ALARM_WINDOW_SECONDS,
        pulses_per_litre,
    )
    if not baseline_stats:
        return None

    baseline_avg_lpm = float(baseline_stats["avg_lpm"])
    recent_avg_lpm = float(recent_stats["avg_lpm"])
    expected_recent_litres = baseline_avg_lpm * (float(WATER_ALARM_WINDOW_SECONDS) / 60.0)
    return {
        "recent_avg_lpm": recent_avg_lpm,
        "baseline_avg_lpm": baseline_avg_lpm,
        "recent_litres": float(recent_stats["litres"]),
        "expected_recent_litres": expected_recent_litres,
        "water_low_lpm": water_low_lpm,
        "low_lpm_triggered": recent_avg_lpm < water_low_lpm,
        "consumption_drop_triggered": (
            baseline_avg_lpm >= max(water_low_lpm, 0.1)
            and recent_avg_lpm <= baseline_avg_lpm * WATER_ALARM_MIN_DROP_RATIO
        ),
    }


def recent_ok_class(ts_value, ok, stale_after_s, unknown_warn=True):
    if not ok:
        return "bad"
    if ts_value in [None, ""]:
        return "warn" if unknown_warn else "bad"
    try:
        age_s = max(0, int(time.time()) - int(ts_value))
    except Exception:
        return "warn" if unknown_warn else "bad"
    return "ok" if age_s <= stale_after_s else "warn"


def short_status_text(kind, status_text):
    text = str(status_text or "").strip()
    upper = text.upper()

    if kind == "sync":
        if "OK" in upper:
            return "OK"
        if "NO SYNC" in upper or "WAIT" in upper:
            return "Waiting"
        return "Error"

    if kind == "pico":
        if "FROZEN" in upper:
            return "Frozen"
        if "NOT CONNECTED" in upper or "DISCONNECTED" in upper:
            return "Disconnected"
        if "CONNECTED" in upper:
            return "Connected"
        return "Disconnected"

    if kind == "log":
        if upper.startswith("LOG OK"):
            return "Ready"
        if "WAIT" in upper:
            return "Waiting"
        return "Error"

    if kind == "ethernet":
        if upper.startswith("OFFICE REACHABLE"):
            return "Online"
        if "WAIT" in upper:
            return "Waiting"
        return "Offline"

    if kind == "push":
        if "OK" in upper:
            return "OK"
        if "WAIT" in upper or "NO CHANGE" in upper:
            return "Waiting"
        return "Error"

    return text or "--"


def build_alarm_rows(state):
    sensors = state.get("sensors", default_sensor_state())
    cfg = load_config()
    rows = []
    now_ts = int(time.time())

    def add_row(key, severity, title, detail):
        rows.append({
            "alarm_key": key,
            "severity": severity,
            "title": title,
            "detail": detail,
        })

    last_sensor_ts = sensors.get("last_sensor_ts")
    if last_sensor_ts in [None, ""]:
        add_row("sensor_missing", "bad", "Sensor Data Missing", "No Pico sensor packet has been received yet.")
    else:
        sensor_age = sensor_age_seconds(sensors, now_ts=now_ts)
        if sensor_age is not None and sensor_age > STALE_SENSOR_SECONDS:
            detail = "No Pico update has been received for %ds." % sensor_age
            trace_summary = pico_trace_summary(sensors)
            if trace_summary:
                detail = "%s %s." % (detail, trace_summary)
            add_row("pico_frozen", "bad", "Pico Frozen", detail)

    water_alarm = water_alarm_metrics(sensors, cfg, now_ts=now_ts)
    if water_alarm and water_alarm.get("low_lpm_triggered"):
        add_row(
            "water_low_lpm",
            "warn",
            "Low Water LPM",
            "Last 10 minutes averaged %.2f L/PM, below the %.2f L/PM threshold."
            % (
                water_alarm["recent_avg_lpm"],
                water_alarm["water_low_lpm"],
            ),
        )
    if water_alarm and water_alarm.get("consumption_drop_triggered"):
        add_row(
            "water_consumption_drop",
            "warn",
            "Water Consumption Drop",
            "Last 10 minutes averaged %.2f L/PM versus %.2f L/PM baseline. Recent use %.1f L vs expected %.1f L."
            % (
                water_alarm["recent_avg_lpm"],
                water_alarm["baseline_avg_lpm"],
                water_alarm["recent_litres"],
                water_alarm["expected_recent_litres"],
            ),
        )

    last_office_ts = state.get("last_dashboard_contact_ts")
    if last_office_ts in [None, ""]:
        add_row("office_missing", "warn", "Office Link Unknown", "The controller has not contacted the office dashboard yet.")
    else:
        try:
            office_age = max(0, now_ts - int(last_office_ts))
            if office_age > STALE_OFFICE_SECONDS:
                add_row("office_stale", "bad", "Office Link Stale", "Last office contact was %ds ago." % office_age)
        except Exception:
            pass

    last_log_ts = state.get("last_log_ts")
    if last_log_ts in [None, ""]:
        add_row("log_missing", "warn", "Logging Unknown", "No local sensor log has been written yet.")
    else:
        try:
            log_age = max(0, now_ts - int(last_log_ts))
            if log_age > STALE_LOG_SECONDS:
                add_row("log_stale", "warn", "Logging Stale", "Last local log write was %ds ago." % log_age)
        except Exception:
            pass

    push_status = str(state.get("last_push_status", "") or "")
    if push_status and "OK" not in push_status and "Waiting" not in push_status:
        add_row("push_failed", "bad", "Push Failed", push_status)

    backup_status = str(state.get("last_backup_status", "") or "")
    if backup_status.startswith("Backup failed"):
        add_row("backup_failed", "bad", "Backup Failed", backup_status)

    controller_alarms = normalize_controller_alarms(sensors.get("controller_alarms", []))
    i = 0
    while i < len(controller_alarms):
        alarm = controller_alarms[i]
        add_row(alarm.get("alarm_key", "controller_alarm"), "bad", "Controller Alarm", alarm.get("message", ""))
        i += 1

    i = 0
    while i < len(sensors.get("alarms", [])):
        add_row("sensor_alarm_%d" % i, "warn", "Sensor Warning", str(sensors["alarms"][i]))
        i += 1

    return rows


def alarm_history_signature(row):
    alarm_key = str(row.get("alarm_key", "") or "").strip()
    title = str(row.get("title", "") or "").strip()
    detail = str(row.get("detail", "") or "").strip()
    if alarm_key.startswith("sensor_alarm_"):
        return "sensor_warning:%s" % detail
    return alarm_key or title or detail


def alarm_snapshot_rows(rows):
    out = []
    if not isinstance(rows, list):
        return out
    i = 0
    while i < len(rows):
        row = rows[i]
        i += 1
        if not isinstance(row, dict):
            continue
        out.append({
            "alarm_key": str(row.get("alarm_key", "") or "").strip(),
            "severity": str(row.get("severity", "") or "").strip(),
            "title": str(row.get("title", "") or "").strip(),
            "detail": str(row.get("detail", "") or "").strip(),
        })
    return out


def reconcile_alarm_history(state, now_ts=None):
    if now_ts is None:
        now_ts = int(time.time())
    current_rows = alarm_snapshot_rows(build_alarm_rows(state))
    previous_rows = alarm_snapshot_rows(state.get("last_alarm_snapshot", []))

    current_map = {}
    i = 0
    while i < len(current_rows):
        row = current_rows[i]
        current_map[alarm_history_signature(row)] = row
        i += 1

    previous_map = {}
    i = 0
    while i < len(previous_rows):
        row = previous_rows[i]
        previous_map[alarm_history_signature(row)] = row
        i += 1

    for signature, row in current_map.items():
        if signature not in previous_map:
            append_alarm_history({
                "ts": int(now_ts),
                "event_type": "activated",
                "alarm_key": row.get("alarm_key", ""),
                "severity": row.get("severity", ""),
                "title": row.get("title", ""),
                "detail": row.get("detail", ""),
            })

    for signature, row in previous_map.items():
        if signature not in current_map:
            append_alarm_history({
                "ts": int(now_ts),
                "event_type": "cleared",
                "alarm_key": row.get("alarm_key", ""),
                "severity": row.get("severity", ""),
                "title": row.get("title", ""),
                "detail": row.get("detail", ""),
            })

    state["last_alarm_snapshot"] = current_rows


def current_alarm_snapshot(state):
    return alarm_snapshot_rows(state.get("last_alarm_snapshot", []))


def update_water_from_pulses(sensors, now_ts):
    raw = sensors.get("raw", {})
    try:
        total_pulses = raw.get("total_flow_pulses")
        if total_pulses in [None, ""]:
            return
        total_pulses = int(total_pulses)
    except Exception:
        return

    cfg = load_config()
    try:
        pulses_per_litre = float(cfg.get("water_pulses_per_litre", 450.0))
    except Exception:
        pulses_per_litre = 450.0
    if pulses_per_litre <= 0:
        return

    prev_total = sensors.get("flow_prev_total_pulses")
    prev_ts = sensors.get("flow_prev_ts")
    samples = sensors.get("flow_rate_samples")
    if not isinstance(samples, list):
        samples = []
    sensors["flow_total_pulses"] = total_pulses
    update_water_history_samples(sensors, total_pulses, now_ts)
    if prev_total is not None and prev_ts is not None:
        try:
            pulse_delta = int(total_pulses) - int(prev_total)
            elapsed_s = max(1, int(now_ts) - int(prev_ts))
        except Exception:
            pulse_delta = None
            elapsed_s = None

        if pulse_delta is not None and pulse_delta >= 0 and elapsed_s is not None:
            sensors["water_last_pulse_delta"] = pulse_delta
            sensors["water_last_elapsed_s"] = elapsed_s
            litres_per_second = (float(pulse_delta) / pulses_per_litre) / float(elapsed_s)
            raw_lpm = round(litres_per_second * 60.0, 2)
            sensors["water_lpm_raw"] = raw_lpm
            samples.append({
                "ts": int(now_ts),
                "pulse_delta": pulse_delta,
                "elapsed_s": elapsed_s,
            })
            cutoff_ts = int(now_ts) - WATER_LPM_AVERAGE_SECONDS
            kept_samples = []
            window_pulses = 0
            window_elapsed_s = 0
            i = 0
            while i < len(samples):
                sample = samples[i]
                i += 1
                try:
                    sample_ts = int(sample.get("ts"))
                    sample_pulse_delta = max(0, int(sample.get("pulse_delta", 0)))
                    sample_elapsed_s = max(1, int(sample.get("elapsed_s", 1)))
                except Exception:
                    continue
                if sample_ts < cutoff_ts:
                    continue
                kept_samples.append({
                    "ts": sample_ts,
                    "pulse_delta": sample_pulse_delta,
                    "elapsed_s": sample_elapsed_s,
                })
                window_pulses += sample_pulse_delta
                window_elapsed_s += sample_elapsed_s
            sensors["flow_rate_samples"] = kept_samples
            if window_elapsed_s > 0:
                window_litres_per_second = (float(window_pulses) / pulses_per_litre) / float(window_elapsed_s)
                sensors["water_lpm"] = round(window_litres_per_second * 60.0, 2)
            else:
                sensors["water_lpm"] = raw_lpm

    sensors["flow_prev_total_pulses"] = total_pulses
    sensors["flow_prev_ts"] = now_ts


def update_feed_diagnostics(sensors, kept_samples, scale=None, now_ts=None):
    now_ts = int(time.time()) if now_ts is None else int(now_ts)
    raw_values = []
    cutoff_ts = now_ts - FEED_DIAGNOSTIC_NOISE_SECONDS
    i = 0
    while i < len(kept_samples):
        try:
            sample_ts = int(kept_samples[i].get("ts"))
            if sample_ts >= cutoff_ts:
                raw_values.append(float(kept_samples[i].get("raw")))
        except Exception:
            pass
        i += 1

    if len(raw_values) < 2:
        sensors["feed_noise_raw_units"] = None
        sensors["feed_noise_kg"] = None
        sensors["feed_stability_label"] = "Waiting for samples"
    else:
        noise_raw = max(raw_values) - min(raw_values)
        sensors["feed_noise_raw_units"] = round(noise_raw, 1)
        try:
            noise_kg = abs(float(scale)) * noise_raw
        except Exception:
            noise_kg = None
        sensors["feed_noise_kg"] = round(noise_kg, 1) if noise_kg is not None else None
        if noise_kg is None:
            sensors["feed_stability_label"] = "Raw signal active"
        elif noise_kg <= FEED_STABLE_NOISE_KG:
            sensors["feed_stability_label"] = "Stable"
        else:
            sensors["feed_stability_label"] = "Moving"

    try:
        settling_until_ts = int(sensors.get("feed_refill_settling_until_ts"))
    except Exception:
        settling_until_ts = None
    if settling_until_ts is not None and now_ts >= settling_until_ts:
        sensors["feed_refill_settling_until_ts"] = None


def append_feed_published_sample(sensors, feed_kg, averaged_raw, now_ts):
    samples = sensors.get("feed_published_samples")
    if not isinstance(samples, list):
        samples = []
    kept = []
    cutoff_ts = int(now_ts) - FEED_DIAGNOSTIC_HISTORY_SECONDS
    i = 0
    while i < len(samples):
        sample = samples[i]
        i += 1
        try:
            sample_ts = int(sample.get("ts"))
            sample_kg = float(sample.get("kg"))
            sample_raw = float(sample.get("raw"))
        except Exception:
            continue
        if sample_ts < cutoff_ts:
            continue
        kept.append({
            "ts": sample_ts,
            "kg": round(sample_kg, 1),
            "raw": round(sample_raw, 1),
        })
    kept.append({
        "ts": int(now_ts),
        "kg": round(float(feed_kg), 1),
        "raw": round(float(averaged_raw), 1),
    })
    sensors["feed_published_samples"] = kept[-1440:]


def update_feed_movement_state(sensors, feed_kg, sample_ts, entries=None):
    movement = clean_feed_movement_state(sensors.get("feed_movement", {}))
    try:
        feed_kg = float(feed_kg)
        sample_ts = int(sample_ts)
    except Exception:
        sensors["feed_movement"] = movement
        return False

    last_sample_ts = movement.get("last_sample_ts")
    if last_sample_ts is not None and sample_ts <= last_sample_ts:
        sensors["feed_movement"] = movement
        return False

    if movement.get("baseline_kg") is None:
        movement["baseline_kg"] = feed_kg
    if movement.get("low_kg") is None:
        movement["low_kg"] = feed_kg

    try:
        noise_kg = max(0.0, float(sensors.get("feed_noise_kg") or 0.0))
    except Exception:
        noise_kg = 0.0
    min_drop_kg = max(FEED_MOVEMENT_MIN_DROP_KG, noise_kg * FEED_MOVEMENT_NOISE_FACTOR)

    active_crop_id = active_crop_id_from_entries(entries if isinstance(entries, dict) else {})
    in_crop = active_crop_id not in [None, ""]
    state_prefix = "in_crop" if in_crop else "out_of_crop"
    feed_out_key = "%s_feed_out_kg" % state_prefix
    feed_in_key = "%s_feed_in_kg" % state_prefix

    baseline_kg = float(movement.get("baseline_kg") or feed_kg)
    low_kg = float(movement.get("low_kg") or feed_kg)
    last_movement = movement.get("last_movement") or ""
    movement_kind = ""
    movement_kg = 0.0

    # Measure a rise from the lowest point since the last movement, not from the last
    # fill level: a delivery into a part-empty bin rarely tops the previous fill.
    if feed_kg >= low_kg + FEED_REFILL_RISE_KG:
        fill_kg = max(0.0, feed_kg - low_kg)
        if fill_kg >= min_drop_kg:
            movement[feed_in_key] = round(float(movement.get(feed_in_key) or 0.0) + fill_kg, 3)
            last_movement = "bin_fill"
            movement_kind = "bin_fill"
            movement_kg = fill_kg
        baseline_kg = feed_kg
        low_kg = feed_kg
    elif feed_kg <= low_kg - min_drop_kg:
        movement_kg = low_kg - feed_kg
        movement[feed_out_key] = round(float(movement.get(feed_out_key) or 0.0) + movement_kg, 3)
        last_movement = "feed_out"
        movement_kind = "feed_out"
        low_kg = feed_kg
    elif feed_kg > low_kg + min_drop_kg:
        low_kg = feed_kg

    if movement_kind and movement_kg >= min_drop_kg:
        events = movement.get("events", [])
        if not isinstance(events, list):
            events = []
        events = append_feed_movement_event(events, {
            "id": "%s-%s" % (sample_ts, movement_kind),
            "ts": int(sample_ts),
            "start_ts": int(sample_ts),
            "end_ts": int(sample_ts),
            "movement": movement_kind,
            "kg": round(float(movement_kg), 3),
            "crop_state": "in_crop" if in_crop else "out_of_crop",
            "crop_id": None if active_crop_id in [None, ""] else int(active_crop_id),
            "feed_kg_after": round(feed_kg, 3),
        }, session_gap_seconds=FEED_FILL_SESSION_GAP_SECONDS if movement_kind == "bin_fill" else FEED_MOVEMENT_SESSION_GAP_SECONDS)
        movement["events"] = events[-500:]

    movement.update({
        "baseline_kg": round(baseline_kg, 3),
        "low_kg": round(low_kg, 3),
        "last_feed_kg": round(feed_kg, 3),
        "last_sample_ts": sample_ts,
        "updated_ts": int(time.time()),
        "last_crop_state": "in_crop" if in_crop else "out_of_crop",
        "last_crop_id": None if active_crop_id in [None, ""] else int(active_crop_id),
        "last_movement": last_movement,
    })
    sensors["feed_movement"] = clean_feed_movement_state(movement)
    return True


def update_feed_raw_display_smoothing(sensors, feed_raw, now_ts=None):
    now_ts = int(time.time()) if now_ts is None else int(now_ts)
    samples = sensors.get("feed_raw_display_samples")
    if not isinstance(samples, list):
        samples = []
    samples.append({
        "ts": now_ts,
        "raw": float(feed_raw),
    })

    cutoff_ts = now_ts - FEED_RAW_DISPLAY_SMOOTH_SECONDS
    kept_samples = []
    raw_values = []
    i = 0
    while i < len(samples):
        sample = samples[i]
        i += 1
        try:
            sample_ts = int(sample.get("ts"))
            sample_raw = float(sample.get("raw"))
        except Exception:
            continue
        if sample_ts < cutoff_ts:
            continue
        kept_samples.append({
            "ts": sample_ts,
            "raw": sample_raw,
        })
        raw_values.append(sample_raw)

    sensors["feed_raw_display_samples"] = kept_samples
    sensors["feed_raw_display_units"] = round(
        sum(raw_values) / float(len(raw_values)) if raw_values else float(feed_raw),
        1,
    )


def feed_raw_display_units(sensors):
    if not isinstance(sensors, dict):
        return None
    value = sensors.get("feed_raw_display_units")
    if value not in [None, ""]:
        return value
    return sensors.get("feed_raw_units")


def update_feed_from_raw(sensors, now_ts=None, entries=None):
    now_ts = int(time.time()) if now_ts is None else int(now_ts)
    raw = sensors.get("raw", {})
    try:
        feed_raw = raw.get("feed_raw_units")
        if feed_raw in [None, ""]:
            feed_raw = raw.get("feed_raw")
        if feed_raw in [None, ""]:
            return
        feed_raw = float(feed_raw)
    except Exception:
        return

    sensors["feed_raw_units"] = feed_raw
    update_feed_raw_display_smoothing(sensors, feed_raw, now_ts=now_ts)
    samples = sensors.get("feed_raw_samples")
    if not isinstance(samples, list):
        samples = []
    samples.append({
        "ts": now_ts,
        "raw": feed_raw,
    })
    cutoff_ts = now_ts - FEED_DISPLAY_AVERAGE_SECONDS
    kept_samples = []
    i = 0
    while i < len(samples):
        sample = samples[i]
        i += 1
        try:
            sample_ts = int(sample.get("ts"))
            sample_raw = float(sample.get("raw"))
        except Exception:
            continue
        if sample_ts < cutoff_ts:
            continue
        kept_samples.append({
            "ts": sample_ts,
            "raw": sample_raw,
        })
    sensors["feed_raw_samples"] = kept_samples

    cfg = load_config()
    tare = cfg.get("feed_tare_raw")
    scale = cfg.get("feed_kg_per_raw_unit")
    capacity = cfg.get("feed_capacity_kg")

    if tare in [None, ""] or scale in [None, ""]:
        update_feed_diagnostics(sensors, kept_samples, now_ts=now_ts)
        sensors["feed_kg_live"] = None
        sensors["feed_kg"] = None
        sensors["feed_kg_updated_ts"] = None
        return False

    try:
        tare = float(tare)
        scale = float(scale)
        capacity = float(capacity) if capacity not in [None, ""] else None
    except Exception:
        update_feed_diagnostics(sensors, kept_samples, now_ts=now_ts)
        sensors["feed_kg_live"] = None
        sensors["feed_kg"] = None
        sensors["feed_kg_updated_ts"] = None
        return False

    if scale <= 0:
        update_feed_diagnostics(sensors, kept_samples, now_ts=now_ts)
        sensors["feed_kg_live"] = None
        sensors["feed_kg"] = None
        sensors["feed_kg_updated_ts"] = None
        return False

    feed_kg_live = (feed_raw - tare) * scale
    if capacity is not None and capacity > 0:
        feed_kg_live = min(feed_kg_live, capacity)
    sensors["feed_kg_live"] = round(feed_kg_live, 1)
    update_feed_diagnostics(sensors, kept_samples, scale=scale, now_ts=now_ts)

    last_update_ts = sensors.get("feed_kg_updated_ts")
    try:
        last_update_ts = int(last_update_ts) if last_update_ts not in [None, ""] else None
    except Exception:
        last_update_ts = None
    if sensors.get("feed_kg") not in [None, ""] and last_update_ts is None:
        sensors["feed_kg_updated_ts"] = now_ts
        return False
    if sensors.get("feed_kg") not in [None, ""] and (now_ts - last_update_ts) < FEED_DISPLAY_AVERAGE_SECONDS:
        return False

    averaged_raw = feed_raw
    if kept_samples:
        averaged_raw = sum(sample["raw"] for sample in kept_samples) / float(len(kept_samples))
    feed_kg = (averaged_raw - tare) * scale
    if capacity is not None and capacity > 0:
        feed_kg = min(feed_kg, capacity)
    previous_feed_kg = sensors.get("feed_kg")
    try:
        previous_feed_kg = float(previous_feed_kg)
    except Exception:
        previous_feed_kg = None
    sensors["feed_average_raw_units"] = round(averaged_raw, 1)
    sensors["feed_kg"] = round(feed_kg, 1)
    sensors["feed_kg_updated_ts"] = now_ts
    sensors["feed_minute_change_kg"] = round(feed_kg - previous_feed_kg, 1) if previous_feed_kg is not None else None
    if previous_feed_kg is not None and feed_kg >= previous_feed_kg + FEED_REFILL_RISE_KG:
        sensors["feed_refill_settling_until_ts"] = now_ts + FEED_REFILL_SETTLING_SECONDS
    update_feed_movement_state(sensors, feed_kg, now_ts, entries=entries)
    append_feed_published_sample(sensors, feed_kg, averaged_raw, now_ts)
    return True


def reset_feed_average_state(sensors, clear_published=True):
    sensors["feed_raw_display_samples"] = []
    sensors["feed_raw_display_units"] = sensors.get("feed_raw_units")
    sensors["feed_raw_samples"] = []
    sensors["feed_average_raw_units"] = None
    sensors["feed_kg_live"] = None
    sensors["feed_kg_updated_ts"] = None
    sensors["feed_minute_change_kg"] = None
    sensors["feed_noise_raw_units"] = None
    sensors["feed_noise_kg"] = None
    sensors["feed_stability_label"] = "Waiting for samples"
    sensors["feed_refill_settling_until_ts"] = None
    sensors["feed_published_samples"] = []
    if clear_published:
        sensors["feed_kg"] = None


CLIMATE_DAYS_KEPT = 90


def update_climate_extremes(sensors, now_ts):
    day = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d")
    days = sensors.get("climate_days")
    if not isinstance(days, list):
        days = []
    if not days or days[-1].get("date") != day:
        days.append({"date": day})
    rec = days[-1]
    for metric, key in [("temp", "temp_c"), ("rh", "rh_pct")]:
        try:
            value = float(sensors.get(key))
        except Exception:
            continue
        if rec.get(metric + "_min") is None or value < rec[metric + "_min"]:
            rec[metric + "_min"] = value
            rec[metric + "_min_ts"] = now_ts
        if rec.get(metric + "_max") is None or value > rec[metric + "_max"]:
            rec[metric + "_max"] = value
            rec[metric + "_max_ts"] = now_ts
    sensors["climate_days"] = days[-CLIMATE_DAYS_KEPT:]


def climate_day_display(rec):
    rec = rec or {}
    return {
        "date": rec.get("date", ""),
        "date_label": datetime.strptime(rec["date"], "%Y-%m-%d").strftime("%a %d %b") if rec.get("date") else "--",
        "temp_min": fmt_value(rec.get("temp_min"), "f1"),
        "temp_min_at": fmt_clock_ts(rec.get("temp_min_ts")),
        "temp_max": fmt_value(rec.get("temp_max"), "f1"),
        "temp_max_at": fmt_clock_ts(rec.get("temp_max_ts")),
        "rh_min": fmt_value(rec.get("rh_min"), "f0"),
        "rh_min_at": fmt_clock_ts(rec.get("rh_min_ts")),
        "rh_max": fmt_value(rec.get("rh_max"), "f0"),
        "rh_max_at": fmt_clock_ts(rec.get("rh_max_ts")),
    }


def climate_today_display(sensors, now_ts):
    day = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d")
    days = sensors.get("climate_days") or []
    if days and days[-1].get("date") == day:
        return climate_day_display(days[-1])
    return climate_day_display({"date": day})


def apply_sensor_packet(state, packet):
    sensors = state.get("sensors", default_sensor_state())
    now_ts = int(time.time())
    packet_kind = str(packet.get("packet_kind") or "full").strip().lower()
    serial_port = str(packet.pop("_serial_port", "") or "").strip()

    if packet.get("boot_count") not in [None, ""]:
        try:
            sensors["pico_boot_count"] = int(packet.get("boot_count"))
        except Exception:
            pass
    if "reset_cause" in packet:
        sensors["pico_reset_cause"] = str(packet.get("reset_cause") or "")
    sensors["pico_packet_kind"] = packet_kind
    if "checkpoint" in packet:
        sensors["pico_checkpoint"] = str(packet.get("checkpoint") or "")
        sensors["pico_checkpoint_ts"] = now_ts

    key_map = {
        "temp_c": "temp_c",
        "rh_pct": "rh_pct",
        "water_lpm": "water_lpm",
        "feed_kg": "feed_kg",
        "hx711_dout": "hx711_dout",
        "hx711_sck": "hx711_sck",
        "hx711_ready": "hx711_ready",
        "hx711_dout_before": "hx711_dout_before",
        "hx711_sck_before": "hx711_sck_before",
        "hx711_ready_before": "hx711_ready_before",
        "status": "device_status",
        "device_status": "device_status",
    }

    for key in key_map:
        if key in packet:
            if key == "feed_kg" and packet.get(key) is None:
                continue
            sensors[key_map[key]] = packet.get(key)

    if isinstance(packet.get("alarms"), list) and packet_kind != "checkpoint":
        sensors["alarms"] = packet.get("alarms")

    if packet_kind != "checkpoint" and ("temp_c" in packet or "rh_pct" in packet):
        update_climate_extremes(sensors, now_ts)

    sensors["pico_connected"] = True
    sensors["last_sensor_ts"] = now_ts
    sensors["last_serial_line"] = json.dumps(packet)
    mark_serial_reader_state(
        sensors,
        status="Receiving Pico packets",
        port=serial_port or None,
        clear_error=True,
        now_ts=now_ts,
    )

    if packet_kind == "checkpoint":
        reconcile_alarm_history(state, now_ts=now_ts)
        state["sensors"] = sensors
        return

    cfg = load_config()
    augers = ensure_augers_state(sensors)
    i = 0
    while i < len(AUGER_DEFS):
        auger_key = AUGER_DEFS[i][0]
        packet_keys = AUGER_PACKET_KEYS.get(auger_key, [])
        j = 0
        while j < len(packet_keys):
            packet_key = packet_keys[j]
            if packet_key in packet:
                bool_value = normalize_bool(packet.get(packet_key))
                if bool_value is not None:
                    update_auger_state(auger_key, augers[auger_key], bool_value, now_ts, cfg=cfg)
                break
            j += 1
        i += 1

    j = 0
    while j < len(LIGHTING_PACKET_KEYS):
        packet_key = LIGHTING_PACKET_KEYS[j]
        if packet_key in packet:
            bool_value = normalize_bool(packet.get(packet_key))
            if bool_value is not None:
                update_lighting_state(sensors, bool_value, now_ts)
            break
        j += 1

    sensors["raw"] = packet
    sensors["device_status"] = str(packet.get("status", sensors.get("device_status", "Pico connected")))
    try:
        append_ndjson(os.path.join(DATA_DIR, "sensor_live.ndjson"), {
            "ts": now_ts,
            "shed_no": load_config()["shed_no"],
            "packet": packet,
        })
        state["last_log_ts"] = now_ts
        state["last_log_status"] = "Log OK"
    except Exception as exc:
        state["last_log_ts"] = now_ts
        state["last_log_status"] = "Log failed: %s" % exc
    update_water_from_pulses(sensors, now_ts)
    update_feed_from_raw(sensors, now_ts=now_ts, entries=state.get("entries", {}))
    evaluate_augers(sensors, now_ts=now_ts)
    state["sensors"] = sensors
    if bool(state.get("pending_pico_update_recovery")):
        state["pending_pico_update_recovery"] = False
        state["pending_pico_update_recovery_set_ts"] = None
        state["last_pico_recovery_status"] = "Pico returned after update"
        state["last_pico_recovery_result_ts"] = now_ts
    calib = state.get("water_calibration", {})
    if isinstance(calib, dict) and calib.get("active"):
        calib["latest_total_pulses"] = sensors.get("flow_total_pulses")
        try:
            end_ts = int(calib.get("end_ts"))
        except Exception:
            end_ts = None
        if end_ts is not None and now_ts >= end_ts:
            calib["active"] = False
            calib["completed"] = True
            try:
                start_total = int(calib.get("start_total_pulses"))
                latest_total = int(calib.get("latest_total_pulses"))
                calib["pulse_delta"] = max(0, latest_total - start_total)
            except Exception:
                calib["pulse_delta"] = None
        state["water_calibration"] = calib

    reconcile_alarm_history(state, now_ts=now_ts)


def mark_serial_reader_state(sensors, status=None, port=None, error=None, clear_error=False, now_ts=None):
    now_ts = int(time.time()) if now_ts is None else int(now_ts)
    if status is not None:
        sensors["serial_reader_status"] = str(status or "")
    if port is not None:
        sensors["serial_reader_port"] = str(port or "")
    sensors["serial_reader_heartbeat_ts"] = now_ts
    if error is not None:
        sensors["serial_reader_error"] = str(error or "")
        sensors["serial_reader_error_ts"] = now_ts if error else None
    elif clear_error:
        sensors["serial_reader_error"] = ""
        sensors["serial_reader_error_ts"] = None


def serial_reader_status_update(status, port=None, error=None, clear_error=False):
    def mutator(state):
        sensors = state.get("sensors", default_sensor_state())
        mark_serial_reader_state(
            sensors,
            status=status,
            port=port,
            error=error,
            clear_error=clear_error,
        )
        state["sensors"] = sensors
        reconcile_alarm_history(state)
    mutate_state(mutator)


def serial_error_update(message, reader_status=None, serial_error=None, port=None):
    def mutator(state):
        sensors = state.get("sensors", default_sensor_state())
        sensors["pico_connected"] = False
        sensors["device_status"] = message
        error_detail = serial_error if serial_error is not None else message
        mark_serial_reader_state(
            sensors,
            status=reader_status or message,
            port=port,
            error=error_detail,
        )
        state["sensors"] = sensors
        reconcile_alarm_history(state)
    mutate_state(mutator)


def serial_reader_loop():
    last_reader_heartbeat_ts = 0
    serial_reader_status_update("Serial reader starting", clear_error=True)
    while not SERIAL_STOP.is_set():
        conn = None
        port = ""
        try:
            cfg = load_config()

            if not cfg.get("serial_enabled"):
                serial_error_update("Serial disabled", reader_status="Serial disabled", serial_error="")
                SERIAL_STOP.wait(2.0)
                continue

            if serial is None:
                serial_error_update("pyserial not installed", reader_status="pyserial not installed")
                SERIAL_STOP.wait(5.0)
                continue

            port = detect_serial_port()
            if not port:
                serial_error_update(
                    "Pico offline: no Pico serial device found",
                    reader_status="No Pico serial device found",
                    serial_error="No Pico serial device found",
                )
                SERIAL_STOP.wait(3.0)
                continue

            try:
                conn = serial.Serial(
                    port=port,
                    baudrate=cfg["serial_baudrate"],
                    timeout=cfg["serial_timeout"],
                )
            except Exception as exc:
                serial_error_update(
                    "Pico offline: %s" % exc,
                    reader_status="Serial open failed",
                    serial_error=str(exc),
                    port=port,
                )
                SERIAL_STOP.wait(3.0)
                continue

            serial_reader_status_update("Listening on %s" % port, port=port, clear_error=True)
            mutate_state(lambda state: apply_sensor_packet(state, {"status": "Pico connected on %s" % port, "_serial_port": port}))

            while not SERIAL_STOP.is_set():
                try:
                    raw = conn.readline()
                except Exception as exc:
                    serial_error_update(
                        "Pico serial read failed: %s" % exc,
                        reader_status="Serial read failed",
                        serial_error=str(exc),
                        port=port,
                    )
                    record_controller_event(
                        "pico_serial_read_failed",
                        "Pico serial read failed",
                        str(exc),
                        push_to_office=False,
                    )
                    break

                if not raw:
                    now_ts = int(time.time())
                    if now_ts - last_reader_heartbeat_ts >= SERIAL_READER_HEARTBEAT_SECONDS:
                        last_reader_heartbeat_ts = now_ts
                        serial_reader_status_update("Waiting for Pico serial data", port=port)
                    continue

                try:
                    line = raw.decode("utf-8", errors="ignore").strip()
                except Exception as exc:
                    serial_reader_status_update("Serial decode failed", port=port, error=str(exc))
                    continue

                if not line:
                    continue

                try:
                    packet = json.loads(line)
                except Exception:
                    mutate_state(lambda state: _record_raw_serial_line(state, line))
                    continue

                if not isinstance(packet, dict):
                    mutate_state(lambda state: _record_raw_serial_line(state, line))
                    continue
                packet["_serial_port"] = port
                state = mutate_state(lambda s: apply_sensor_packet(s, packet))
                if packet.get("packet_kind") != "checkpoint" and load_config().get("sync_on_sensor_update"):
                    auto_sync_if_changed(state, pull_back=False)
        except Exception as exc:
            serial_error_update(
                "Pico serial loop error: %s" % exc,
                reader_status="Serial loop error",
                serial_error=str(exc),
                port=port,
            )
            record_controller_event(
                "pico_serial_loop_error",
                "Pico serial loop error",
                str(exc),
                push_to_office=False,
            )
            SERIAL_STOP.wait(3.0)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


def _record_raw_serial_line(state, line):
    sensors = state.get("sensors", default_sensor_state())
    sensors["last_serial_line"] = line
    sensors["device_status"] = "Non-JSON serial data received"
    sensors["pico_connected"] = True
    sensors["last_sensor_ts"] = int(time.time())
    mark_serial_reader_state(sensors, status="Receiving non-JSON serial data", clear_error=True)
    evaluate_augers(sensors)
    state["sensors"] = sensors
    reconcile_alarm_history(state)


def start_serial_thread():
    global SERIAL_THREAD
    if SERIAL_THREAD is not None and SERIAL_THREAD.is_alive():
        return

    SERIAL_STOP.clear()
    SERIAL_THREAD = threading.Thread(target=serial_reader_loop, daemon=True)
    SERIAL_THREAD.start()


def auger_monitor_loop():
    while not SERIAL_STOP.is_set():
        def mutator(s):
            evaluate_augers(s.get("sensors", default_sensor_state()))
            maybe_auto_backup(s)
            reconcile_alarm_history(s)
        state = mutate_state(mutator)
        if pico_post_update_recovery_due(state):
            attempt_ts = int(time.time())
            mutate_state(lambda s: s.update({
                "last_pico_recovery_attempt_ts": attempt_ts,
                "last_pico_recovery_status": "Attempting post-update Pico reset",
            }))
            record_controller_event(
                "pico_post_update_recovery",
                "Attempting post-update Pico reset",
                pico_recovery_detail(state, "No fresh Pico packet arrived after controller restart"),
                push_to_office=False,
            )
            reset_status = soft_reset_pico()
            recovery_status = str(reset_status.get("status") or "")
            recovery_ok = bool(reset_status.get("ok"))
            result_ts = int(time.time())
            state = mutate_state(lambda s: s.update({
                "last_pico_recovery_attempt_ts": attempt_ts,
                "last_pico_recovery_result_ts": result_ts,
                "last_pico_recovery_status": recovery_status,
                "pending_pico_update_recovery": False,
                "pending_pico_update_recovery_set_ts": None,
            }))
            record_controller_event(
                "pico_post_update_recovery_result",
                "Post-update Pico reset %s" % ("successful" if recovery_ok else "failed"),
                recovery_status,
                push_to_office=False,
            )
        if pico_auto_recovery_due(state):
            attempt_ts = int(time.time())
            mutate_state(lambda s: s.update({
                "last_pico_recovery_attempt_ts": attempt_ts,
                "last_pico_recovery_status": "Attempting automatic Pico reset",
            }))
            record_controller_event(
                "pico_auto_recovery",
                "Attempting automatic Pico reset",
                pico_recovery_detail(state, "No sensor update received"),
                push_to_office=False,
            )
            reset_status = soft_reset_pico()
            recovery_status = str(reset_status.get("status") or "")
            recovery_ok = bool(reset_status.get("ok"))
            result_ts = int(time.time())
            state = mutate_state(lambda s: s.update({
                "last_pico_recovery_attempt_ts": attempt_ts,
                "last_pico_recovery_result_ts": result_ts,
                "last_pico_recovery_status": recovery_status,
            }))
            record_controller_event(
                "pico_auto_recovery_result",
                "Automatic Pico reset %s" % ("successful" if recovery_ok else "failed"),
                recovery_status,
                push_to_office=False,
            )
        if load_config().get("sync_on_sensor_update"):
            auto_sync_if_changed(state, pull_back=False)
        SERIAL_STOP.wait(5.0)


def start_monitor_thread():
    global MONITOR_THREAD
    if MONITOR_THREAD is not None and MONITOR_THREAD.is_alive():
        return

    SERIAL_STOP.clear()
    MONITOR_THREAD = threading.Thread(target=auger_monitor_loop, daemon=True)
    MONITOR_THREAD.start()


BACKGROUND_SYNC_THREAD = None


AUTO_UPDATE_WINDOW_MINUTES = 30
AUTO_UPDATE_THREAD = None


def auto_update_status_path():
    return os.path.join(DATA_DIR, "auto_update_status.json")


def load_auto_update_status():
    data = read_json_file(auto_update_status_path(), {})
    return data if isinstance(data, dict) else {}


def auto_update_loop():
    # Once a night, in the first half hour after midnight, check GitHub and install the
    # update if this controller is on a different commit to its branch on GitHub.
    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            in_window = now.hour == 0 and now.minute < AUTO_UPDATE_WINDOW_MINUTES
            status = load_auto_update_status()
            if in_window and load_config().get("auto_update_enabled", False) and status.get("last_run_date") != today:
                status = {"last_run_date": today, "last_run_ts": int(time.time())}
                write_json_file_atomic(auto_update_status_path(), status)
                check = check_for_update()
                if not check.get("ok"):
                    status["result"] = "Check failed: %s" % (check.get("status") or "unknown error")
                elif not check.get("update_available"):
                    status["result"] = "Already on latest version"
                else:
                    status["result"] = "Updating %s -> %s" % (check.get("local_commit"), check.get("remote_commit"))
                write_json_file_atomic(auto_update_status_path(), status)
                if check.get("ok") and check.get("update_available"):
                    install_controller_update("nightly auto update")
        except Exception as exc:
            try:
                status = load_auto_update_status()
                status["result"] = "Auto update error: %s" % exc
                write_json_file_atomic(auto_update_status_path(), status)
            except Exception:
                pass
        time.sleep(60)


def start_auto_update_thread():
    global AUTO_UPDATE_THREAD
    if AUTO_UPDATE_THREAD and AUTO_UPDATE_THREAD.is_alive():
        return
    AUTO_UPDATE_THREAD = threading.Thread(target=auto_update_loop, daemon=True)
    AUTO_UPDATE_THREAD.start()


def start_background_sync_thread():
    global BACKGROUND_SYNC_THREAD
    if BACKGROUND_SYNC_THREAD is not None and BACKGROUND_SYNC_THREAD.is_alive():
        return
    BACKGROUND_SYNC_THREAD = threading.Thread(target=background_sync_loop, daemon=True)
    BACKGROUND_SYNC_THREAD.start()


HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ shed_display_name }} Controller</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root {
            --bg: #5b5b5b;
            --panel: rgba(115, 115, 115, 0.96);
            --panel-2: rgba(104, 104, 104, 0.98);
            --line: #858585;
            --text: #ececec;
            --muted: #d2d2d2;
            --green: #7be1aa;
            --amber: #ffd06a;
            --red: #ff7777;
            --blue: #84d0ff;
        }
        * {
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        body {
            margin: 0;
            min-height: 100vh;
            color: var(--text);
            font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
            background: #5b5b5b;
        }
        .wrap {
            width: 100%;
            max-width: 1024px;
            margin: 0 auto;
            padding: 18px;
        }
        .hero {
            display: grid;
            grid-template-columns: 1fr;
            gap: 16px;
            margin-bottom: 16px;
        }
        .panel {
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 20px;
            padding: 18px;
            box-shadow: 0 0 20px rgba(0,0,0,0.08);
        }
        .hero-main {
            display: block;
        }
        h1 {
            margin: 0;
            font-size: 40px;
            line-height: 1;
            letter-spacing: 0.02em;
            white-space: nowrap;
        }
        h1.active {
            text-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        h1.inactive {
            text-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .title-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 22px;
            flex-wrap: nowrap;
        }
        .hero-crop-wrap {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            margin-left: auto;
        }
        .hero-crop {
            font-size: 18px;
            font-weight: 700;
            color: var(--text);
            line-height: 1;
            text-align: right;
            white-space: nowrap;
        }
        .hero-datetime {
            font-size: 18px;
            font-weight: 700;
            color: var(--text);
            line-height: 1;
            text-align: right;
            white-space: nowrap;
        }
        .hero-crop.active {
            text-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .hero-crop.inactive {
            text-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .hero-datetime.active {
            text-shadow: 0 0 10px rgba(47,158,58,0.50),
                0 0 18px rgba(47,158,58,0.30),
                0 0 28px rgba(47,158,58,0.15);
        }
        .hero-datetime.inactive {
            text-shadow: 0 0 10px rgba(214,69,69,0.50),
                0 0 18px rgba(214,69,69,0.30),
                0 0 28px rgba(214,69,69,0.15);
        }
        .hero-birds {
            display: inline-flex;
            align-items: baseline;
            justify-content: center;
            gap: 8px;
            padding: 14px 16px;
            border-radius: 16px;
            background: var(--panel-2);
            border: 1px solid var(--line);
            text-decoration: none;
            min-height: 52px;
            box-sizing: border-box;
        }
        .hero-birds.active,
        .hero-age.active,
        .hero-mortality.active {
            border-color: rgba(47,158,58,0.90);
            box-shadow: 0 0 10px rgba(47,158,58,0.15),
                0 0 18px rgba(47,158,58,0.09);
        }
        .hero-birds.inactive,
        .hero-age.inactive,
        .hero-mortality.inactive {
            border-color: rgba(214,69,69,0.90);
            box-shadow: 0 0 10px rgba(214,69,69,0.13),
                0 0 18px rgba(214,69,69,0.08);
        }
        .hero-age.lighting-on {
            border-color: rgba(47,158,58,0.90);
            box-shadow: 0 0 10px rgba(47,158,58,0.15),
                0 0 18px rgba(47,158,58,0.09);
        }
        .hero-age.lighting-off {
            border-color: rgba(214,69,69,0.90);
            box-shadow: 0 0 10px rgba(214,69,69,0.13),
                0 0 18px rgba(214,69,69,0.08);
        }
        .hero-birds-label {
            color: var(--muted);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            line-height: 1;
            white-space: nowrap;
        }
        .hero-birds-val {
            font-size: 28px;
            font-weight: 700;
            line-height: 1;
            color: var(--text);
            white-space: nowrap;
        }
        .hero-stat-row {
            display: flex;
            gap: 16px;
            flex-wrap: nowrap;
            align-items: stretch;
            margin-top: 12px;
        }
        .hero-age {
            display: inline-flex;
            align-items: baseline;
            justify-content: center;
            gap: 8px;
            padding: 14px 16px;
            border-radius: 16px;
            background: var(--panel-2);
            border: 1px solid var(--line);
            min-height: 52px;
            box-sizing: border-box;
        }
        .hero-age-label {
            color: var(--muted);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            line-height: 1;
            white-space: nowrap;
        }
        .hero-age-val {
            font-size: 28px;
            font-weight: 700;
            line-height: 1;
            color: var(--text);
            white-space: nowrap;
        }
        .hero-light-icon {
            font-size: 22px;
            line-height: 1;
            margin-left: 6px;
            transition: opacity 120ms ease, filter 120ms ease, color 120ms ease;
        }
        .hero-light-icon.lighting-on {
            color: #9a4b00;
            opacity: 1;
            filter: drop-shadow(0 0 8px rgba(255, 208, 106, 0.75));
        }
        .hero-light-icon.lighting-off {
            color: #0d2b4a;
            opacity: 0.65;
            filter: grayscale(1) brightness(0.75);
        }
        .hero-mortality {
            display: inline-flex;
            align-items: baseline;
            justify-content: center;
            gap: 8px;
            padding: 14px 16px;
            border-radius: 16px;
            background: var(--panel-2);
            border: 1px solid var(--line);
            text-decoration: none;
            color: var(--text);
            min-height: 52px;
            box-sizing: border-box;
        }
        .hero-mortality-label {
            color: var(--muted);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            line-height: 1;
            white-space: nowrap;
        }
        .hero-mortality-val {
            font-size: 28px;
            font-weight: 700;
            line-height: 1;
            color: var(--text);
            white-space: nowrap;
        }
        .hero-allocations {
            margin-top: 12px;
            color: var(--muted);
            font-size: 16px;
        }
        .hero-datetime-inline {
            margin-left: auto;
            display: inline-flex;
            align-items: center;
            justify-content: flex-end;
            min-height: 64px;
            box-sizing: border-box;
            padding: 0 8px 0 12px;
        }
        h2 {
            margin: 0 0 14px 0;
            font-size: 24px;
        }
        .sub {
            margin-top: 10px;
            color: var(--muted);
            font-size: 18px;
        }
        .pill-grid {
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 6px;
            width: 100%;
        }
        .pill {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            justify-content: center;
            gap: 2px;
            padding: 7px 9px;
            border-radius: 14px;
            background: var(--panel-2);
            border: 1px solid var(--line);
            font-size: 12px;
            min-width: 0;
            min-height: 46px;
        }
        .pill-label {
            color: var(--muted);
            font-size: 8px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            line-height: 1;
        }
        .pill-value {
            display: block;
            max-width: 100%;
            font-size: 12px;
            font-weight: 700;
            line-height: 1.1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .pill.ok { border-color: rgba(47,158,58,0.45); color: var(--green); }
        .pill.warn { border-color: rgba(240,138,18,0.45); color: var(--amber); }
        .pill.bad { border-color: rgba(214,69,69,0.45); color: var(--red); }
        .hero-pills {
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #d5dde6;
        }
        .top-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            grid-auto-rows: 170px;
            gap: 14px;
            margin-bottom: 16px;
        }
        .metric {
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 18px;
            padding: 16px;
            min-height: 170px;
            height: 100%;
            display: flex;
            flex-direction: column;
        }
        .metric-link {
            display: block;
            text-decoration: none;
            color: inherit;
            height: 100%;
        }
        .metric-split-link {
            display: block;
            text-decoration: none;
            color: inherit;
            height: 100%;
        }
        .metric-split-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 14px;
            height: 100%;
        }
        .metric.metric-mini {
            min-width: 0;
            padding: 14px;
        }
        .metric.metric-mini .metric-label {
            margin-bottom: 8px;
            font-size: 12px;
        }
        .metric.metric-mini .metric-val {
            font-size: 32px;
        }
        .metric.metric-mini .metric-sub {
            font-size: 13px;
        }
        .auger-row-shell {
            grid-column: 1 / span 3;
            display: grid;
            grid-template-columns: calc((100% - 70px) / 6) minmax(0, 1fr);
            gap: 14px;
            height: 100%;
        }
        .auger-grid-shell {
            display: grid;
            gap: 14px;
            height: 100%;
        }
        .auger-grid-shell.count-1 {
            grid-template-columns: 1fr;
        }
        .auger-grid-shell.count-2 {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .auger-grid-shell.count-3 {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }
        .auger-grid-shell.count-4 {
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }
        .auger-grid-shell .metric {
            min-width: 0;
        }
        .lighting-tile {
            padding: 16px;
        }
        .lighting-tile .metric-val {
            font-size: 40px;
        }
        .metric.flow-green {
            border-color: #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .metric.flow-red,
        .metric.feed-red {
            border-color: #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .metric.temp-green {
            border-color: #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .metric.temp-warn {
            border-color: #f08a12;
            box-shadow: 0 0 10px rgba(240,138,18,0.52),
                0 0 20px rgba(240,138,18,0.36),
                0 0 34px rgba(240,138,18,0.19);
        }
        .metric.temp-red {
            border-color: #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .metric.rh-green {
            border-color: #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .metric.rh-warn {
            border-color: #f08a12;
            box-shadow: 0 0 10px rgba(240,138,18,0.52),
                0 0 20px rgba(240,138,18,0.36),
                0 0 34px rgba(240,138,18,0.19);
        }
        .metric.rh-red {
            border-color: #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .metric.feed-green {
            border-color: #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .metric.state-green {
            border-color: #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .metric.state-warn {
            border-color: #f08a12;
            box-shadow: 0 0 10px rgba(240,138,18,0.52),
                0 0 20px rgba(240,138,18,0.36),
                0 0 34px rgba(240,138,18,0.19);
        }
        .metric.state-red {
            border-color: #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .metric-label {
            color: var(--muted);
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 10px;
        }
        .metric-val {
            font-size: 40px;
            font-weight: 700;
            line-height: 1;
            margin-top: auto;
            margin-bottom: auto;
        }
        .metric-sub {
            margin-top: auto;
            font-size: 15px;
            color: var(--muted);
        }
        .metric-sub-auger-last {
            margin-top: 4px;
            font-size: 12px;
            color: var(--muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .main-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 16px;
        }
        input[type="number"], input[type="text"] {
            width: 100%;
            min-height: 78px;
            border-radius: 16px;
            border: 1px solid var(--line);
            background: var(--panel-2);
            color: var(--text);
            font-size: 34px;
            padding: 14px 18px;
        }
        input[type="text"] {
            font-size: 24px;
        }
        .allocation-list {
            display: grid;
            gap: 12px;
        }
        .allocation-card {
            padding: 14px;
            border-radius: 16px;
            background: var(--panel-2);
            border: 1px solid #d5dde6;
        }
        .allocation-top {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 10px;
            align-items: center;
        }
        .allocation-title {
            font-size: 24px;
            font-weight: 700;
        }
        .allocation-meta {
            color: var(--muted);
            font-size: 16px;
        }
        .allocation-form {
            display: grid;
            grid-template-columns: 1fr repeat(4, minmax(0, 1fr));
            gap: 10px;
        }
        .action-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
        }
        .button-link {
            display: block;
            min-height: 78px;
            width: 100%;
            border-radius: 16px;
            border: 1px solid #d5dde6;
            background: #ffffff;
            color: var(--text);
            font-size: 20px;
            font-weight: 700;
            text-decoration: none;
            text-align: center;
            line-height: 78px;
            white-space: nowrap;
        }
        .settings-button {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 14px;
            min-height: 98px;
            font-size: 26px;
            line-height: 1;
        }
        .settings-icon {
            font-size: 28px;
            line-height: 1;
        }
        .home-buttons {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }
        button {
            min-height: 78px;
            width: 100%;
            border-radius: 16px;
            border: 1px solid #d5dde6;
            background: #ffffff;
            color: var(--text);
            font-size: 24px;
            font-weight: 700;
            cursor: pointer;
        }
        button:active {
            transform: scale(0.99);
        }
        .danger {
            border-color: #d64545;
            background: linear-gradient(180deg, #542e34, #3e2328);
        }
        .secondary {
            border-color: #d5dde6;
            background: #ffffff;
            font-size: 20px;
        }
        .msg {
            margin-bottom: 16px;
            padding: 14px 16px;
            border-radius: 16px;
            border: 1px solid #1676b8;
            background: #e6f0f9;
            font-size: 18px;
        }
        .msg.error {
            border-color: #d64545;
            background: #fdecec;
        }
        .msg.warn {
            border-color: rgba(240,138,18,0.45);
            background: #fff4e5;
        }
        .floating-alerts {
            margin-bottom: 16px;
        }
        .detail-list {
            display: grid;
            gap: 10px;
        }
        .full-panel {
            margin-top: 16px;
        }
        .detail {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            padding: 12px 0;
            border-bottom: 1px solid #d5dde6;
            font-size: 18px;
        }
        .detail:last-child {
            border-bottom: 0;
        }
        .label {
            color: var(--muted);
        }
        .alarm-list {
            display: grid;
            gap: 10px;
            margin-top: 12px;
        }
        .alarm {
            padding: 12px 14px;
            border-radius: 14px;
            border: 1px solid rgba(214,69,69,0.35);
            background: #fdecec;
            font-size: 17px;
        }
        .mono {
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 14px;
            color: var(--muted);
            word-break: break-word;
        }
        @media (min-width: 901px) and (max-width: 1100px) and (max-height: 700px) {
            .wrap {
                padding: 10px 12px 12px;
            }
            .hero {
                gap: 10px;
                margin-bottom: 10px;
            }
            .panel {
                border-radius: 16px;
                padding: 12px;
            }
            h1,
            .hero-crop {
                font-size: 32px;
            }
            .hero-birds,
            .hero-age,
            .hero-mortality {
                margin-top: 10px;
                padding: 9px 12px;
                border-radius: 12px;
                gap: 8px;
            }
            .hero-birds-val,
            .hero-age-val,
            .hero-mortality-val {
                font-size: 24px;
            }
            .hero-birds-label,
            .hero-age-label,
            .hero-mortality-label {
                font-size: 12px;
            }
            .hero-allocations {
                margin-top: 8px;
                font-size: 14px;
            }
            .hero-pills {
                margin-top: 10px;
                padding-top: 10px;
            }
            .pill-grid {
                gap: 5px;
            }
            .pill {
                min-height: 38px;
                padding: 5px 7px;
                border-radius: 12px;
            }
            .pill-label {
                font-size: 7px;
            }
            .pill-value {
                font-size: 11px;
            }
            .floating-alerts {
                padding: 10px 12px;
                border-radius: 14px;
                margin-bottom: 10px;
            }
            .alarm-list {
                gap: 8px;
                margin-top: 0;
            }
            .alarm {
                padding: 9px 11px;
                border-radius: 12px;
                font-size: 14px;
            }
            .top-grid {
                grid-auto-rows: 132px;
                gap: 10px;
                margin-bottom: 10px;
            }
            .metric {
                min-height: 132px;
                border-radius: 16px;
                padding: 10px;
            }
            .metric-split-grid {
                gap: 10px;
            }
            .metric.metric-mini {
                padding: 10px;
            }
            .metric.metric-mini .metric-label {
                font-size: 11px;
            }
            .metric.metric-mini .metric-val {
                font-size: 26px;
            }
            .metric.metric-mini .metric-sub {
                font-size: 12px;
            }
            .metric-label {
                margin-bottom: 8px;
                font-size: 15px;
            }
            .metric-val {
                font-size: 37px;
            }
            .metric-sub {
                margin-top: auto;
                font-size: 15px;
            }
            .settings-button {
                min-height: 62px;
                border-radius: 14px;
                font-size: 20px;
            }
            .button-link {
                line-height: 62px;
            }
            .settings-icon {
                font-size: 22px;
            }
            .msg {
                margin-bottom: 10px;
                padding: 10px 12px;
                border-radius: 14px;
                font-size: 15px;
            }
        }
        @media (max-width: 900px) {
            .hero, .top-grid, .main-grid, .action-grid, .allocation-form, .pill-grid {
                grid-template-columns: 1fr;
            }
            .metric-split-grid {
                gap: 10px;
            }
            .auger-row-shell,
            .auger-grid-shell,
            .auger-grid-shell.count-1,
            .auger-grid-shell.count-2,
            .auger-grid-shell.count-3,
            .auger-grid-shell.count-4 {
                grid-column: auto;
                grid-template-columns: 1fr;
            }
            .title-row {
                flex-wrap: wrap;
            }
            h1 {
                font-size: 36px;
            }
            .metric-val {
                font-size: 34px;
            }
            button, input[type="number"] {
                min-height: 72px;
            }
        }
    </style>
</head>
<body>
    <div class="wrap">
        {% if msg and not hide_home_alerts %}
        <div class="msg auto-dismiss {% if not ok %}error{% endif %}">{{ msg }}</div>
        {% endif %}
        {% if not hide_home_alerts %}
        <div id="offlineBanner" class="msg warn" {% if not offline_banner %}style="display:none"{% endif %}>{{ offline_banner }}</div>
        <div id="picoFreezeBanner" class="msg error" {% if not pico_warning_banner %}style="display:none"{% endif %}>{{ pico_warning_banner }}</div>
        <div id="picoRecoveryBanner" class="msg warn" {% if not pico_recovery_banner %}style="display:none"{% endif %}>{{ pico_recovery_banner }}</div>
        {% endif %}

        <div class="hero">
            <div class="panel">
                <div class="hero-main">
                    <div>
                        <div class="title-row">
                            <h1 id="headerTitle" class="{{ crop_class }}">CDF - {{ shed_display_name|upper }}</h1>
                            <div class="hero-crop-wrap">
                                <div id="cropHeader" class="hero-crop {{ crop_class }}">Crop <span id="cropValue">{{ active_crop_code }}</span></div>
                            </div>
                        </div>
                        <div class="hero-stat-row">
                            <a class="hero-birds {{ crop_class }}" href="{{ url_for('allocation_view') }}" id="birdsBox">
                                <span class="hero-birds-label">Birds</span>
                                <span class="hero-birds-val" id="birdsValue">{{ birds_display }}</span>
                            </a>
                            <a class="hero-mortality {{ crop_class }}" href="{{ url_for('mortality_view') }}" id="mortalityBox">
                                <span class="hero-mortality-label">Mortality</span>
                                <span class="hero-mortality-val" id="mortalityValue">{{ mortality_total }}</span>
                            </a>
                            <div class="hero-age {{ crop_class }}" id="ageBox">
                                <span class="hero-age-label">Bird Age</span>
                                <span class="hero-age-val" id="birdAgeValue">{{ oldest_bird_age }}</span>
                            </div>
                            <div class="hero-datetime-inline">
                                <div id="cropDateTime" class="hero-datetime {{ crop_class }}">{{ current_datetime }}</div>
                            </div>
                        </div>
                        <div class="hero-allocations" id="allocationSummary" {% if not allocation_summary %}style="display:none"{% endif %}>{{ allocation_summary }}</div>
                    </div>
                </div>
                <div class="hero-pills">
                    <div class="pill-grid">
                        <div id="alarmPill" class="pill {{ alarm_class }}"><span class="pill-label">Alarm</span><span class="pill-value" id="alarmValue">{{ alarm_short }}</span></div>
                        <div id="ethernetPill" class="pill {{ ethernet_class }}"><span class="pill-label">Office Link</span><span class="pill-value" id="ethernetValue">{{ ethernet_short }}</span></div>
                        <div id="syncPill" class="pill {{ sync_class }}"><span class="pill-label">Office Sync</span><span class="pill-value" id="syncValue">{{ sync_short }}</span></div>
                        <div id="picoPill" class="pill {{ sensor_class }}"><span class="pill-label">Pico</span><span class="pill-value" id="picoValue">{{ sensor_status_short }}</span></div>
                        <div id="pushPill" class="pill {{ push_class }}"><span class="pill-label">Update</span><span class="pill-value" id="pushValue">{{ push_short }}</span></div>
                        <div id="loggingPill" class="pill {{ log_class }}"><span class="pill-label">Logging</span><span class="pill-value" id="loggingValue">{{ log_short }}</span></div>
                    </div>
                </div>
            </div>
        </div>

        {% if not hide_home_alerts %}
        <div class="panel floating-alerts" id="controllerAlertsPanel" style="{% if not controller_alerts %}display:none{% endif %}">
            <div class="alarm-list" id="controllerAlertsList">
                {% for alarm in controller_alerts %}
                <div class="alarm">{{ alarm }}</div>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <div class="top-grid">
            <div class="metric-split-grid">
                <a class="metric-link" href="{{ url_for('temp_settings_view') }}">
                    <div id="tempTile" class="metric metric-mini {{ temp_glow }}">
                        <div class="metric-label">Temp</div>
                        <div class="metric-val" id="tempValue">{{ temp_c }}</div>
                        <div class="metric-sub">C · <span id="tempHiLo">H {{ climate_today.temp_max }} / L {{ climate_today.temp_min }}</span></div>
                    </div>
                </a>
                <a class="metric-link" href="{{ url_for('rh_settings_view') }}">
                    <div id="rhTile" class="metric metric-mini {{ rh_glow }}">
                        <div class="metric-label">RH</div>
                        <div class="metric-val" id="rhValue">{{ rh_pct }}</div>
                        <div class="metric-sub">%RH · <span id="rhHiLo">H {{ climate_today.rh_max }} / L {{ climate_today.rh_min }}</span></div>
                    </div>
                </a>
            </div>
            <a class="metric-link" href="{{ url_for('water_settings_view') }}">
                <div id="waterTile" class="metric {{ water_glow }}">
                    <div class="metric-label">Water L/PM</div>
                    <div class="metric-val" id="waterValue">{{ water_lpm }}</div>
                    <div class="metric-sub">Live water flow</div>
                </div>
            </a>
            <a class="metric-link" href="{{ url_for('feed_settings_view') }}">
                <div id="feedTile" class="metric {{ feed_glow }}">
                    <div class="metric-label">Feed Bin KG</div>
                    <div class="metric-val" id="feedValue">{{ feed_kg }}</div>
                    <div class="metric-sub">Feed remaining</div>
                </div>
            </a>
            <a class="metric-link" href="{{ url_for('water_history_view') }}">
                <div class="metric">
                    <div class="metric-label">Water Yesterday 6am-6am</div>
                    <div class="metric-val" id="water7to7Value">{{ water_7to7 }}</div>
                    <div class="metric-sub">Litres</div>
                </div>
            </a>
            {% if lighting_tile or auger_tiles %}
            <div class="{% if lighting_tile and auger_tiles %}auger-row-shell{% elif lighting_tile %}auger-row-shell{% else %}auger-grid-shell count-{{ auger_count }}{% endif %}">
                {% if lighting_tile %}
                <div id="auger-lighting" class="metric lighting-tile {{ lighting_tile.glow }}">
                    <div class="metric-label">{{ lighting_tile.label }}</div>
                    <div class="metric-val" data-lighting-status>{{ lighting_tile.status }}</div>
                    <div class="metric-sub">&nbsp;</div>
                </div>
                {% endif %}
                {% if auger_tiles %}
                <div class="auger-grid-shell count-{{ auger_count }}">
                {% for auger in auger_tiles %}
                <div id="auger-{{ auger.key }}" class="metric {{ auger.glow }}">
                    <div class="metric-label">{{ auger.label }}</div>
                    <div class="metric-val" data-auger-status>{{ auger.status }}</div>
                    <div class="metric-sub" data-auger-runtime>{% if auger.runtime %}{{ auger.runtime }}{% else %}&nbsp;{% endif %}</div>
                    <div class="metric-sub metric-sub-auger-last" data-auger-last-run>{{ auger.last_run }}</div>
                </div>
                {% endfor %}
                </div>
                {% endif %}
            </div>
            {% endif %}
            <a class="metric-link" href="{{ url_for('feed_history_view') }}">
                <div class="metric">
                    <div class="metric-label">Feed Yesterday 6am-6am</div>
                    <div class="metric-val" id="feed7to7Value">{{ feed_7to7 }}</div>
                    <div class="metric-sub">KG</div>
                </div>
            </a>
        </div>

        <div class="main-grid">
            <div class="panel home-buttons">
                <a class="button-link settings-button" href="{{ url_for('index') }}">
                    <span class="settings-icon">&#9638;</span>
                    <span>Overview</span>
                </a>
                <a class="button-link settings-button" href="{{ url_for('controller_settings_view') }}">
                    <span class="settings-icon">&#9881;</span>
                    <span>Settings</span>
                </a>
            </div>
        </div>

    </div>
    <script>
        const controllerPollMs = {{ refresh_seconds * 1000 }};
        const glowClasses = ['temp-green', 'temp-warn', 'temp-red', 'rh-green', 'rh-warn', 'rh-red', 'flow-green', 'flow-red', 'feed-green', 'feed-red', 'state-green', 'state-warn', 'state-red'];

        function setText(id, value) {
            const el = document.getElementById(id);
            if (el) el.textContent = value;
        }

        function setPillClass(id, cls) {
            const el = document.getElementById(id);
            if (!el) return;
            el.classList.remove('ok', 'warn', 'bad');
            el.classList.add(cls);
        }

        function setGlowClass(id, cls) {
            const el = document.getElementById(id);
            if (!el) return;
            glowClasses.forEach(name => el.classList.remove(name));
            if (cls) el.classList.add(cls);
        }

        function setCropClass(activeCropId) {
            const cls = activeCropId === null ? 'inactive' : 'active';
            ['headerTitle', 'cropHeader', 'cropDateTime', 'birdsBox', 'mortalityBox', 'ageBox'].forEach(id => {
                const el = document.getElementById(id);
                if (!el) return;
                el.classList.remove('active', 'inactive');
                el.classList.add(cls);
            });
        }

        function renderController(data) {
            setText('birdsValue', data.birds_display || data.total_birds);
            setText('birdAgeValue', data.oldest_bird_age);
            setText('cropValue', data.active_crop_code || '--');
            setText('cropDateTime', data.current_datetime || '--');
            setCropClass(data.active_crop_id);
            setText('syncValue', data.sync_short || '--');
            setText('picoValue', data.sensor_status_short || '--');
            setText('loggingValue', data.log_short || '--');
            setText('ethernetValue', data.ethernet_short || '--');
            setText('pushValue', data.push_short || '--');
            if (document.getElementById('alarmValue')) setText('alarmValue', data.alarm_short || '--');
            setPillClass('syncPill', data.sync_class);
            setPillClass('picoPill', data.sensor_class);
            setPillClass('loggingPill', data.log_class);
            setPillClass('ethernetPill', data.ethernet_class);
            setPillClass('pushPill', data.push_class);
            if (document.getElementById('alarmPill')) setPillClass('alarmPill', data.alarm_class);
            setText('tempValue', data.temp_c);
            setText('rhValue', data.rh_pct);
            if (data.climate_today) {
                setText('tempHiLo', 'H ' + data.climate_today.temp_max + ' / L ' + data.climate_today.temp_min);
                setText('rhHiLo', 'H ' + data.climate_today.rh_max + ' / L ' + data.climate_today.rh_min);
            }
            setText('waterValue', data.water_lpm);
            setText('feedValue', data.feed_kg);
            setText('water7to7Value', data.water_7to7);
            setText('feed7to7Value', data.feed_7to7);
            setText('mortalityValue', data.mortality_total);
            setGlowClass('tempTile', data.temp_glow);
            setGlowClass('rhTile', data.rh_glow);
            setGlowClass('waterTile', data.water_glow);
            setGlowClass('feedTile', data.feed_glow);

            const alloc = document.getElementById('allocationSummary');
            if (alloc) {
                if (data.allocation_summary) {
                    alloc.style.display = '';
                    alloc.textContent = data.allocation_summary;
                } else {
                    alloc.style.display = 'none';
                    alloc.textContent = '';
                }
            }

            const banner = document.getElementById('offlineBanner');
            if (banner) {
                if (data.offline_banner) {
                    banner.style.display = '';
                    banner.textContent = data.offline_banner;
                } else {
                    banner.style.display = 'none';
                    banner.textContent = '';
                }
            }

            const picoBanner = document.getElementById('picoFreezeBanner');
            if (picoBanner) {
                if (data.pico_warning_banner) {
                    picoBanner.style.display = '';
                    picoBanner.textContent = data.pico_warning_banner;
                } else {
                    picoBanner.style.display = 'none';
                    picoBanner.textContent = '';
                }
            }

            const picoRecoveryBanner = document.getElementById('picoRecoveryBanner');
            if (picoRecoveryBanner) {
                if (data.pico_recovery_banner) {
                    picoRecoveryBanner.style.display = '';
                    picoRecoveryBanner.textContent = data.pico_recovery_banner;
                } else {
                    picoRecoveryBanner.style.display = 'none';
                    picoRecoveryBanner.textContent = '';
                }
            }

            const lightingTile = document.getElementById('auger-lighting');
            if (lightingTile) {
                setGlowClass('auger-lighting', data.lighting_tile ? data.lighting_tile.glow : (data.lighting_on ? 'state-green' : 'state-warn'));
                const lightingStatus = lightingTile.querySelector('[data-lighting-status]');
                if (lightingStatus) lightingStatus.textContent = data.lighting_tile ? data.lighting_tile.status : (data.lighting_on ? 'On' : 'Off');
            }

            (data.auger_tiles || []).forEach(auger => {
                const tile = document.getElementById('auger-' + auger.key);
                if (!tile) return;
                setGlowClass('auger-' + auger.key, auger.glow);
                const status = tile.querySelector('[data-auger-status]');
                const runtime = tile.querySelector('[data-auger-runtime]');
                const lastRun = tile.querySelector('[data-auger-last-run]');
                if (status) status.textContent = auger.status;
                if (runtime) runtime.textContent = auger.runtime;
                if (lastRun) lastRun.textContent = auger.last_run;
            });

            const panel = document.getElementById('controllerAlertsPanel');
            const list = document.getElementById('controllerAlertsList');
            const alerts = data.controller_alerts || [];
            if (panel && list) {
                if (alerts.length) {
                    panel.style.display = '';
                    list.innerHTML = alerts.map(msg => `<div class="alarm"></div>`).join('');
                    Array.from(list.children).forEach((el, idx) => { el.textContent = alerts[idx]; });
                } else {
                    panel.style.display = 'none';
                    list.innerHTML = '';
                }
            }
        }

        setTimeout(() => {
            document.querySelectorAll('.auto-dismiss').forEach((el) => {
                el.style.display = 'none';
            });
        }, 10000);

        async function pollController() {
            try {
                const resp = await fetch('/api/home-state', { cache: 'no-store' });
                if (!resp.ok) return;
                renderController(await resp.json());
            } catch (err) {
            }
        }

        setInterval(pollController, controllerPollMs);

        if (window.EventSource) {
            const waterSource = new EventSource('/api/water-stream');
            waterSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    setText('waterValue', data.water_lpm);
                    setGlowClass('waterTile', data.water_glow);
                } catch (err) {
                }
            };
        }
    </script>
</body>
</html>
"""


OVERVIEW_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ shed_display_name }} Overview</title>
    <meta name="cdf-theme-native" content="1">
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Semi+Condensed:wght@500;600&display=swap">
    <style>
        :root {
            --page: #eef2f6;
            --card: #ffffff;
            --card-2: #f5f8fb;
            --rule: #d5dde6;
            --track: #dbe3ec;
            --text: #0d2b4a;
            --muted: #4a6078;
            --soft: #31475e;
            --green: #2f9e3a;
            --amber: #f08a12;
            --red: #d64545;
            --blue: #1676b8;
            --water: #1676b8;
            --feed: #d9b86a;
            --steel: #b8bdb6;
            --wall: #7a807a;
        }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body {
            margin: 0;
            min-height: 100vh;
            background: var(--page);
            color: var(--text);
            font-family: "Barlow", "Helvetica Neue", Helvetica, sans-serif;
        }
        .cond { font-family: "Barlow Semi Condensed", "Barlow", "Helvetica Neue", Helvetica, sans-serif; }
        .page { display: flex; flex-direction: column; min-height: 100vh; }

        .topbar {
            min-height: 76px; padding: 10px 28px; display: flex; align-items: center;
            justify-content: space-between; gap: 16px; flex-wrap: wrap; border-bottom: 1px solid var(--rule);
         background: #ffffff;}
        .brand-logo { height: 48px; width: auto; display: block; }
        .topbar-left { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
        /* The shed name box takes all the room between the logo and the status items. */
        .topbar-left.crop-badge { flex: 1 1 auto; min-width: 0; justify-content: space-evenly; align-items: center; align-self: stretch; padding-top: 0; padding-bottom: 0; }
        /* Barlow's letters sit ~2px below the centre of their line box; lift them so they look centred. */
        .topbar-left .shed-title, .topbar-left .subtitle { line-height: 1; margin: 0; position: relative; top: -2px; }
        .topbar-left .subtitle { font-size: 22px; font-weight: 600; color: var(--soft); }
        .hdr-sep { font-size: 28px; font-weight: 700; line-height: 1; color: var(--muted); position: relative; top: -2px; }
        .shed-title { font-size: 30px; font-weight: 600; line-height: 1; }
        .crop-badge {
            padding: 8px 18px; border-radius: 12px; border: 2px solid var(--rule);
            transition: border-color 0.4s, box-shadow 0.4s;
        }
        .crop-badge.active { border-color: #2f9e3a; box-shadow: 0 0 6px rgba(47,158,58,0.5), 0 0 14px rgba(47,158,58,0.25); }
        .crop-badge.inactive { border-color: #d64545; box-shadow: 0 0 6px rgba(214,69,69,0.5), 0 0 14px rgba(214,69,69,0.25); }
        .subtitle { font-size: 18px; color: var(--muted); }
        .topbar-right { display: flex; align-items: center; gap: 24px; }
        .chip { padding: 8px 16px; border-radius: 999px; color: var(--page); font-size: 17px; font-weight: 600; white-space: nowrap; }
        .chip.ok { background: var(--green); }
        .chip.attention { background: var(--amber); }
        .sync { display: flex; align-items: center; gap: 8px; font-size: 16px; color: var(--muted); white-space: nowrap; }
        .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--amber); }
        .dot.ok { background: var(--green); }
        .dot.bad { background: var(--red); }
        .clock { font-size: 30px; font-weight: 500; }

        .banners { padding: 0 24px; }
        .banner { margin-top: 12px; padding: 10px 14px; border-radius: 12px; background: var(--card); font-size: 16px; font-weight: 600; }
        .banner.warn { color: #9a4b00; background: #fff4e5; border: 1px solid #f3b366; }
        .banner.error { color: #8f1f1f; background: #fdecec; border: 1px solid #e3a0a0; }
        .banner.info { color: var(--soft); border: 1px solid var(--rule); }

        .body { flex: 1; padding: 20px 24px; display: flex; gap: 20px; align-items: stretch; }
        .plan-wrap { flex: 0 1 836px; min-width: 0; }
        .plan-stage-box { position: relative; width: 100%; }
        .stage { position: absolute; left: 0; top: 0; width: 836px; height: 480px; transform-origin: 0 0; }
        .abs { position: absolute; }


        .climate-card {
            top: 0; height: 86px; padding: 8px 14px; border-radius: 14px; background: var(--card);
            border: 2px solid var(--rule); display: flex; flex-direction: column; justify-content: center; gap: 2px;
            color: var(--text); text-decoration: none;
        }
        .climate-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
        .glowable { transition: border-color 0.3s, box-shadow 0.3s; }
        .glowable.temp-green, .glowable.flow-green, .glowable.feed-green, .glowable.state-green {
            border-color: #2f9e3a;
            box-shadow: 0 0 8px rgba(47,158,58,0.75), 0 0 16px rgba(47,158,58,0.45), 0 0 28px rgba(47,158,58,0.22);
        }
        .glowable.temp-warn, .glowable.state-warn {
            border-color: #f08a12;
            box-shadow: 0 0 8px rgba(240,138,18,0.75), 0 0 16px rgba(240,138,18,0.45), 0 0 28px rgba(240,138,18,0.22);
        }
        .glowable.temp-red, .glowable.flow-red, .glowable.feed-red, .glowable.state-red {
            border-color: #d64545;
            box-shadow: 0 0 8px rgba(214,69,69,0.75), 0 0 16px rgba(214,69,69,0.45), 0 0 28px rgba(214,69,69,0.22);
        }
        .card-label { font-size: 15px; color: var(--soft); }
        .temp-val { font-size: 44px; font-weight: 600; line-height: 1; }
        .climate-body { display: flex; align-items: center; gap: 6px; }
        .climate-body .unit { align-self: flex-end; margin-bottom: 4px; }
        .hilo-stack { margin-left: auto; display: flex; flex-direction: column; align-items: flex-end; gap: 2px; font-size: 14px; color: var(--muted); line-height: 1.15; }
        .hilo-stack b { color: var(--text); font-weight: 600; }
        .unit { font-size: 22px; color: var(--muted); }
        .hilo { font-size: 14px; color: var(--muted); margin-top: 4px; }
        .temp-right { margin-left: auto; display: flex; flex-direction: column; align-items: flex-end; gap: 4px; text-align: right; }
        .rh-val { font-size: 20px; font-weight: 600; color: var(--text); text-decoration: none; }
        .temp-status { font-size: 14px; font-weight: 600; }

        .water-card {
            top: 0; height: 86px; padding: 8px 16px; border-radius: 14px;
            background: var(--card); display: flex; flex-direction: column; justify-content: center; gap: 2px;
            color: var(--text); text-decoration: none; border: 2px solid transparent;
        }
        .water-ring { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--water); }
        .water-val { font-size: 36px; font-weight: 600; line-height: 1.05; }

        .bin {
            left: 16px; top: 150px; width: 124px; height: 124px; border-radius: 50%; border: 4px solid var(--steel);
            background: var(--card-2); overflow: hidden; box-shadow: 6px 8px 0 rgba(0,0,0,0.3); display: block; color: var(--text); text-decoration: none;
        }
        .bin-fill { position: absolute; left: 0; right: 0; bottom: 0; background: rgba(217,184,106,0.38); transition: height 0.6s; }
        .bin-cap { position: absolute; left: 50%; top: 30%; width: 14px; height: 14px; margin: -7px 0 0 -7px; border-radius: 50%; background: var(--steel); }
        .bin-readout { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; padding-bottom: 14px; line-height: 1.05; }
        .bin-kg { font-size: 22px; font-weight: 600; }
        .bin-kg-unit { font-size: 14px; font-weight: 500; margin-left: 2px; }
        .bin-pct { font-size: 17px; font-weight: 600; color: var(--soft); }
        .bin-label-sub { font-size: 14px; color: var(--muted); }
        .bin-label { width: 156px; text-align: center; }
        .bin-label-name { font-size: 16px; font-weight: 600; }
        .bin-label-kg { font-size: 22px; font-weight: 600; }
        .feed-pipe { width: 36px; height: 6px; background: var(--feed); }

        .shed {
            left: 170px; top: 190px; width: 650px; height: 330px; border: 6px solid var(--wall); border-radius: 6px; overflow: hidden;
            background-color: #c9a458;
            background-image:
                repeating-linear-gradient(28deg, rgba(255,236,170,0.35) 0px, rgba(255,236,170,0.35) 2px, transparent 2px, transparent 9px),
                repeating-linear-gradient(-34deg, rgba(120,88,30,0.28) 0px, rgba(120,88,30,0.28) 2px, transparent 2px, transparent 13px),
                repeating-linear-gradient(72deg, rgba(240,214,140,0.4) 0px, rgba(240,214,140,0.4) 1px, transparent 1px, transparent 17px),
                repeating-linear-gradient(-80deg, rgba(150,112,44,0.22) 0px, rgba(150,112,44,0.22) 3px, transparent 3px, transparent 23px);
            box-shadow: 8px 10px 0 rgba(0,0,0,0.3);
        }
        .shed.lights-off { filter: brightness(0.62) saturate(0.8); }
        .pen { position: absolute; top: 0; height: 318px; display: flex; align-items: center; justify-content: center; }
        .pen.divided { border-right: 3px dashed #5a4722; }
        .pen-card {
            max-width: calc(100% - 16px); padding: 14px 18px; border-radius: 12px; background: rgba(255,255,255,0.95);
            display: flex; flex-direction: column; align-items: center; gap: 4px; text-align: center;
        }
        .pen-name { font-size: 30px; font-weight: 600; line-height: 1.05; color: var(--text); text-decoration: none; }
        .pen-birds { font-size: 18px; color: var(--soft); }
        .pen-card { color: var(--text); text-decoration: none; }
        .pen-card:active { transform: scale(0.98); }
        .shed-empty { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; }
        .add-corner { position: absolute; bottom: 12px; z-index: 2; }
        .add-btn {
            width: 52px; height: 52px; border-radius: 50%; border: 3px solid var(--text); background: rgba(255,255,255,0.95);
            color: var(--text); font-family: inherit; font-size: 34px; font-weight: 500; line-height: 1; cursor: pointer;
            display: flex; align-items: center; justify-content: center; padding: 0 0 4px; opacity: 0.5;
        }
        .add-btn:active { transform: scale(0.95); }
        .add-btn-big { width: 96px; height: 96px; font-size: 64px; padding-bottom: 8px; }
        .add-hint { padding: 8px 14px; border-radius: 10px; background: rgba(255,255,255,0.95); font-size: 16px; color: var(--soft); }

        .modal { position: fixed; inset: 0; z-index: 50; background: rgba(20,22,21,0.72); display: none; align-items: center; justify-content: center; padding: 16px; }
        .modal.open { display: flex; }
        .modal-card { width: 100%; max-width: 560px; max-height: calc(100vh - 32px); overflow-y: auto; padding: 22px; border-radius: 16px; background: var(--card); border: 1px solid var(--rule); display: flex; flex-direction: column; gap: 16px; }
        .modal-title { font-size: 28px; font-weight: 600; }
        .modal-sub { font-size: 16px; color: var(--muted); margin-top: -10px; }
        .field-label { font-size: 15px; color: var(--soft); margin-bottom: 8px; }
        .shed-choices { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 8px; }
        .shed-choice input { position: absolute; opacity: 0; pointer-events: none; }
        .shed-choice span {
            display: flex; align-items: center; justify-content: center; min-height: 52px; border-radius: 10px;
            border: 1px solid #c5d0dc; background: var(--card-2); font-size: 18px; font-weight: 600; cursor: pointer;
        }
        .shed-choice input:checked + span { background: var(--text); color: var(--page); border-color: var(--text); }
        .shed-choice input:focus-visible + span { outline: 3px solid var(--text); outline-offset: 2px; }
        .modal input[type="number"] {
            width: 100%; min-height: 60px; padding: 0 16px; border-radius: 10px; border: 1px solid #c5d0dc;
            background: var(--card-2); color: var(--text); font-family: inherit; font-size: 26px; font-weight: 600;
        }
        .modal-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .modal-actions button { min-height: 56px; border-radius: 12px; font-family: inherit; font-size: 18px; font-weight: 600; cursor: pointer; }
        .btn-primary { border: 0; background: var(--text); color: var(--page); }
        .btn-secondary { border: 1px solid #c5d0dc; background: var(--card-2); color: var(--text); }

        .door { width: 10px; background: repeating-linear-gradient(45deg, var(--amber) 0px, var(--amber) 8px, var(--page) 8px, var(--page) 16px); }
        .door-tick { background: var(--text); }
        .door-label { width: 126px; }
        .end-label { top: 528px; font-size: 14px; color: var(--muted); }

        .panel {
            flex: 1 1 360px; min-width: 300px; padding: 16px 20px; border-radius: 14px; background: var(--card);
            display: flex; flex-direction: column; gap: 10px;
        }
        .panel-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
        .panel-title { font-size: 24px; font-weight: 600; }
        .panel-chip { padding: 5px 12px; border-radius: 999px; font-size: 15px; font-weight: 600; color: var(--page); white-space: nowrap; }
        .gauge { position: relative; height: 22px; }
        .gauge-track { position: absolute; left: 0; right: 0; top: 6px; height: 10px; border-radius: 5px; background: var(--track); }
        .gauge-band { position: absolute; top: 6px; height: 10px; background: rgba(47,158,58,0.55); }
        .gauge-marker { position: absolute; top: 0; width: 4px; height: 22px; margin-left: -2px; border-radius: 2px; background: var(--text); transition: left 0.6s; }
        .gauge-scale { display: flex; justify-content: space-between; gap: 8px; font-size: 14px; color: var(--muted); }
        .advice { font-size: 15px; line-height: 1.3; }
        .gauge-block { display: flex; flex-direction: column; gap: 3px; }
        .gauge-title { font-size: 13px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }
        .rule { height: 1px; background: var(--track); }
        .row { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
        .row-label { font-size: 15px; color: var(--muted); }
        .row-big { font-size: 28px; font-weight: 600; }
        .row-mid { font-size: 24px; font-weight: 600; }
        .row-small { font-size: 15px; }
        .row-link { color: inherit; text-decoration: none; }
        .pen-table { display: grid; grid-template-columns: 1fr auto auto; column-gap: 22px; row-gap: 4px; font-size: 15px; }
        .pen-table > :nth-child(3n+2), .pen-table > :nth-child(3n+3) { text-align: right; }
        .pen-table-head { font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }
        .mort-select {
            min-height: 42px; width: 100%; padding: 0 10px; border-radius: 10px; border: 1px solid #c5d0dc;
            background: var(--card-2); color: var(--text); font-family: inherit; font-size: 16px; font-weight: 600;
        }
        .mort-open {
            min-height: 52px; width: 100%; border: 1px solid #9aa8b6; border-radius: 12px; background: var(--card-2);
            color: var(--text); font-family: inherit; font-size: 18px; font-weight: 600; cursor: pointer;
        }
        .note { font-size: 14px; color: var(--muted); }
        .equip { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-top: 8px; }
        .equip-item { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 12px; background: var(--card); border: 2px solid var(--rule); color: var(--text); text-decoration: none; }
        a.equip-item:active { background: var(--card-2); }
        .panel .equip-item { background: var(--card-2); }
        .equip-head { display: flex; align-items: center; gap: 8px; font-size: 16px; }
        .equip-name { font-weight: 600; }
        .equip-status { margin-left: auto; font-weight: 600; }
        .equip-time { font-size: 14px; color: var(--muted); }
        .equip-time:empty { display: none; }
        .equip-item .dot { background: var(--amber); }
        .equip-item.state-green .dot { background: var(--green); }
        .equip-item.state-red .dot { background: var(--red); }

        .nav { padding: 0 24px 16px; display: flex; gap: 12px; }
        .nav a {
            flex: 1 1 0; min-height: 56px; display: flex; align-items: center; justify-content: center; gap: 8px; text-align: center;
            border: 1px solid #c5d0dc; border-radius: 12px; background: var(--card); color: var(--text);
            font-size: 18px; font-weight: 500; text-decoration: none; padding: 0 8px;
        }
        .nav a[aria-current="page"] { background: var(--text); color: var(--page); border-color: var(--text); font-weight: 600; }
        .nav-badge { min-width: 24px; padding: 1px 7px; border-radius: 999px; background: var(--red); color: var(--page); font-size: 14px; font-weight: 600; }
        a:focus-visible, button:focus-visible { outline: 3px solid var(--text); outline-offset: 2px; }

        @media (min-width: 901px) {
            /* Kiosk layout: one screen, no page scroll. The shed plan scales to fill
               whatever space the left column has; the panel scrolls if it ever overflows. */
            .page { height: 100vh; min-height: 0; }
            .body { min-height: 0; }
            .plan-wrap { flex: 1 1 auto; display: flex; flex-direction: column; min-height: 0; }
            .plan-stage-box { flex: 1 1 auto; min-height: 0; }
            .panel { flex: 0 0 340px; min-width: 0; overflow-y: auto; padding: 14px 18px; gap: 8px; }
            /* Compact right panel so it fits short kiosk screens without scrolling. */
            .panel .panel-title { font-size: 21px; }
            .panel .panel-chip { padding: 3px 10px; font-size: 14px; }
            .panel .gauge { height: 18px; }
            .panel .gauge-track, .panel .gauge-band { top: 5px; height: 8px; }
            .panel .gauge-marker { height: 18px; }
            .panel .gauge-scale { font-size: 12px; }
            .panel .gauge-title { font-size: 11px; }
            .panel .advice { font-size: 14px; }
            .panel .row-label { font-size: 14px; }
            .panel .row-big { font-size: 23px; }
            .panel .row-mid { font-size: 19px; }
            .panel .pen-table { font-size: 14px; row-gap: 2px; }
            .panel .mort-open { min-height: 44px; font-size: 16px; }
            .panel .equip-item { padding: 8px 12px; }
        }
        @media (max-width: 900px) {
            .topbar { padding: 10px 16px; }
            .shed-title { font-size: 28px; }
            .clock { font-size: 24px; }
            .body { flex-direction: column; padding: 16px; }
            .plan-wrap, .panel { flex: none; width: 100%; min-width: 0; }
            .nav { padding: 0 16px 16px; flex-wrap: wrap; }
            .nav a { flex: 1 1 30%; font-size: 16px; }
            .banners { padding: 0 16px; }
        }
    </style>
</head>
<body>
<div class="page">
    <header class="topbar">
        <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
        <div class="topbar-left crop-badge {{ crop_class }}" id="shedTitle">
            <div class="shed-title cond">{{ shed_display_name }}</div>
            <span class="hdr-sep" aria-hidden="true">·</span>
            <div class="subtitle" id="headerBirds">{{ header_birds }}</div>
            <span class="hdr-sep" id="headerDaySep" aria-hidden="true" {% if not header_day %}style="display:none"{% endif %}>·</span>
            <div class="subtitle" id="headerDay" {% if not header_day %}style="display:none"{% endif %}>{{ header_day }}</div>
        </div>
        <div class="topbar-right">
            <div id="overviewChip" class="chip {% if overview_chip_ok %}ok{% else %}attention{% endif %}">{{ overview_chip_text }}</div>
            <div class="sync"><span id="syncDot" class="dot {{ sync_class }}"></span><span id="syncValue">Office sync {{ sync_short }}</span></div>
            <div class="clock cond" id="clockValue">{{ clock_hm }}</div>
        </div>
    </header>

    <div class="banners">
        {% if msg and not hide_home_alerts %}<div class="banner {% if ok %}info{% else %}error{% endif %} auto-dismiss">{{ msg }}</div>{% endif %}
        {% if not hide_home_alerts %}
        <div id="offlineBanner" class="banner warn" {% if not offline_banner %}style="display:none"{% endif %}>{{ offline_banner }}</div>
        <div id="picoFreezeBanner" class="banner error" {% if not pico_warning_banner %}style="display:none"{% endif %}>{{ pico_warning_banner }}</div>
        <div id="picoRecoveryBanner" class="banner warn" {% if not pico_recovery_banner %}style="display:none"{% endif %}>{{ pico_recovery_banner }}</div>
        {% endif %}
    </div>

    <main class="body">
        <section class="plan-wrap" aria-label="Shed plan">
            <div class="plan-stage-box" id="stageBox">
                <div class="stage" id="stage">
                    <a class="abs climate-card glowable {{ temp_glow }}" id="tempCard" href="{{ url_for('temp_settings_view') }}" style="left: {{ layout.temp_x }}px; width: {{ layout.temp_w }}px">
                        <div class="climate-head"><span class="card-label">Temperature</span><span class="temp-status" id="tempStatus" style="color: {{ temp_status_text_color }}">{{ temp_status_short }}</span></div>
                        <div class="climate-body">
                            <div class="temp-val cond" id="tempValue">{{ temp_c }}</div>
                            <div class="unit">°C</div>
                            <div class="hilo-stack" aria-label="Today's high and low">
                                <span>H <b id="tempHi">{{ climate_today.temp_max }}</b></span>
                                <span>L <b id="tempLo">{{ climate_today.temp_min }}</b></span>
                            </div>
                        </div>
                    </a>

                    <a class="abs climate-card glowable {{ rh_glow }}" id="rhCard" href="{{ url_for('rh_settings_view') }}" style="left: {{ layout.rh_x }}px; width: {{ layout.rh_w }}px">
                        <div class="climate-head"><span class="card-label">Humidity</span><span class="temp-status" id="rhStatus" style="color: {{ rh_status_text_color }}">{{ rh_status_short }}</span></div>
                        <div class="climate-body">
                            <div class="temp-val cond" id="rhValue">{{ rh_pct }}</div>
                            <div class="unit">%RH</div>
                            <div class="hilo-stack" aria-label="Today's high and low">
                                <span>H <b id="rhHi">{{ climate_today.rh_max }}</b></span>
                                <span>L <b id="rhLo">{{ climate_today.rh_min }}</b></span>
                            </div>
                        </div>
                    </a>

                    <a class="abs water-card glowable {{ water_glow }}" id="waterCard" href="{{ url_for('water_settings_view') }}" style="left: {{ layout.water_x }}px; width: {{ layout.water_w }}px">
                        <div style="display: flex; align-items: center; gap: 8px" class="card-label"><span class="water-ring"></span><span>Water now</span></div>
                        <div class="water-val cond"><span id="waterValue">{{ water_lpm }}</span> L/min</div>
                    </a>

                    <div class="abs feed-pipe" style="left: {{ layout.pipe_x }}px; top: {{ layout.pipe_y }}px"></div>
                    <a class="abs bin glowable {{ feed_glow }}" id="binCircle" href="{{ url_for('feed_settings_view') }}" aria-label="Feed bin {{ feed_kg }} kg" style="left: {{ layout.bin_x }}px; top: {{ layout.bin_y }}px">
                        <div class="bin-fill" id="binFill" style="height: {{ (feed_live_pct or 0)|round(0) }}%"></div>
                        <div class="bin-cap"></div>
                        <div class="bin-readout">
                            <div class="bin-kg cond"><span id="binLiveKg">{{ feed_kg_live_display }}</span><span class="bin-kg-unit">kg</span></div>
                            <div class="bin-pct cond" id="binPct">{% if feed_live_pct is not none %}{{ feed_live_pct|round(0)|int }}%{% else %}--{% endif %}</div>
                        </div>
                    </a>
                    <div class="abs bin-label" style="left: {{ layout.bin_label_x }}px; top: {{ layout.bin_label_y }}px">
                        <div class="bin-label-name">Feed bin</div>
                        <div class="bin-label-sub">Live weight</div>
                    </div>

                    <div class="abs shed {% if lighting_tile and not lighting_on %}lights-off{% endif %}" id="shedFloor" style="left: {{ layout.shed_x }}px; top: {{ layout.shed_y }}px; width: {{ layout.shed_w }}px; height: {{ layout.shed_h }}px">
                        {% for pen in pens %}
                        <div class="pen {% if pen.divided %}divided{% endif %}" style="left: {{ pen.left }}px; width: {{ pen.width }}px">
                            <a class="pen-card" href="{{ url_for('allocation_view') }}" aria-label="{{ pen.name }}, open allocation">
                                <span class="pen-name cond">{{ pen.name }}</span>
                                <span class="pen-birds"><span data-pen-placed="{{ pen.dest_shed }}">{{ pen.placed_text }}</span> (<span data-pen-birds="{{ pen.dest_shed }}">{{ pen.birds_text }}</span>)</span>
                            </a>
                        </div>
                        {% endfor %}
                        {% if pens %}
                        {% if pen_add_options and pens|length < 4 %}
                        <button type="button" class="add-btn add-corner" style="{{ 'left' if layout.front_left else 'right' }}: 12px" data-side="front" aria-label="Add a pen at the front end">+</button>
                        <button type="button" class="add-btn add-corner" style="{{ 'right' if layout.front_left else 'left' }}: 12px" data-side="rear" aria-label="Add a pen at the rear end">+</button>
                        {% endif %}
                        {% else %}
                        <div class="shed-empty">
                            <button type="button" class="add-btn add-btn-big" data-side="rear" aria-label="Add the first pen">+</button>
                            <div class="add-hint">Shed empty. Tap + to add the first pen.</div>
                        </div>
                        {% endif %}
                    </div>

                    <div class="abs door" style="left: {{ layout.door_x }}px; top: {{ layout.door_y }}px; height: {{ layout.door_h }}px"></div>
                    <div class="abs door-tick" style="left: {{ layout.tick_x }}px; top: {{ layout.door_y }}px; width: 10px; height: 2px"></div>
                    <div class="abs door-tick" style="left: {{ layout.tick_x }}px; top: {{ layout.door_y + layout.door_h - 2 }}px; width: 10px; height: 2px"></div>
                    <div class="abs door-tick" style="left: {{ layout.tick_x + 4 }}px; top: {{ layout.door_y }}px; width: 2px; height: {{ layout.door_h }}px"></div>
                    <div class="abs door-label" style="left: {{ layout.label_x }}px; top: {{ layout.label_y }}px; text-align: {{ layout.label_align }}">
                        <div style="font-size: 16px; font-weight: 600">Door</div>
                    </div>
                    <div class="abs end-label" style="left: {{ layout.front_label_x }}px; top: {{ layout.end_label_y }}px; width: 80px; text-align: {{ 'left' if layout.front_left else 'right' }}">Front end</div>
                    <div class="abs end-label" style="left: {{ layout.rear_label_x }}px; top: {{ layout.end_label_y }}px; width: 80px; text-align: {{ 'right' if layout.front_left else 'left' }}">Rear end</div>
                </div>
            </div>
            {% if auger_tiles %}
            <div class="equip" aria-label="Augers">
                {% for auger in auger_tiles %}
                <a class="equip-item glowable {{ auger.glow }}" id="equip-{{ auger.key }}" href="{{ url_for('auger_runs_view') }}" aria-label="{{ auger.label }}, view auger runs">
                    <div class="equip-head"><span class="dot"></span><span class="equip-name">{{ auger.label }}</span><span class="equip-status" data-equip-status>{{ auger.status }}</span></div>
                    <div class="equip-time" data-equip-runtime>{{ auger.runtime or '' }}</div>
                    <div class="equip-time" data-equip-last-run>{{ auger.last_run or '' }}</div>
                </a>
                {% endfor %}
            </div>
            {% endif %}
        </section>

        <section class="panel" aria-label="Shed conditions">
            <div class="panel-head">
                <div class="panel-title cond">Shed conditions</div>
                <div class="panel-chip" id="panelChip" style="background: {{ temp_status_color if temp_status != 'ok' or rh_ok else '#f08a12' }}">{{ 'No reading' if temp_status == 'none' else ('On target' if temp_status == 'ok' and rh_ok else 'Needs a look') }}</div>
            </div>

            <div class="gauge-block">
                <div class="gauge-title">Temperature</div>
                <div class="gauge">
                    <div class="gauge-track"></div>
                    <div class="gauge-band" style="left: {{ temp_band_left }}%; width: {{ temp_band_width }}%"></div>
                    <div class="gauge-marker" id="gaugeMarker" style="left: {{ temp_marker_pct if temp_marker_pct is not none else 0 }}%; {% if temp_marker_pct is none %}display: none{% endif %}"></div>
                </div>
                <div class="gauge-scale">
                    <div>{{ temp_scale_low }}</div>
                    <div>{{ temp_target_text }}</div>
                    <div>{{ temp_scale_high }}</div>
                </div>
            </div>

            <div class="gauge-block">
                <div class="gauge-title">Humidity</div>
                <div class="gauge">
                    <div class="gauge-track"></div>
                    <div class="gauge-band" style="left: {{ rh_band_left }}%; width: {{ rh_band_width }}%"></div>
                    <div class="gauge-marker" id="rhGaugeMarker" style="left: {{ rh_marker_pct if rh_marker_pct is not none else 0 }}%; {% if rh_marker_pct is none %}display: none{% endif %}"></div>
                </div>
                <div class="gauge-scale">
                    <div>{{ rh_scale_low }}</div>
                    <div>{{ rh_target_text }}</div>
                    <div>{{ rh_scale_high }}</div>
                </div>
            </div>

            <div class="advice" id="tempAdvice" style="color: {{ temp_advice_color }}">{{ temp_advice }}</div>
            <div class="advice" id="rhAdvice" style="color: #9a4b00; {% if not rh_advice %}display: none{% endif %}">{{ rh_advice }}</div>

            <div class="rule"></div>

            <div style="display: flex; flex-direction: column; gap: 8px">
                <a class="row row-link" href="{{ url_for('allocation_view') }}">
                    <div class="row-label">Birds in shed</div>
                    <div class="row-big cond" id="birdsValue">{{ birds_display }}</div>
                </a>
                {% if pens %}
                <div class="pen-table">
                    <div class="pen-table-head"></div>
                    <div class="pen-table-head">Live</div>
                    <div class="pen-table-head">Mortality</div>
                    {% for pen in pens|sort(attribute='number_order') %}
                    <div style="color: var(--muted)">{{ pen.name }}</div>
                    <a class="row-link" href="{{ url_for('allocation_view') }}" data-pen-birds="{{ pen.dest_shed }}">{{ pen.birds_text }}</a>
                    <a class="row-link" href="{{ url_for('mortality_view') }}" data-pen-mortality="{{ pen.dest_shed }}">{{ pen.mortality_text }}</a>
                    {% endfor %}
                </div>
                {% endif %}
            </div>

            <div class="rule"></div>

            <a class="row row-link" href="{{ url_for('water_history_view') }}">
                <div class="row-label">Water yesterday 6am to 6am</div>
                <div class="row-mid cond"><span id="water7to7Value">{{ water_7to7 }}</span> L</div>
            </a>

            <a class="row row-link" href="{{ url_for('feed_history_view') }}">
                <div class="row-label">Feed yesterday 6am to 6am</div>
                <div class="row-mid cond"><span id="feed7to7Value">{{ feed_7to7 }}</span> kg</div>
            </a>

            <div class="rule"></div>

            {% if pens %}
            <button type="button" class="mort-open" id="mortOpen">Add mortality</button>
            {% endif %}

            {% if lighting_tile %}
            <div class="equip-item glowable {{ lighting_tile.glow }}" id="equip-lighting" style="margin-top: auto">
                <div class="equip-head"><span class="dot"></span><span class="equip-name">{{ lighting_tile.label }}</span><span class="equip-status" data-equip-status>{{ lighting_tile.status }}</span></div>
            </div>
            {% endif %}

        </section>
    </main>

    <div class="modal" id="addPenModal" role="dialog" aria-modal="true" aria-labelledby="addPenTitle">
        <form class="modal-card" method="post" action="{{ url_for('add_pen') }}">
            <div class="modal-title cond" id="addPenTitle">Add pen</div>
            <div class="modal-sub" id="addPenSub">At the rear end of the shed</div>
            <input type="hidden" name="side" id="addPenSide" value="rear">
            <input type="hidden" name="return_to" value="index">
            <fieldset style="border: 0; margin: 0; padding: 0">
                <legend class="field-label">Which shed are these birds for?</legend>
                <div class="shed-choices">
                    {% for opt in pen_add_options %}
                    <label class="shed-choice">
                        <input type="radio" name="dest_shed" value="{{ opt.dest_shed }}" required {% if opt.is_home %}checked{% endif %}>
                        <span>{{ opt.label }}</span>
                    </label>
                    {% endfor %}
                </div>
            </fieldset>
            <div>
                <label class="field-label" for="addPenBirds" style="display: block">Birds placed</label>
                <input type="number" id="addPenBirds" name="placed_bird_count" min="1" step="1" inputmode="numeric" required>
            </div>
            <div class="modal-actions">
                <button type="button" class="btn-secondary" id="addPenCancel">Cancel</button>
                <button type="submit" class="btn-primary">Add pen</button>
            </div>
        </form>
    </div>

    {% if pens %}
    <div class="modal" id="mortModal" role="dialog" aria-modal="true" aria-labelledby="mortTitle">
        <form class="modal-card" id="mortForm" method="post" action="{{ url_for('mortality_add_view') }}">
            <div class="modal-title cond" id="mortTitle">Add mortality</div>
            <div class="modal-sub"><a class="row-link" href="{{ url_for('mortality_view') }}">View mortality history</a></div>
            <input type="hidden" name="return_to" value="index">
            <fieldset style="border: 0; margin: 0; padding: 0">
                <legend class="field-label">Which pen?</legend>
                <div class="shed-choices">
                    {% for pen in pens|sort(attribute='number_order') %}
                    <label class="shed-choice">
                        <input type="radio" name="dest_shed" value="{{ pen.dest_shed }}" required {% if loop.first %}checked{% endif %}>
                        <span>{{ pen.name }}</span>
                    </label>
                    {% endfor %}
                </div>
            </fieldset>
            <div>
                <label class="field-label" for="mortDay" style="display: block">Day</label>
                <select id="mortDay" name="mortality_date" class="mort-select">
                    {% for day in mortality_days %}<option value="{{ day.value }}">{{ day.label }}</option>{% endfor %}
                </select>
            </div>
            <div>
                <label class="field-label" for="mortBirds" style="display: block">Birds lost</label>
                <input type="number" id="mortBirds" name="bird_loss" min="1" step="1" inputmode="numeric" required>
            </div>
            <div class="modal-actions">
                <button type="button" class="btn-secondary" id="mortCancel">Cancel</button>
                <button type="submit" class="btn-primary">Record</button>
            </div>
        </form>
    </div>
    {% endif %}

    <nav class="nav" aria-label="Controller pages">
        <a href="{{ url_for('index') }}" aria-current="page">Overview</a>
        <a href="{{ url_for('controller_alarms_view') }}">Alarms <span class="nav-badge" id="alarmBadge" {% if not alarm_count %}style="display:none"{% endif %}>{{ alarm_count }}</span></a>
        <a href="{{ url_for('climate_history_view') }}">Trends</a>
        <a href="{{ url_for('feed_history_view') }}">Feed and water log</a>
        <a href="{{ url_for('classic_view') }}">Classic view</a>
        <a href="{{ url_for('controller_settings_view') }}">Settings</a>
    </nav>
</div>
<script>
    const controllerPollMs = {{ refresh_seconds * 1000 }};
    const pensSignature = {{ pens_signature|tojson }};
    const glowClasses = ['temp-green', 'temp-warn', 'temp-red', 'flow-green', 'flow-red', 'feed-green', 'feed-red', 'state-green', 'state-warn', 'state-red'];

    const mortModal = document.getElementById('mortModal');
    if (mortModal) {
        document.getElementById('mortOpen').addEventListener('click', () => mortModal.classList.add('open'));
        document.getElementById('mortCancel').addEventListener('click', () => mortModal.classList.remove('open'));
        mortModal.addEventListener('click', (event) => { if (event.target === mortModal) mortModal.classList.remove('open'); });
        document.getElementById('mortForm').addEventListener('submit', (event) => {
            const day = document.getElementById('mortDay');
            if (day.value) {
                const pen = document.querySelector('#mortForm input[name="dest_shed"]:checked');
                const penName = pen ? pen.parentElement.textContent.trim() : '';
                const birds = document.getElementById('mortBirds').value;
                if (!confirm('Record ' + birds + ' mortality in ' + penName + ' for ' + day.options[day.selectedIndex].text + '?')) event.preventDefault();
            }
        });
    }

    const addPenModal = document.getElementById('addPenModal');
    function openAddPen(side) {
        document.getElementById('addPenSide').value = side;
        document.getElementById('addPenSub').textContent = {{ (not pens)|tojson }}
            ? 'First pen in the shed'
            : (side === 'front' ? 'At the front end of the shed, before ' : 'At the rear end of the shed, after ') + (side === 'front' ? {{ (pens[0].name if pens else '')|tojson }} : {{ (pens[-1].name if pens else '')|tojson }});
        addPenModal.classList.add('open');
    }
    function closeAddPen() {
        addPenModal.classList.remove('open');
    }
    document.querySelectorAll('.add-btn').forEach(btn => btn.addEventListener('click', () => openAddPen(btn.dataset.side)));
    document.getElementById('addPenCancel').addEventListener('click', closeAddPen);
    addPenModal.addEventListener('click', (event) => { if (event.target === addPenModal) closeAddPen(); });

    function fitStage() {
        const box = document.getElementById('stageBox');
        const stage = document.getElementById('stage');
        if (window.innerWidth > 900) {
            box.style.height = '';
            const scale = Math.max(0.4, Math.min(box.clientWidth / 836, box.clientHeight / 480));
            const left = Math.max(0, (box.clientWidth - 836 * scale) / 2);
            const top = Math.max(0, (box.clientHeight - 480 * scale) / 2);
            stage.style.transform = 'translate(' + left + 'px, ' + top + 'px) scale(' + scale + ')';
            return;
        }
        const scale = Math.min(1.4, box.clientWidth / 836);
        stage.style.transform = 'scale(' + scale + ')';
        box.style.height = (480 * scale) + 'px';
    }
    window.addEventListener('resize', fitStage);
    fitStage();

    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = (value === undefined || value === null) ? '--' : value;
    }
    function setClass(el, cls, options) {
        if (!el) return;
        options.forEach(name => el.classList.remove(name));
        if (cls) el.classList.add(cls);
    }
    function toggleBanner(id, text) {
        const el = document.getElementById(id);
        if (!el) return;
        el.style.display = text ? '' : 'none';
        el.textContent = text || '';
    }

    function render(d) {
        if ((d.pens_signature || '') !== pensSignature && !addPenModal.classList.contains('open') && !(mortModal && mortModal.classList.contains('open'))) {
            window.location.reload();
            return;
        }
        setText('headerBirds', d.header_birds);
        setText('headerDay', d.header_day);
        document.getElementById('headerDay').style.display = d.header_day ? '' : 'none';
        document.getElementById('headerDaySep').style.display = d.header_day ? '' : 'none';
        setClass(document.getElementById('shedTitle'), d.crop_class, ['active', 'inactive']);
        setText('clockValue', d.clock_hm);
        setText('syncValue', 'Office sync ' + (d.sync_short || '--'));
        setClass(document.getElementById('syncDot'), d.sync_class, ['ok', 'warn', 'bad']);
        const chip = document.getElementById('overviewChip');
        setClass(chip, d.overview_chip_ok ? 'ok' : 'attention', ['ok', 'attention']);
        setText('overviewChip', d.overview_chip_text);

        setText('tempValue', d.temp_c);
        setText('rhValue', d.rh_pct);
        if (d.climate_today) {
            setText('tempHi', d.climate_today.temp_max);
            setText('tempLo', d.climate_today.temp_min);
            setText('rhHi', d.climate_today.rh_max);
            setText('rhLo', d.climate_today.rh_min);
        }
        setClass(document.getElementById('tempCard'), d.temp_glow, glowClasses);
        setClass(document.getElementById('rhCard'), d.rh_glow, glowClasses);
        const status = document.getElementById('tempStatus');
        status.textContent = d.temp_status_short;
        status.style.color = d.temp_status_text_color;
        const rhStatus = document.getElementById('rhStatus');
        rhStatus.textContent = d.rh_status_short;
        rhStatus.style.color = d.rh_status_text_color;
        const panelChip = document.getElementById('panelChip');
        panelChip.style.background = (d.temp_status === 'ok' && !d.rh_ok) ? '#f08a12' : d.temp_status_color;
        panelChip.textContent = d.temp_status === 'none' ? 'No reading' : ((d.temp_status === 'ok' && d.rh_ok) ? 'On target' : 'Needs a look');
        const rhMarker = document.getElementById('rhGaugeMarker');
        if (d.rh_marker_pct === null || d.rh_marker_pct === undefined) {
            rhMarker.style.display = 'none';
        } else {
            rhMarker.style.display = '';
            rhMarker.style.left = d.rh_marker_pct + '%';
        }
        const rhAdvice = document.getElementById('rhAdvice');
        rhAdvice.style.display = d.rh_advice ? '' : 'none';
        rhAdvice.textContent = d.rh_advice || '';
        const marker = document.getElementById('gaugeMarker');
        if (d.temp_marker_pct === null || d.temp_marker_pct === undefined) {
            marker.style.display = 'none';
        } else {
            marker.style.display = '';
            marker.style.left = d.temp_marker_pct + '%';
        }
        const advice = document.getElementById('tempAdvice');
        advice.textContent = d.temp_advice;
        advice.style.color = d.temp_advice_color;

        setText('waterValue', d.water_lpm);
        setClass(document.getElementById('waterCard'), d.water_glow, glowClasses);

        setText('binLiveKg', d.feed_kg_live_display);
        const livePct = d.feed_live_pct === null || d.feed_live_pct === undefined ? null : d.feed_live_pct;
        setText('binPct', livePct === null ? '--' : Math.round(livePct) + '%');
        document.getElementById('binFill').style.height = (livePct || 0) + '%';
        setClass(document.getElementById('binCircle'), d.feed_glow, glowClasses);
        setText('water7to7Value', d.water_7to7);
        setText('feed7to7Value', d.feed_7to7);

        setText('birdsValue', d.birds_display || d.total_birds);
        setText('mortalityValue', d.mortality_total);
        (d.pens || []).forEach(pen => {
            document.querySelectorAll('[data-pen-birds="' + pen.dest_shed + '"]').forEach(el => { el.textContent = pen.birds_text; });
            document.querySelectorAll('[data-pen-placed="' + pen.dest_shed + '"]').forEach(el => { el.textContent = pen.placed_text; });
            document.querySelectorAll('[data-pen-mortality="' + pen.dest_shed + '"]').forEach(el => { el.textContent = pen.mortality_text; });
        });

        const shed = document.getElementById('shedFloor');
        if (d.lighting_tile) setClass(shed, d.lighting_on ? '' : 'lights-off', ['lights-off']);

        (d.auger_tiles || []).forEach(auger => {
            const item = document.getElementById('equip-' + auger.key);
            setClass(item, auger.glow, glowClasses);
            if (item) {
                item.querySelector('[data-equip-status]').textContent = auger.status;
                item.querySelector('[data-equip-runtime]').textContent = auger.runtime || '';
                item.querySelector('[data-equip-last-run]').textContent = auger.last_run || '';
            }
        });
        if (d.lighting_tile) {
            const item = document.getElementById('equip-lighting');
            setClass(item, d.lighting_tile.glow, glowClasses);
            if (item) item.querySelector('[data-equip-status]').textContent = d.lighting_tile.status;
        }

        const badge = document.getElementById('alarmBadge');
        badge.style.display = d.alarm_count ? '' : 'none';
        badge.textContent = d.alarm_count;

        toggleBanner('offlineBanner', d.offline_banner);
        toggleBanner('picoFreezeBanner', d.pico_warning_banner);
        toggleBanner('picoRecoveryBanner', d.pico_recovery_banner);
    }

    setTimeout(() => {
        document.querySelectorAll('.auto-dismiss').forEach(el => { el.style.display = 'none'; });
    }, 10000);

    async function poll() {
        try {
            const resp = await fetch('/api/home-state', { cache: 'no-store' });
            if (!resp.ok) return;
            render(await resp.json());
        } catch (err) {
        }
    }
    setInterval(poll, controllerPollMs);

    if (window.EventSource) {
        const waterSource = new EventSource('/api/water-stream');
        waterSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                setText('waterValue', data.water_lpm);
                setClass(document.getElementById('waterCard'), data.water_glow, glowClasses);
            } catch (err) {
            }
        };
    }
</script>
</body>
</html>
"""


CLIMATE_HISTORY_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Daily High Low</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root {
            --bg: #5b5b5b;
            --panel: rgba(115, 115, 115, 0.96);
            --panel-2: rgba(104, 104, 104, 0.98);
            --line: #858585;
            --text: #ececec;
            --muted: #d2d2d2;
            --red: #ff7777;
            --blue: #84d0ff;
        }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { margin: 0; min-height: 100vh; color: var(--text); background: var(--bg); font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }
        .wrap { width: 100%; max-width: 1024px; margin: 0 auto; padding: 16px; }
        .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 20px; padding: 16px; margin-bottom: 14px; }
        h1 { margin: 0 0 4px; font-size: 30px; }
        .sub { color: var(--muted); font-size: 15px; }
        table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
        th, td { padding: 10px 8px; text-align: right; border-bottom: 1px solid var(--line); white-space: nowrap; }
        th:first-child, td:first-child { text-align: left; }
        th { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
        td { font-size: 19px; font-weight: 700; }
        .hi { color: var(--red); }
        .lo { color: var(--blue); }
        .at { display: block; font-size: 12px; font-weight: 400; color: var(--muted); }
        .group { text-align: center !important; }
        .scroll { overflow-x: auto; }
        .button-link {
            display: flex; align-items: center; justify-content: center; min-height: 72px; border-radius: 16px;
            border: 1px solid #d5dde6; background: #ffffff;
            color: var(--text); font-size: 22px; font-weight: 700; text-decoration: none;
        }
        .nav { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    </style>
</head>
<body>
    <div class="wrap">
        <nav class="page-nav" aria-label="Page navigation"><a class="page-nav-btn" href="{{ url_for('index') }}" data-nav-back>← Back</a><a class="page-nav-btn" href="{{ url_for('index') }}">⌂ Overview</a></nav>
        <div class="panel">
            <h1>Daily High / Low</h1>
            <div class="sub">Shed {{ shed_no }} · midnight to midnight · last {{ rows|length }} day{% if rows|length != 1 %}s{% endif %} recorded</div>
        </div>
        <div class="panel scroll">
            {% if rows %}
            <table>
                <thead>
                    <tr><th></th><th class="group" colspan="2">Temp °C</th><th class="group" colspan="2">RH %</th></tr>
                    <tr><th>Day</th><th>High</th><th>Low</th><th>High</th><th>Low</th></tr>
                </thead>
                <tbody>
                    {% for r in rows %}
                    <tr>
                        <td>{{ r.date_label }}{% if r.date == today %}<span class="at">Today so far</span>{% endif %}</td>
                        <td class="hi">{{ r.temp_max }}<span class="at">{{ r.temp_max_at }}</span></td>
                        <td class="lo">{{ r.temp_min }}<span class="at">{{ r.temp_min_at }}</span></td>
                        <td class="hi">{{ r.rh_max }}<span class="at">{{ r.rh_max_at }}</span></td>
                        <td class="lo">{{ r.rh_min }}<span class="at">{{ r.rh_min_at }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="sub">No readings recorded yet. Highs and lows start filling in as soon as the Pico sends temperature and humidity.</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""


EXIT_KIOSK_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Closing Shed Screen</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <div class="wrap" style="max-width: 720px; margin: 0 auto; padding: 40px 24px;">
        <div class="panel" style="padding: 24px;">
            <h1>Closing the shed screen</h1>
            <div class="sub">Returning to the Raspberry Pi desktop. The controller keeps running in the background, so sensors, alarms and office sync carry on. Reboot the Pi to bring the shed screen back.</div>
        </div>
    </div>
</body>
</html>
"""


SETTINGS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Settings</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <meta name="cdf-theme-native" content="1">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Semi+Condensed:wght@500;600&display=swap">
    <style>
        :root {
            --page: #eef2f6; --card: #ffffff; --card-2: #f5f8fb; --rule: #d5dde6; --track: #dbe3ec;
            --text: #0d2b4a; --muted: #4a6078; --soft: #31475e;
            --green: #2f9e3a; --amber: #f08a12; --red: #d64545;
        }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { margin: 0; min-height: 100vh; background: var(--page); color: var(--text); font-family: "Barlow", "Helvetica Neue", Helvetica, sans-serif; }
        .cond { font-family: "Barlow Semi Condensed", "Barlow", "Helvetica Neue", Helvetica, sans-serif; }
        .topbar { min-height: 64px; background: #ffffff; padding: 10px 28px; display: flex; align-items: center; gap: 18px; flex-wrap: wrap; border-bottom: 1px solid var(--rule); }
        .back { display: flex; align-items: center; justify-content: center; min-height: 48px; padding: 0 16px; border-radius: 12px; border: 1px solid #c5d0dc; background: var(--card); color: var(--text); text-decoration: none; font-size: 17px; font-weight: 600; }
        .title { font-size: 34px; font-weight: 600; color: #0b3a6b; }
        .brand-logo { height: 44px; width: auto; display: block; margin-left: auto; }
        .chips { display: flex; gap: 8px; flex-wrap: wrap; }
        .chip { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 999px; background: var(--card); font-size: 15px; color: var(--soft); }
        .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--amber); }
        .dot.ok { background: var(--green); }
        .dot.bad { background: var(--red); }
        .wrap { max-width: 1200px; margin: 0 auto; padding: 14px 24px 20px; }
        .msg { margin-bottom: 16px; padding: 12px 14px; border-radius: 12px; background: var(--card); border: 1px solid var(--rule); font-weight: 600; }
        .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
        .col { display: flex; flex-direction: column; gap: 14px; }
        .section-title { margin: 0 0 6px 4px; font-size: 14px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
        .list { border-radius: 14px; background: var(--card); overflow: hidden; }
        .item { display: flex; align-items: center; gap: 12px; min-height: 50px; padding: 0 18px; color: var(--text); text-decoration: none; font-size: 18px; font-weight: 500; border-top: 1px solid var(--track); }
        .item:first-child { border-top: 0; }
        .item:active { background: var(--card-2); }
        .item-sub { margin-left: auto; font-size: 15px; color: var(--muted); }
        .chev { color: var(--muted); font-size: 22px; line-height: 1; }
        .badge { margin-left: auto; min-width: 26px; padding: 2px 8px; border-radius: 999px; background: var(--red); color: var(--page); font-size: 14px; font-weight: 600; text-align: center; }
        .card { border-radius: 14px; background: var(--card); padding: 18px; display: flex; flex-direction: column; gap: 12px; }
        .row { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; font-size: 16px; }
        .row-label { color: var(--muted); }
        .status { font-size: 18px; font-weight: 600; }
        .status.is-busy { color: var(--amber); }
        .hint { font-size: 14px; color: var(--muted); line-height: 1.35; }
        .btns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .btns form { margin: 0; }
        button {
            width: 100%; min-height: 56px; border-radius: 12px; border: 1px solid #c5d0dc; background: var(--card-2);
            color: var(--text); font-family: inherit; font-size: 17px; font-weight: 600; cursor: pointer;
        }
        button:active { background: var(--track); }
        button:disabled { opacity: 0.5; }
        button.primary { background: var(--text); color: var(--page); border-color: var(--text); }
        button.danger { background: #fdecec; border-color: #e3a0a0; color: #8f1f1f; }
        input[type="number"] {
            width: 100%; min-height: 56px; padding: 0 14px; border-radius: 12px; border: 1px solid #c5d0dc;
            background: var(--card-2); color: var(--text); font-family: inherit; font-size: 20px; font-weight: 600;
        }
        button.mode-toggle { width: auto; min-height: 40px; padding: 0 18px; font-size: 15px; }
        button.mode-toggle.on { background: var(--green); border-color: var(--green); color: var(--page); }
        .mode-chip { padding: 4px 12px; border-radius: 999px; font-size: 15px; font-weight: 600; color: var(--page); background: var(--amber); }
        .mode-chip.live { background: var(--green); }
        details summary { cursor: pointer; color: var(--muted); font-size: 15px; min-height: 32px; display: flex; align-items: center; }
        details .row { margin-top: 6px; font-size: 15px; }
        .mono { font-family: ui-monospace, Menlo, monospace; font-size: 14px; }
        a:focus-visible, button:focus-visible, input:focus-visible { outline: 3px solid var(--text); outline-offset: 2px; }
        @media (max-width: 860px) {
            .topbar { padding: 10px 16px; }
            .title { font-size: 28px; }
            .chips { margin-left: 0; width: 100%; }
            .wrap { padding: 16px; }
            .cols { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <header class="topbar">
        <a class="back" href="{{ url_for('index') }}">← Overview</a>
        <div class="title cond">Settings</div>
        <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
        <div class="chips">
            <div class="chip"><span class="dot {{ sync_class }}"></span>Office sync {{ sync_short }}</div>
            <div class="chip"><span class="dot {{ sensor_class }}"></span>Pico {{ sensor_status_short }}</div>
        </div>
    </header>

    <div class="wrap">
        {% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
        <div class="cols">
            <div class="col">
                <section>
                    <h2 class="section-title">Shed</h2>
                    <nav class="list" aria-label="Shed settings">
                        <a class="item" href="{{ url_for('allocation_view') }}"><span>Shed allocation</span><span class="item-sub">{{ birds_display }}</span><span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('mortality_view') }}"><span>Mortality</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('controller_alarms_view') }}"><span>Alarms</span>{% if alarm_count %}<span class="badge">{{ alarm_count }}</span>{% else %}<span class="item-sub">None active</span>{% endif %}<span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('temp_settings_view') }}"><span>Temperature range</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('rh_settings_view') }}"><span>Humidity range</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('water_settings_view') }}"><span>Water meter</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('feed_settings_view') }}"><span>Feed bin</span><span class="chev" style="margin-left: auto">›</span></a>
                    </nav>
                </section>

                <section>
                    <h2 class="section-title">Controller</h2>
                    <nav class="list" aria-label="Controller tools">
                        <a class="item" href="{{ url_for('controller_health_view') }}"><span>Health</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('controller_events_view') }}"><span>Event log</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('controller_config_view') }}"><span>Config</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('commissioning_view') }}"><span>Commissioning</span><span class="chev" style="margin-left: auto">›</span></a>
                        <a class="item" href="{{ url_for('hx711_diagnostics_view') }}"><span>Feed scale diagnostics</span><span class="chev" style="margin-left: auto">›</span></a>
                    </nav>
                </section>
            </div>

            <div class="col">
                <section>
                    <h2 class="section-title">Software</h2>
                    <div class="card">
                        <div class="row"><span class="status" id="controllerUpdateStatus">{{ update_status.status }}</span></div>
                        <div class="row"><span class="row-label">Last checked</span><span id="controllerUpdateChecked">{{ update_checked_at }}</span></div>
                        {% if update_status.restart_required %}
                        <div class="hint">Latest code has been pulled. Restart the controller to run the new version.</div>
                        {% endif %}
                        <div class="btns">
                            <form id="controllerUpdateCheckForm" method="post" action="{{ url_for('check_update_view') }}">
                                <button id="controllerUpdateCheckButton" type="submit">Check for update</button>
                            </form>
                            <form id="controllerUpdateApplyForm" method="post" action="{{ url_for('apply_update_view') }}" {% if not update_status.update_available %}style="display:none;"{% endif %}>
                                <button class="primary" type="submit">Install update</button>
                            </form>
                        </div>
                        <details>
                            <summary>Version details</summary>
                            <div class="row"><span class="row-label">Branch</span><span class="mono" id="controllerUpdateBranch">{{ update_status.branch }}</span></div>
                            <div class="row"><span class="row-label">Installed</span><span class="mono" id="controllerUpdateCurrent">{{ update_status.local_commit }}</span></div>
                            <div class="row"><span class="row-label">Latest</span><span class="mono" id="controllerUpdateLatest">{{ update_status.remote_commit }}</span></div>
                        </details>
                        <div class="row"><span class="row-label">Nightly auto update</span>
                            <form method="post" action="{{ url_for('toggle_auto_update_view') }}" style="margin: 0">
                                <input type="hidden" name="enabled" value="{{ '0' if auto_update_enabled else '1' }}">
                                <button type="submit" class="mode-toggle {% if auto_update_enabled %}on{% endif %}" aria-pressed="{{ 'true' if auto_update_enabled else 'false' }}">{{ 'On' if auto_update_enabled else 'Off' }}</button>
                            </form>
                        </div>
                        <div class="row"><span class="row-label">Last nightly check</span><span style="text-align: right">{{ auto_update_last }}</span></div>
                        <div class="hint">Shortly after midnight the controller checks GitHub and, if it is on a different version, installs the update and restarts. Pico firmware changes are deployed automatically.</div>
                    </div>
                </section>

                <section>
                    <h2 class="section-title">Mode</h2>
                    <div class="card">
                        <div class="row"><span class="row-label">Current mode</span><span class="mode-chip {% if current_mode_key == 'live' %}live{% endif %}">{{ current_mode }}</span></div>
                        <div class="hint">Use commissioning while wiring and proving sensors. Go live once the shed is ready for normal alarms. Switching needs the mode PIN.</div>
                        <form method="post" action="{{ url_for('switch_controller_mode_view') }}" class="btns">
                            <input type="hidden" name="target_mode" value="{{ next_mode_key }}">
                            <input type="number" name="mode_pin" inputmode="numeric" enterkeyhint="done" placeholder="Mode PIN" aria-label="Mode PIN">
                            <button type="submit">{{ "Go live" if next_mode_key == "live" else "Back to commissioning" }}</button>
                        </form>
                    </div>
                </section>

                <section>
                    <h2 class="section-title">Power</h2>
                    <div class="card">
                        <div class="btns">
                            <form method="post" action="{{ url_for('controller_exit_kiosk_view') }}" onsubmit="return confirm('Close the shed screen and go to the Raspberry Pi desktop? The controller keeps running in the background.');" style="grid-column: 1 / -1">
                                <button type="submit">⇱ Exit to desktop</button>
                            </form>
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
(function () {
    const form = document.getElementById('controllerUpdateCheckForm');
    if (!form) return;
    const button = document.getElementById('controllerUpdateCheckButton');
    const statusEl = document.getElementById('controllerUpdateStatus');
    const branchEl = document.getElementById('controllerUpdateBranch');
    const currentEl = document.getElementById('controllerUpdateCurrent');
    const latestEl = document.getElementById('controllerUpdateLatest');
    const checkedEl = document.getElementById('controllerUpdateChecked');
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
            checkedEl.textContent = data.checked_at_label || '--';
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


HEALTH_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Controller Health</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root {
            --bg: #5b5b5b;
            --panel: rgba(115, 115, 115, 0.96);
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
            max-width: 1024px;
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
        .detail-list {
            display: grid;
            gap: 10px;
        }
        .detail {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            padding: 12px 0;
            border-bottom: 1px solid #d5dde6;
            font-size: 18px;
        }
        .detail:last-child {
            border-bottom: 0;
        }
        .label {
            color: var(--muted);
        }
        .alarm-list {
            display: grid;
            gap: 10px;
            margin-top: 16px;
        }
        .alarm {
            padding: 12px 14px;
            border-radius: 14px;
            border: 1px solid rgba(214,69,69,0.35);
            background: #fdecec;
            font-size: 17px;
        }
        .mono {
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 14px;
            color: var(--muted);
            word-break: break-word;
            margin-top: 16px;
        }
    </style>
</head>
<body>
    <div class="wrap">
        <nav class="page-nav" aria-label="Page navigation"><a class="page-nav-btn" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a><a class="page-nav-btn" href="{{ url_for('index') }}">⌂ Overview</a></nav>
        <div class="panel">
            <h1>Shed {{ shed_no }} Controller Health</h1>
            <div class="sub">Dashboard connection, sync status, serial state, and controller diagnostics.</div>
            <div class="detail-list">
                <div class="detail"><span class="label">Dashboard</span><span>{{ dashboard_url }}</span></div>
                <div class="detail"><span class="label">Controller IP</span><span>{{ controller_ip }}</span></div>
                <div class="detail"><span class="label">Serial Port</span><span>{{ serial_port }}</span></div>
                <div class="detail"><span class="label">Last Sensor</span><span>{{ last_sensor }} • {{ last_sensor_age }}</span></div>
                <div class="detail"><span class="label">Last Sync</span><span>{{ last_sync }} • {{ last_sync_age }}</span></div>
                <div class="detail"><span class="label">Last Backup</span><span>{{ last_backup }} • {{ last_backup_age }}</span></div>
                <div class="detail"><span class="label">Backup Status</span><span>{{ last_backup_status }}</span></div>
                <div class="detail"><span class="label">Controller State Version</span><span>{{ state_version }}</span></div>
                <div class="detail"><span class="label">State Updated</span><span>{{ state_updated_at }} • {{ state_updated_age }}</span></div>
                <div class="detail"><span class="label">Office Sync Version</span><span>{{ last_seen_office_sync_version }}</span></div>
                <div class="detail"><span class="label">Office Sync Seen</span><span>{{ last_seen_office_sync_at }} • {{ last_seen_office_sync_age }}</span></div>
                {% for auger in auger_rows %}
                <div class="detail"><span class="label">{{ auger.label }}</span><span>{{ auger.status }} • {{ auger.runtime }} • {{ auger.last_run }}</span></div>
                {% endfor %}
                <div class="detail"><span class="label">Lighting State</span><span>{{ lighting_status }}{% if lighting_runtime %} • {{ lighting_runtime }}{% endif %} • {{ lighting_last_change }}</span></div>
                <div class="detail"><span class="label">Pico Trace</span><span>{{ pico_trace_summary or "--" }}</span></div>
                <div class="detail"><span class="label">Auto Recovery</span><span>{{ pico_recovery_status or "--" }}</span></div>
                <div class="detail"><span class="label">Crop Active</span><span>{{ "Yes" if entry.crop_active == 1 else "No" }}</span></div>
                <div class="detail"><span class="label">Started</span><span>{{ started_at }}</span></div>
                <div class="detail"><span class="label">Updated By</span><span>{{ entry.updated_by }}</span></div>
                <div class="detail"><span class="label">Updated At</span><span>{{ updated_at }}</span></div>
            </div>
            {% if controller_alerts %}
            <div class="alarm-list">
                {% for alarm in controller_alerts %}
                <div class="alarm">{{ alarm }}</div>
                {% endfor %}
            </div>
            {% endif %}
            <div class="mono">{{ last_serial_line }}</div>
        </div>
    </div>
</body>
</html>
"""


CONFIG_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Controller Config</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root { --bg:#5b5b5b; --panel:rgba(115,115,115,0.96); --line:#8a8a8a; --text:#ececec; --muted:#d2d2d2; }
        body { margin:0; color: var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background: #5b5b5b; }
        .wrap { max-width:1024px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color: var(--text); text-decoration:none; font-size:18px; }
        .grid { display:grid; grid-template-columns:1.2fr 0.8fr; gap:16px; }
        .panel { background: var(--panel); border: 1px solid var(--line); border-radius:20px; padding:18px; }
        h1 { margin:0 0 8px 0; font-size:38px; }
        .sub { color: var(--muted); margin-bottom:16px; font-size:18px; }
        .field { margin-bottom:14px; }
        .group-title { margin:18px 0 10px 0; font-size:18px; color: var(--text); }
        label { display:block; color: var(--muted); margin-bottom:8px; font-size:15px; }
        input[type="text"], input[type="number"], select { width:100%; min-height:64px; border-radius:16px; border: 1px solid var(--line); background: #f5f8fb; color: var(--text); font-size:24px; padding:10px 14px; box-sizing:border-box; }
        .value-readout { min-height:64px; border-radius:16px; border: 1px solid var(--line); background: #5f5f5f; color: var(--text); font-size:22px; padding:14px; box-sizing:border-box; display:flex; align-items:center; word-break:break-word; }
        .check { display:flex; align-items:center; justify-content:space-between; padding:12px 0; border-bottom: 1px solid #d5dde6; font-size:18px; }
        .check:last-child { border-bottom: 0; }
        input[type="checkbox"] { width:28px; height:28px; }
        button, .button-link { display:block; width:100%; min-height:68px; border-radius:16px; border: 1px solid #d5dde6; background: #ffffff; color: var(--text); font-size:20px; font-weight:700; text-decoration:none; text-align:center; line-height:68px; cursor:pointer; }
        .button-link { margin-top:12px; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:12px 0; border-bottom: 1px solid #d5dde6; font-size:16px; }
        .detail:last-child { border-bottom: 0; }
        .hint { color: var(--muted); font-size:15px; margin-top:12px; }
        .auger-grid { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; margin-top:10px; }
        .auger-card { border: 1px solid #d5dde6; border-radius:16px; padding:14px; background: #636363; }
        .auger-card h3 { margin:0 0 12px 0; font-size:18px; color: var(--text); }
        .auger-card .check { padding:10px 0 0 0; border-bottom: 0; }
        @media (max-width: 900px) { .grid { grid-template-columns:1fr; } .auger-grid { grid-template-columns:1fr; } }
    </style>
</head>
<body>
    <div class="wrap">
        <nav class="page-nav" aria-label="Page navigation"><a class="page-nav-btn" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a><a class="page-nav-btn" href="{{ url_for('index') }}">⌂ Overview</a></nav>
        <div class="grid">
            <div class="panel">
                <h1>Shed {{ shed_no }} Controller Config</h1>
                <div class="sub">Local controller identity, office URL, serial settings, and refresh behavior.</div>
                <form method="post" action="{{ url_for('save_controller_config_view') }}">
                    <div class="group-title">Identity & Network</div>
                    <div class="field"><label for="shed_no">Shed Number</label><input id="shed_no" type="number" name="shed_no" step="1" inputmode="numeric" value="{{ cfg.shed_no }}"></div>
                    <div class="field"><label for="dashboard_url">Office Dashboard URL</label><input id="dashboard_url" type="text" name="dashboard_url" inputmode="url" enterkeyhint="done" data-cdf-urlpad="1" value="{{ cfg.dashboard_url }}"></div>
                    <div class="field"><label>This Device IP</label><div class="value-readout">{{ host_ips }}</div></div>
                    <div class="group-title">Pico Serial</div>
                    <div class="field"><label for="serial_port">Serial Port</label><input id="serial_port" type="text" name="serial_port" value="{{ cfg.serial_port }}"></div>
                    <div class="field"><label for="serial_baudrate">Serial Baudrate</label><input id="serial_baudrate" type="number" name="serial_baudrate" step="1" inputmode="numeric" value="{{ cfg.serial_baudrate }}"></div>
                    <div class="group-title">Display & Sync</div>
                    <div class="field"><label for="touch_refresh_seconds">Home Poll Seconds</label><input id="touch_refresh_seconds" type="number" name="touch_refresh_seconds" step="0.05" min="0.25" inputmode="decimal" value="{{ cfg.touch_refresh_seconds }}"></div>
                    <div class="check"><span>Serial Enabled</span><input type="checkbox" name="serial_enabled" {% if cfg.serial_enabled %}checked{% endif %}></div>
                    <div class="check"><span>Auto Sync On Change</span><input type="checkbox" name="sync_on_sensor_update" {% if cfg.sync_on_sensor_update %}checked{% endif %}></div>
                    <div class="group-title">Shed Layout</div>
                    <div class="sub" style="margin-bottom:10px;">How the shed plan on the overview is drawn, as seen on this screen.</div>
                    <div class="field"><label for="layout_front_end">Front end of shed</label>
                        <select id="layout_front_end" name="layout_front_end">
                            <option value="left" {% if cfg.layout_front_end == 'left' %}selected{% endif %}>Left side of screen</option>
                            <option value="right" {% if cfg.layout_front_end == 'right' %}selected{% endif %}>Right side of screen</option>
                        </select>
                    </div>
                    <div class="field"><label for="layout_bin_corner">Feed bin position</label>
                        <select id="layout_bin_corner" name="layout_bin_corner">
                            <option value="top-left" {% if cfg.layout_bin_corner == 'top-left' %}selected{% endif %}>Top left corner</option>
                            <option value="top-right" {% if cfg.layout_bin_corner == 'top-right' %}selected{% endif %}>Top right corner</option>
                            <option value="bottom-left" {% if cfg.layout_bin_corner == 'bottom-left' %}selected{% endif %}>Bottom left corner</option>
                            <option value="bottom-right" {% if cfg.layout_bin_corner == 'bottom-right' %}selected{% endif %}>Bottom right corner</option>
                        </select>
                    </div>
                    <div class="field"><label for="layout_door_end">Door</label>
                        <select id="layout_door_end" name="layout_door_end">
                            <option value="left" {% if cfg.layout_door_end == 'left' %}selected{% endif %}>Left end wall</option>
                            <option value="right" {% if cfg.layout_door_end == 'right' %}selected{% endif %}>Right end wall</option>
                        </select>
                    </div>
                    <div class="group-title">Augers</div>
                    <div class="sub" style="margin-bottom:10px;">Rename each auger tile and decide whether it should appear and be monitored on this shed.</div>
                    <div class="auger-grid">
                        <div class="auger-card">
                            <h3>Cross Auger</h3>
                            <div class="field"><label for="cross_auger_label">Label</label><input id="cross_auger_label" type="text" name="cross_auger_label" value="{{ cfg.cross_auger_label }}"></div>
                            <div class="check"><span>Enabled</span><input type="checkbox" name="cross_auger_enabled" {% if cfg.cross_auger_enabled %}checked{% endif %}></div>
                        </div>
                        <div class="auger-card">
                            <h3>Left Auger</h3>
                            <div class="field"><label for="auger_left_label">Label</label><input id="auger_left_label" type="text" name="auger_left_label" value="{{ cfg.auger_left_label }}"></div>
                            <div class="check"><span>Enabled</span><input type="checkbox" name="auger_left_enabled" {% if cfg.auger_left_enabled %}checked{% endif %}></div>
                        </div>
                        <div class="auger-card">
                            <h3>Right Auger</h3>
                            <div class="field"><label for="auger_right_label">Label</label><input id="auger_right_label" type="text" name="auger_right_label" value="{{ cfg.auger_right_label }}"></div>
                            <div class="check"><span>Enabled</span><input type="checkbox" name="auger_right_enabled" {% if cfg.auger_right_enabled %}checked{% endif %}></div>
                        </div>
                        <div class="auger-card">
                            <h3>Lighting</h3>
                            <div class="field"><label for="lighting_label">Label</label><input id="lighting_label" type="text" name="lighting_label" value="{{ cfg.lighting_label }}"></div>
                            <div class="check"><span>Enabled</span><input type="checkbox" name="lighting_enabled" {% if cfg.lighting_enabled %}checked{% endif %}></div>
                        </div>
                    </div>
                    <button type="submit">Save Controller Config</button>
                </form>
                <div class="hint">If you change shed number or network settings, the controller app should be restarted after saving.</div>
            </div>
            <div class="panel">
                <h1>Backup & Export</h1>
                <div class="sub">Automatic backups run hourly. You can also create or download exports here.</div>
                <div class="detail"><span>Last Backup</span><span>{{ last_backup }}</span></div>
                <div class="detail"><span>Status</span><span>{{ last_backup_status }}</span></div>
                <a class="button-link" href="{{ url_for('create_backup_view') }}">Create Backup Now</a>
                <a class="button-link" href="{{ url_for('download_latest_backup_view') }}">Download Latest Backup ZIP</a>
                <a class="button-link" href="{{ url_for('export_config_view') }}">Export Config JSON</a>
                <a class="button-link" href="{{ url_for('export_state_view') }}">Export State JSON</a>
            </div>
        </div>
    </div>
</body>
</html>
"""


ALARMS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Alarms</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root { --bg:#5b5b5b; --panel:rgba(115,115,115,0.96); --line:#8a8a8a; --text:#ececec; --muted:#d2d2d2; --green:#7be1aa; --amber:#ffd06a; --red:#ff7777; }
        body { margin:0; color: var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background: #5b5b5b; }
        .wrap { max-width:1024px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color: var(--text); text-decoration:none; font-size:18px; }
        .panel { background: var(--panel); border: 1px solid var(--line); border-radius:20px; padding:18px; }
        h1 { margin:0 0 8px 0; font-size:38px; }
        .sub { color: var(--muted); margin-bottom:16px; font-size:18px; }
        .alarm-list { display:grid; gap:12px; }
        .alarm { padding:14px 16px; border-radius:16px; border: 1px solid #d5dde6; background: #f5f8fb; }
        .alarm.bad { border-color: rgba(214,69,69,0.45); }
        .alarm.warn { border-color: rgba(240,138,18,0.45); }
        .alarm-title { font-size:20px; font-weight:700; margin-bottom:4px; }
        .alarm-detail { color: var(--muted); font-size:16px; }
        .okbox { padding:18px; border-radius:16px; border: 1px solid rgba(47,158,58,0.35); color: var(--green); background: rgba(30,57,42,0.25); font-size:20px; }
        .section-title { margin:22px 0 12px 0; font-size:24px; font-weight:700; }
        .history-table { width:100%; border-collapse:collapse; }
        .history-table th, .history-table td { text-align:left; padding:12px 10px; border-bottom: 1px solid #d5dde6; font-size:16px; vertical-align:top; }
        .history-table th { color: var(--muted); font-weight:700; }
        .history-pill { display:inline-block; padding:4px 10px; border-radius:999px; border: 1px solid #d5dde6; font-size:13px; font-weight:700; }
        .history-pill.bad { border-color: rgba(214,69,69,0.45); color: var(--red); }
        .history-pill.ok { border-color: rgba(47,158,58,0.45); color: var(--green); }
        button { display:block; width:100%; min-height:68px; border-radius:16px; border: 1px solid #d5dde6; background: #ffffff; color: var(--text); font-size:20px; font-weight:700; cursor:pointer; margin-top:16px; }
    </style>
</head>
<body>
    <div class="wrap">
        <nav class="page-nav" aria-label="Page navigation"><a class="page-nav-btn" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a><a class="page-nav-btn" href="{{ url_for('index') }}">⌂ Overview</a></nav>
        <div class="panel">
            <h1>Shed {{ shed_no }} Alarms</h1>
            <div class="sub">Stale sensor checks, office link checks, push failures, and controller alarms.</div>
            {% if alarm_rows %}
            <div class="alarm-list">
                {% for alarm in alarm_rows %}
                <div class="alarm {{ alarm.severity }}">
                    <div class="alarm-title">{{ alarm.title }}</div>
                    <div class="alarm-detail">{{ alarm.detail }}</div>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <div class="okbox">No active controller alarms.</div>
            {% endif %}
            <div class="section-title">Previous Alarms</div>
            {% if alarm_history_rows %}
            <table class="history-table">
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Event</th>
                        <th>Alarm</th>
                        <th>Detail</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in alarm_history_rows %}
                    <tr>
                        <td>{{ row.ts_label }}</td>
                        <td><span class="history-pill {{ row.event_class }}">{{ row.event_label }}</span></td>
                        <td>{{ row.title if row.title else "--" }}</td>
                        <td>{{ row.detail if row.detail else "--" }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="okbox">No previous alarms logged yet.</div>
            {% endif %}
            <form method="post" action="{{ url_for('clear_controller_alarms_view') }}">
                <button type="submit">Clear Alarms</button>
            </form>
        </div>
    </div>
</body>
</html>
"""


CONTROLLER_EVENTS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Event Log</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root { --panel:rgba(115,115,115,0.96); --line:#8a8a8a; --text:#ececec; --muted:#d2d2d2; }
        body { margin:0; color: var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background: #5b5b5b; }
        .wrap { max-width:1300px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color: var(--text); text-decoration:none; font-size:18px; }
        .panel { background: var(--panel); border: 1px solid var(--line); border-radius:20px; padding:18px; }
        h1 { margin:0 0 8px 0; font-size:38px; }
        .sub { color: var(--muted); margin-bottom:16px; font-size:18px; }
        table { width:100%; border-collapse:collapse; font-size:14px; }
        th, td { padding:10px 8px; border-bottom: 1px solid #d5dde6; text-align:left; vertical-align:top; }
        th { color: #0d2b4a; }
    </style>
</head>
<body>
    <div class="wrap">
        <nav class="page-nav" aria-label="Page navigation"><a class="page-nav-btn" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a><a class="page-nav-btn" href="{{ url_for('index') }}">⌂ Overview</a></nav>
        <div class="panel">
            <h1>Shed {{ shed_no }} Event Log</h1>
            <div class="sub">Recent local controller events and sync actions.</div>
            <table>
                <thead><tr><th>Time</th><th>Type</th><th>Message</th><th>Detail</th></tr></thead>
                <tbody>
                    {% for row in rows %}
                    <tr><td>{{ row.ts_label }}</td><td>{{ row.event_type }}</td><td>{{ row.message }}</td><td>{{ row.detail if row.detail else "--" }}</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""


COMMISSIONING_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Commissioning</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root { --panel:rgba(115,115,115,0.96); --panel2:#686868; --line:#8a8a8a; --text:#ececec; --muted:#d2d2d2; }
        body { margin:0; color: var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background: #5b5b5b; }
        .wrap { max-width:1200px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color: var(--text); text-decoration:none; font-size:18px; }
        .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
        .panel { background: var(--panel); border: 1px solid var(--line); border-radius:20px; padding:18px; }
        h1 { margin:0 0 8px 0; font-size:38px; }
        .sub { color: var(--muted); margin-bottom:16px; font-size:18px; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom: 1px solid #d5dde6; font-size:16px; }
        .detail:last-child { border-bottom: 0; }
        .label { color: var(--muted); }
        .mono { font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:13px; color: #0d2b4a; word-break:break-word; background: var(--panel2); border: 1px solid #d5dde6; border-radius:14px; padding:12px; }
        @media (max-width: 900px) { .grid { grid-template-columns:1fr; } }
    </style>
</head>
<body>
    <div class="wrap">
        <nav class="page-nav" aria-label="Page navigation"><a class="page-nav-btn" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a><a class="page-nav-btn" href="{{ url_for('index') }}">⌂ Overview</a></nav>
        <div class="panel" style="margin-bottom:16px;">
            <h1>Shed {{ shed_no }} Commissioning</h1>
            <div class="sub">Raw sensor values, sync versions, and wiring diagnostics.</div>
            <div class="detail"><span class="label">Controller State Version</span><span>{{ state_version }}</span></div>
            <div class="detail"><span class="label">State Updated</span><span>{{ state_updated_at }} • {{ state_updated_age }}</span></div>
            <div class="detail"><span class="label">Office Sync Version</span><span>{{ last_seen_office_sync_version }}</span></div>
            <div class="detail"><span class="label">Office Sync Seen</span><span>{{ last_seen_office_sync_at }} • {{ last_seen_office_sync_age }}</span></div>
        </div>
        <div class="grid">
            <div class="panel">
                <h1>Live Parsed</h1>
                <div class="detail"><span class="label">Temp C</span><span>{{ temp_c }}</span></div>
                <div class="detail"><span class="label">RH %</span><span>{{ rh_pct }}</span></div>
                <div class="detail"><span class="label">Water L/PM</span><span>{{ water_lpm }}</span></div>
                <div class="detail"><span class="label">Flow Total Pulses</span><span>{{ flow_total_pulses }}</span></div>
                <div class="detail"><span class="label">Feed KG</span><span>{{ feed_kg }}</span></div>
                <div class="detail"><span class="label">Feed Raw Smoothed</span><span>{{ feed_raw_units }}</span></div>
                <div class="detail"><span class="label">Lighting</span><span>{{ lighting_status }}</span></div>
                <div class="detail"><span class="label">Pico Trace</span><span>{{ pico_trace_summary or "--" }}</span></div>
                <div class="detail"><span class="label">Auto Recovery</span><span>{{ pico_recovery_status or "--" }}</span></div>
            </div>
            <div class="panel">
                <h1>Raw Packet</h1>
                <div class="mono">{{ raw_json }}</div>
                <h1 style="margin-top:16px;">Last Serial Line</h1>
                <div class="mono">{{ last_serial_line }}</div>
            </div>
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
    <title>Shed {{ shed_no }} {{ metric_title }}</title>
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
        <nav class="page-nav" aria-label="Page navigation"><a class="page-nav-btn" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a><a class="page-nav-btn" href="{{ url_for('index') }}">⌂ Overview</a></nav>
        {% if log_tab in ['feed', 'water'] %}
        <div class="log-tabs" role="tablist" aria-label="Log type">
            <a class="log-tab {% if log_tab == 'feed' %}active{% endif %}" role="tab" aria-selected="{{ 'true' if log_tab == 'feed' else 'false' }}" href="{{ url_for('feed_history_view') }}">Feed</a>
            <a class="log-tab {% if log_tab == 'water' %}active{% endif %}" role="tab" aria-selected="{{ 'true' if log_tab == 'water' else 'false' }}" href="{{ url_for('water_history_view') }}">Water</a>
        </div>
        {% endif %}
        <div class="panel">
            <div class="view-head">
                <div>
                    <h1>Shed {{ shed_no }} {{ metric_title }}</h1>
                    <div class="sub" id="viewSub">Current crop {{ crop_code }}. Daily totals, 6am to 6am. Tap a day to see its hours.</div>
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
            <div class="empty">No history available for the current crop yet.</div>
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
        document.getElementById('viewSub').textContent = 'Current crop {{ crop_code }}. Daily totals, 6am to 6am. Tap a day to see its hours.';
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


AUGER_RUNS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Auger Runs</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root {
            --bg: #5b5b5b;
            --panel: rgba(115, 115, 115, 0.96);
            --line: #8a8a8a;
            --text: #ececec;
            --muted: #d2d2d2;
        }
        body { margin: 0; color: var(--text); font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; background: #5b5b5b; }
        .wrap { max-width: 1100px; margin: 0 auto; padding: 18px; }
        .topbar { margin-bottom: 16px; }
        .topbar a { color: var(--text); text-decoration: none; font-size: 18px; }
        .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 20px; padding: 18px; margin-bottom: 16px; }
        h1 { margin: 0 0 8px 0; font-size: 38px; }
        .sub { color: var(--muted); margin-bottom: 16px; font-size: 18px; }
        table { width: 100%; border-collapse: collapse; font-size: 15px; }
        th, td { border-bottom: 1px solid #d5dde6; padding: 10px 8px; text-align: left; }
        th { color: var(--muted); }
        .empty { color: var(--muted); font-size: 18px; }
    </style>
</head>
<body>
    <div class="wrap">
        <nav class="page-nav" aria-label="Page navigation"><a class="page-nav-btn" href="{{ url_for('index') }}" data-nav-back>← Back</a><a class="page-nav-btn" href="{{ url_for('index') }}">⌂ Overview</a></nav>
        <div class="panel">
            <h1>Shed {{ shed_no }} Auger Runs</h1>
            <div class="sub">Completed auger run timestamps and durations recorded by this controller.</div>
            {% if rows %}
            <table>
                <thead>
                    <tr>
                        <th>Auger</th>
                        <th>Started</th>
                        <th>Stopped</th>
                        <th>Duration</th>
                        <th>Runs</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in rows %}
                    <tr>
                        <td>{{ row.auger_label }}</td>
                        <td>{{ row.started_at }}</td>
                        <td>{{ row.stopped_at }}</td>
                        <td>{{ row.duration }}</td>
                        <td>{{ row.run_count_label }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="empty">No auger runs recorded yet.</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""


# Shared look for the shed's number entry pages (allocation, mortality and the setup pages), matching Settings.
ENTRY_PAGE_HEAD = """
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
    </style>
"""


RANGE_SETTINGS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} {{ title }}</title>
""" + ENTRY_PAGE_HEAD + """
    <style>
        .limits { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .band { position: relative; height: 22px; margin: 26px 0 8px; border-radius: 999px; overflow: hidden; display: flex; }
        .band div { height: 100%; }
        .band .r { background: #f3b5b5; } .band .a { background: #f8cf97; } .band .g { background: #a9dca6; }
        .band-wrap { position: relative; }
        .marker { position: absolute; top: -26px; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; font-size: 14px; font-weight: 600; color: var(--navy); }
        .marker::after { content: ""; width: 3px; height: 36px; margin-top: 2px; border-radius: 2px; background: var(--navy); }
        .band-scale { display: flex; justify-content: space-between; font-size: 14px; color: var(--muted); }
        .guide { display: grid; gap: 8px; }
        .guide div { display: flex; gap: 10px; align-items: baseline; font-size: 15px; color: var(--soft); }
        .guide b { flex: 0 0 74px; }
        .guide .pill { justify-content: center; }
    </style>
</head>
<body>
    <header class="topbar">
        <a class="back" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a>
        <a class="back" href="{{ url_for('index') }}">⌂ Overview</a>
        <div class="title cond">{{ title }} range</div>
        <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
    </header>

    <div class="wrap">
        {% if request.args.get('msg') %}<div class="msg auto-dismiss {% if request.args.get('ok') == '0' %}error{% endif %}">{{ request.args.get('msg') }}</div>{% endif %}
        <div class="cols">
            <div class="col">
                <section>
                    <h2 class="section-title">Now in the shed</h2>
                    <div class="card">
                        <div class="now" id="nowValue"><b class="cond">{{ current_value }}</b><span>{{ unit }}</span></div>
                        <div class="band-wrap">
                            <div class="band" id="band"></div>
                            <div class="marker" id="marker" hidden><span id="markerText"></span></div>
                        </div>
                        <div class="band-scale"><span id="scaleLo"></span><span id="scaleHi"></span></div>
                    </div>
                </section>
                <section>
                    <h2 class="section-title">How the colours work</h2>
                    <div class="card guide">
                        <div><b><span class="pill on">Green</span></b>Comfortably inside the range.</div>
                        <div><b><span class="pill wait">Amber</span></b>Still in range, but within the amber margin of a red limit.</div>
                        <div><b><span class="pill bad">Red</span></b>Outside the range. The shed tile shows an alarm.</div>
                    </div>
                </section>
            </div>
            <section>
                <h2 class="section-title">Limits</h2>
                <form class="card form" method="post" action="{{ save_url }}">
                    <div class="limits">
                        <div>
                            <label class="field" for="low_value">Red below</label>
                            <input id="low_value" type="number" name="low_value" step="{{ step }}" inputmode="{{ inputmode }}" enterkeyhint="done" value="{{ low_value }}">
                        </div>
                        <div>
                            <label class="field" for="high_value">Red above</label>
                            <input id="high_value" type="number" name="high_value" step="{{ step }}" inputmode="{{ inputmode }}" enterkeyhint="done" value="{{ high_value }}">
                        </div>
                        <div>
                            <label class="field" for="amber_margin">Amber margin</label>
                            <input id="amber_margin" type="number" name="amber_margin" step="{{ step }}" inputmode="{{ inputmode }}" enterkeyhint="done" value="{{ amber_margin }}">
                        </div>
                    </div>
                    <div class="hint">All in {{ unit }}. The amber margin is a warning zone just inside each red limit. The bar on the left updates as you type.</div>
                    <button class="primary" type="submit">{{ button_label }}</button>
                </form>
            </section>
        </div>
    </div>
<script>
(function () {
    const lowEl = document.getElementById('low_value'), highEl = document.getElementById('high_value'), marginEl = document.getElementById('amber_margin');
    const band = document.getElementById('band'), marker = document.getElementById('marker'), markerText = document.getElementById('markerText');
    const nowEl = document.getElementById('nowValue');
    const current = parseFloat({{ current_value|tojson }});
    function fmt(v) { return (Math.round(v * 10) / 10).toString(); }
    function draw() {
        const lo = parseFloat(lowEl.value), hi = parseFloat(highEl.value), m = Math.max(0, parseFloat(marginEl.value) || 0);
        if (!isFinite(lo) || !isFinite(hi) || hi <= lo) { band.innerHTML = ''; marker.hidden = true; return; }
        const pad = Math.max(m * 2, (hi - lo) * 0.3);
        let min = lo - pad, max = hi + pad;
        if (isFinite(current)) { min = Math.min(min, current - pad * 0.2); max = Math.max(max, current + pad * 0.2); }
        const pct = (v) => ((v - min) / (max - min)) * 100;
        const a1 = Math.min(lo + m, hi), a2 = Math.max(hi - m, a1);
        const parts = [['r', min, lo], ['a', lo, a1], ['g', a1, a2], ['a', a2, hi], ['r', hi, max]];
        band.innerHTML = parts.map(([c, x, y]) => '<div class="' + c + '" style="width:' + Math.max(0, pct(y) - pct(x)) + '%"></div>').join('');
        document.getElementById('scaleLo').textContent = fmt(min);
        document.getElementById('scaleHi').textContent = fmt(max);
        nowEl.classList.remove('ok', 'warn', 'alarm');
        if (isFinite(current)) {
            marker.hidden = false;
            marker.style.left = pct(current) + '%';
            markerText.textContent = 'Now';
            nowEl.classList.add(current < lo || current > hi ? 'alarm' : (current < a1 || current > a2 ? 'warn' : 'ok'));
        } else {
            marker.hidden = true;
        }
    }
    [lowEl, highEl, marginEl].forEach((el) => el.addEventListener('input', draw));
    draw();
    setTimeout(() => { document.querySelectorAll('.auto-dismiss').forEach((el) => { el.style.display = 'none'; }); }, 10000);
})();
</script>
</body>
</html>
"""


WATER_SETTINGS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Water Settings</title>
""" + ENTRY_PAGE_HEAD + """
</head>
<body>
    <header class="topbar">
        <a class="back" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a>
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
                        <div class="now"><b class="cond" id="waterCurrentValue">{{ current_value }}</b><span>L/min</span></div>
                        <div class="details">
                            <div class="detail"><span>Raw pulse L/min</span><span id="waterCurrentRawValue">{{ current_value_raw }}</span></div>
                            <div class="detail"><span>Low flow alarm below</span><span>{{ water_low_lpm }} L/min</span></div>
                            <div class="detail"><span>Pulses per litre</span><span id="waterPulsesPerLitre">{{ water_pulses_per_litre }}</span></div>
                            <div class="detail"><span>Total flow pulses</span><span id="waterTotalPulses">{{ total_flow_pulses }}</span></div>
                        </div>
                    </div>
                </section>
                <section>
                    <h2 class="section-title">Live pulses from the Pico</h2>
                    <div class="card">
                        <div class="detail" style="border-top:0"><span>Latest pulse change</span><span><span id="livePulseLastDelta">{{ live_pulse_last_delta }}</span> in <span id="livePulseLastSeconds">{{ live_pulse_last_seconds }}</span></span></div>
                        <div class="detail"><span>Smoothing window</span><span><span id="livePulseWindowDelta">{{ live_pulse_window_delta }}</span> in <span id="livePulseWindowSeconds">{{ live_pulse_window_seconds }}</span></span></div>
                        <div class="detail"><span>Total pulses seen</span><span id="waterTotalPulsesMirror">{{ total_flow_pulses }}</span></div>
                        <div class="hint" style="margin-top:8px">The flow figure above is smoothed over a short window. These are the raw pulses as they arrive.</div>
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
                                <input id="threshold_value" type="number" name="threshold_value" step="0.01" inputmode="decimal" enterkeyhint="done" value="{{ water_low_lpm }}">
                            </div>
                            <button class="primary" type="submit">Save</button>
                        </div>
                        <div class="hint">Green at or above this flow. Red below it, or when there's no reading.</div>
                    </form>
                </section>
                <section>
                    <h2 class="section-title">Meter calibration</h2>
                    <div class="card form">
                        <form method="post" action="{{ url_for('save_water_pulses_per_litre') }}">
                            <div class="inline">
                                <div>
                                    <label class="field" for="manual_pulses_per_litre">Pulses per litre</label>
                                    <input id="manual_pulses_per_litre" type="number" name="pulses_per_litre" step="0.01" inputmode="decimal" enterkeyhint="done" value="{{ water_pulses_per_litre }}">
                                </div>
                                <button class="primary" type="submit">Save</button>
                            </div>
                        </form>
                        <div class="hint">Type a known figure, or run a 5 minute test against the shed's water meter:</div>
                        <div>
                            <div class="detail"><span>Test</span><span id="calibrationStatus" class="status">{{ calibration_status }}</span></div>
                            <div class="detail"><span>Pulses counted</span><span id="calibrationPulseDelta">{{ calibration_pulse_delta }}</span></div>
                            <div class="detail"><span>Time left</span><span id="calibrationRemaining">{{ calibration_remaining }}</span></div>
                        </div>
                        <form id="startCalibrationForm" method="post" action="{{ url_for('start_water_calibration') }}" {% if not calibration_can_start %}style="display:none"{% endif %}>
                            <button class="go" type="submit">Start 5 minute test</button>
                        </form>
                        <form id="cancelCalibrationForm" method="post" action="{{ url_for('cancel_water_calibration') }}" {% if not calibration_active %}style="display:none"{% endif %}>
                            <button class="danger" type="submit">Cancel test</button>
                        </form>
                        <form id="finishCalibrationForm" method="post" action="{{ url_for('finish_water_calibration') }}">
                            <div class="inline">
                                <div>
                                    <label class="field" for="meter_litres">Litres on the meter for the test</label>
                                    <input id="meter_litres" type="number" name="meter_litres" step="0.01" inputmode="decimal" enterkeyhint="done" value="" {% if not calibration_ready %}disabled{% endif %}>
                                </div>
                                <button id="finishCalibrationButton" class="primary" type="submit" {% if not calibration_ready %}disabled{% endif %}>Save</button>
                            </div>
                        </form>
                        <div id="calibrationHint" class="hint">
                            New pulses per litre = counted pulses divided by the litres from the physical meter.
                            {% if not calibration_ready %}Complete the 5 minute calibration first to enable saving.{% endif %}
                        </div>
                    </div>
                </section>
            </div>
        </div>
    </div>
<script>
setTimeout(() => { document.querySelectorAll('.auto-dismiss').forEach((el) => { el.style.display = 'none'; }); }, 10000);
(function () {
    const currentEl = document.getElementById('waterCurrentValue');
    const currentRawEl = document.getElementById('waterCurrentRawValue');
    const pplEl = document.getElementById('waterPulsesPerLitre');
    const totalEl = document.getElementById('waterTotalPulses');
    const totalMirrorEl = document.getElementById('waterTotalPulsesMirror');
    const liveLastDeltaEl = document.getElementById('livePulseLastDelta');
    const liveLastSecondsEl = document.getElementById('livePulseLastSeconds');
    const liveWindowDeltaEl = document.getElementById('livePulseWindowDelta');
    const liveWindowSecondsEl = document.getElementById('livePulseWindowSeconds');
    const statusEl = document.getElementById('calibrationStatus');
    const pulseEl = document.getElementById('calibrationPulseDelta');
    const remainingEl = document.getElementById('calibrationRemaining');
    const startForm = document.getElementById('startCalibrationForm');
    const cancelForm = document.getElementById('cancelCalibrationForm');
    const meterInput = document.getElementById('meter_litres');
    const finishButton = document.getElementById('finishCalibrationButton');
    const hintEl = document.getElementById('calibrationHint');
    if (!currentEl || !pplEl || !totalEl || !statusEl || !pulseEl || !remainingEl) return;

    function setVisible(el, visible) {
        if (!el) return;
        el.style.display = visible ? '' : 'none';
    }

    async function refreshWaterCalibration() {
        try {
            const resp = await fetch('/api/settings/water-state', { cache: 'no-store' });
            if (!resp.ok) return;
            const data = await resp.json();
            currentEl.textContent = data.current_value || '--';
            if (currentRawEl) currentRawEl.textContent = data.current_value_raw || '--';
            pplEl.textContent = data.water_pulses_per_litre || '--';
            totalEl.textContent = data.total_flow_pulses || '--';
            if (totalMirrorEl) totalMirrorEl.textContent = data.total_flow_pulses || '--';
            if (liveLastDeltaEl) liveLastDeltaEl.textContent = data.live_pulse_last_delta || '--';
            if (liveLastSecondsEl) liveLastSecondsEl.textContent = data.live_pulse_last_seconds || '--';
            if (liveWindowDeltaEl) liveWindowDeltaEl.textContent = data.live_pulse_window_delta || '--';
            if (liveWindowSecondsEl) liveWindowSecondsEl.textContent = data.live_pulse_window_seconds || '--';
            statusEl.textContent = data.calibration_status || 'Ready';
            pulseEl.textContent = data.calibration_pulse_delta || '--';
            remainingEl.textContent = data.calibration_remaining || '--';
            setVisible(startForm, !!data.calibration_can_start);
            setVisible(cancelForm, !!data.calibration_active);
            if (meterInput) meterInput.disabled = !data.calibration_ready;
            if (finishButton) finishButton.disabled = !data.calibration_ready;
            if (hintEl) {
                let hint = 'New pulses per litre = counted pulses divided by the litres from the physical meter.';
                if (!data.calibration_ready) hint += ' Complete the 5 minute calibration first to enable saving.';
                hintEl.textContent = hint;
            }
        } catch (err) {
        }
    }

    refreshWaterCalibration();
    setInterval(refreshWaterCalibration, 1000);
})();
</script>
</body>
</html>
"""


FEED_SETTINGS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Feed Settings</title>
""" + ENTRY_PAGE_HEAD + """
    <style>
        .binbar { margin-top: 12px; height: 14px; border-radius: 999px; background: var(--track); overflow: hidden; }
        .binbar div { height: 100%; width: 0; background: var(--green); border-radius: 999px; }
        .binbar.low div { background: var(--amber); }
        .chart-box { width: 100%; height: 200px; border-radius: 12px; background: var(--card-2); overflow: hidden; }
        canvas { width: 100%; height: 100%; display: block; }
        .state-pill { display: inline-flex; padding: 3px 10px; border-radius: 999px; font-size: 14px; font-weight: 600; background: var(--card-2); color: var(--muted); }
        .state-pill.in-crop { background: #e3f4e1; color: #1e6b16; }
        .state-pill.out-crop { background: #fff4e5; color: #9a4b00; }
        .table-wrap { margin-top: 10px; max-height: 300px; }
    </style>
</head>
<body>
    <header class="topbar">
        <a class="back" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a>
        <a class="back" href="{{ url_for('index') }}">⌂ Overview</a>
        <div class="title cond">Feed bin</div>
        <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
    </header>

    <div class="wrap">
        {% if request.args.get('msg') %}<div class="msg auto-dismiss {% if request.args.get('ok') == '0' %}error{% endif %}">{{ request.args.get('msg') }}</div>{% endif %}
        <div class="cols">
            <div class="col">
                <section>
                    <h2 class="section-title">In the bin now</h2>
                    <div class="card">
                        <div class="now"><b class="cond" id="currentFeedKg">{{ current_feed_kg }}</b><span>kg</span><span id="binPct" style="margin-left:auto; font-size:20px"></span></div>
                        <div class="binbar" id="binBar"><div></div></div>
                        <div class="details">
                            <div class="detail"><span>Live calculated kg</span><span id="feedLiveKg">{{ feed_live_kg }}</span></div>
                            <div class="detail"><span>Updated</span><span id="feedKgUpdated">{{ feed_kg_updated_age }}</span></div>
                            <div class="detail"><span>Signal</span><span id="feedStabilityLabel">{{ feed_stability_label }}</span></div>
                            <div class="detail"><span>Refill recording</span><span id="feedRefillStatus">{{ feed_refill_status }}</span></div>
                        </div>
                    </div>
                </section>
                <section>
                    <h2 class="section-title">Last 24 hours</h2>
                    <div class="card"><div class="chart-box"><canvas id="feedTraceChart"></canvas></div></div>
                </section>
                <section>
                    <h2 class="section-title">Scale readings</h2>
                    <div class="card">
                        <div class="detail" style="border-top:0"><span>Smoothed raw units</span><span id="currentFeedRaw">{{ current_feed_raw }}</span></div>
                        <div class="detail"><span>60 second average raw</span><span id="feedAverageRaw">{{ feed_average_raw }}</span></div>
                        <div class="detail"><span>60 second noise</span><span><span id="feedNoiseKg">{{ feed_noise_kg }}</span> kg</span></div>
                        <div class="detail"><span>60 second raw range</span><span id="feedNoiseRaw">{{ feed_noise_raw_units }}</span></div>
                        <div class="detail"><span>Last 60 second movement</span><span><span id="feedMinuteChange">{{ feed_minute_change_kg }}</span> kg</span></div>
                        <div class="detail"><span>Tare raw</span><span>{{ feed_tare_raw }}</span></div>
                        <div class="detail"><span>kg per raw unit</span><span>{{ feed_kg_per_raw_unit }}</span></div>
                    </div>
                </section>
                <a class="link-item" href="{{ url_for('hx711_diagnostics_view') }}"><span>Feed scale diagnostics</span><span>›</span></a>
            </div>
            <div class="col">
                <section>
                    <h2 class="section-title">Bin</h2>
                    <div class="card form">
                        <form method="post" action="{{ url_for('save_feed_settings') }}">
                            <div class="inline">
                                <div>
                                    <label class="field" for="threshold_value">Low feed warning below (kg)</label>
                                    <input id="threshold_value" type="number" name="threshold_value" step="1" inputmode="numeric" enterkeyhint="done" value="{{ feed_low_kg|replace(',', '')|replace('--', '') }}">
                                </div>
                                <button class="primary" type="submit">Save</button>
                            </div>
                        </form>
                        <form method="post" action="{{ url_for('save_feed_capacity') }}">
                            <div class="inline">
                                <div>
                                    <label class="field" for="feed_capacity_kg">Bin capacity when full (kg)</label>
                                    <input id="feed_capacity_kg" type="number" name="feed_capacity_kg" step="1" inputmode="numeric" enterkeyhint="done" value="{{ feed_capacity_kg|replace(',', '')|replace('--', '') }}">
                                </div>
                                <button class="primary" type="submit">Save</button>
                            </div>
                        </form>
                    </div>
                </section>
                <section>
                    <h2 class="section-title">Scale calibration</h2>
                    <div class="card form">
                        <div class="hint"><b>1.</b> Empty the bin, then set the tare.</div>
                        <form method="post" action="{{ url_for('set_feed_tare') }}">
                            <button id="setFeedTareButton" type="submit" {% if not feed_raw_available %}disabled{% endif %}>Set tare from the empty bin</button>
                        </form>
                        <div class="hint"><b>2.</b> Put a known weight in the bin and enter it.</div>
                        <form method="post" action="{{ url_for('save_feed_known_weight') }}">
                            <div class="inline">
                                <div>
                                    <label class="field" for="known_weight_kg">Known weight (kg)</label>
                                    <input id="known_weight_kg" type="number" name="known_weight_kg" step="0.1" inputmode="decimal" enterkeyhint="done" value="">
                                </div>
                                <button id="calibrateFeedButton" class="primary" type="submit" {% if not feed_calibration_ready %}disabled{% endif %}>Calibrate</button>
                            </div>
                        </form>
                        {% if not feed_calibration_ready %}<div class="hint">Needs a live scale reading and a tare before it can calibrate.</div>{% endif %}
                        <form method="post" action="{{ url_for('undo_feed_calibration') }}">
                            <button type="submit" {% if not feed_calibration_can_undo %}disabled{% endif %}>Undo last calibration change</button>
                        </form>
                        {% if feed_calibration_rows %}
                        <div class="table-wrap">
                            <table>
                                <thead><tr><th>Time</th><th>Action</th><th>Tare raw</th><th>kg / raw</th><th>Detail</th></tr></thead>
                                <tbody>
                                    {% for row in feed_calibration_rows %}
                                    <tr>
                                        <td>{{ row.ts_label }}</td>
                                        <td>{{ row.action_label }}</td>
                                        <td>{{ row.previous_tare }} to {{ row.updated_tare }}</td>
                                        <td>{{ row.previous_scale }} to {{ row.updated_scale }}</td>
                                        <td>{{ row.detail or "--" }}</td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                        {% endif %}
                    </div>
                </section>
                <section>
                    <h2 class="section-title">Feed movements</h2>
                    <div class="card">
                        <div class="detail" style="border-top:0"><span>State</span><span><span id="feedMovementState" class="state-pill {{ feed_movement.state_class }}">{{ feed_movement.state_label }}</span></span></div>
                        <div class="detail"><span>Crop</span><span id="feedMovementCrop">{{ feed_movement.crop_code }}</span></div>
                        <div class="detail"><span>Last feed kg</span><span id="feedMovementLastFeed">{{ feed_movement.last_feed_kg }}</span></div>
                        <div class="detail"><span>Last movement</span><span id="feedMovementLastMovement">{{ feed_movement.last_movement_label }}</span></div>
                        <div class="detail"><span>Updated</span><span id="feedMovementUpdated">{{ feed_movement.updated_age }}</span></div>
                        <div class="table-wrap">
                            <table>
                                <thead><tr><th>Time</th><th>Movement</th><th>kg</th><th>Crop state</th><th>Crop</th><th>kg after</th></tr></thead>
                                <tbody id="feedMovementRows">
                                    {% for row in feed_movement.event_rows %}
                                    <tr>
                                        <td>{{ row.ts_label }}</td>
                                        <td>{{ row.movement_label }}</td>
                                        <td>{{ row.kg_label }}</td>
                                        <td><span class="state-pill {{ row.crop_state_class }}">{{ row.crop_state_label }}</span></td>
                                        <td>{{ row.crop_label }}</td>
                                        <td>{{ row.feed_kg_after_label }}</td>
                                    </tr>
                                    {% endfor %}
                                    {% if not feed_movement.event_rows %}
                                    <tr><td colspan="6">No feed movement lines recorded yet.</td></tr>
                                    {% endif %}
                                </tbody>
                            </table>
                        </div>
                        <div class="hint" style="margin-top:8px">Local controller activity. Add out-of-crop feed to a crop from the office dashboard feed page.</div>
                    </div>
                </section>
            </div>
        </div>
    </div>
    <script>
        setTimeout(() => { document.querySelectorAll('.auto-dismiss').forEach((el) => { el.style.display = 'none'; }); }, 10000);
        const FEED_LOW_KG = {{ feed_low_kg|tojson }};
        const FEED_CAPACITY_KG = {{ feed_capacity_kg|tojson }};
        function updateBinBar(kgText) {
            const kg = parseFloat(String(kgText || '').replace(/,/g, ''));
            const cap = parseFloat(String(FEED_CAPACITY_KG || '').replace(/,/g, ''));
            const low = parseFloat(String(FEED_LOW_KG || '').replace(/,/g, ''));
            const bar = document.getElementById('binBar'), pctEl = document.getElementById('binPct');
            if (!bar) return;
            if (!isFinite(kg) || !isFinite(cap) || cap <= 0) { bar.style.display = 'none'; pctEl.textContent = ''; return; }
            const pct = Math.max(0, Math.min(100, Math.round(kg * 100 / cap)));
            bar.style.display = '';
            bar.firstElementChild.style.width = pct + '%';
            bar.classList.toggle('low', isFinite(low) && kg < low);
            pctEl.textContent = pct + '% full';
        }
        updateBinBar({{ current_feed_kg|tojson }});
        function setFeedText(id, value) {
            const el = document.getElementById(id);
            if (el) el.textContent = value;
        }

        function updateMovement(data) {
            const movement = data.feed_movement || {};
            setFeedText('feedMovementCrop', movement.crop_code || '--');
            setFeedText('feedMovementLastFeed', movement.last_feed_kg || '--');
            setFeedText('feedMovementLastMovement', movement.last_movement_label || '--');
            setFeedText('feedMovementUpdated', movement.updated_age || '--');
            const rowsEl = document.getElementById('feedMovementRows');
            if (rowsEl) {
                const rows = Array.isArray(movement.event_rows) ? movement.event_rows : [];
                if (!rows.length) {
                    rowsEl.innerHTML = '<tr><td colspan="6">No feed movement lines recorded yet.</td></tr>';
                } else {
                    rowsEl.innerHTML = rows.map((row) => (
                        '<tr>' +
                        '<td>' + (row.ts_label || '--') + '</td>' +
                        '<td>' + (row.movement_label || '--') + '</td>' +
                        '<td>' + (row.kg_label || '--') + '</td>' +
                        '<td><span class="state-pill ' + (row.crop_state_class || '') + '">' + (row.crop_state_label || '--') + '</span></td>' +
                        '<td>' + (row.crop_label || '--') + '</td>' +
                        '<td>' + (row.feed_kg_after_label || '--') + '</td>' +
                        '</tr>'
                    )).join('');
                }
            }
            const stateEl = document.getElementById('feedMovementState');
            if (stateEl) {
                stateEl.textContent = movement.state_label || '--';
                stateEl.classList.remove('in-crop', 'out-crop');
                if (movement.state_class) stateEl.classList.add(movement.state_class);
            }
        }

        function drawFeedTrace(rows) {
            const canvas = document.getElementById('feedTraceChart');
            if (!canvas) return;
            const box = canvas.getBoundingClientRect();
            const ratio = window.devicePixelRatio || 1;
            canvas.width = Math.max(1, Math.round(box.width * ratio));
            canvas.height = Math.max(1, Math.round(box.height * ratio));
            const ctx = canvas.getContext('2d');
            ctx.scale(ratio, ratio);
            const width = box.width;
            const height = box.height;
            ctx.clearRect(0, 0, width, height);
            ctx.fillStyle = '#f5f8fb';
            ctx.fillRect(0, 0, width, height);
            if (!Array.isArray(rows) || rows.length < 2) {
                ctx.fillStyle = '#4a6078';
                ctx.font = '16px Barlow, Arial';
                ctx.fillText('Waiting for 60 second readings', 14, 28);
                return;
            }
            const values = rows.map((row) => Number(row.kg)).filter((value) => Number.isFinite(value));
            if (values.length < 2) return;
            let min = Math.min(...values);
            let max = Math.max(...values);
            if (max <= min) { max += 1; min -= 1; }
            const pad = 16;
            ctx.strokeStyle = '#2f9e3a';
            ctx.lineWidth = 2;
            ctx.beginPath();
            rows.forEach((row, index) => {
                const value = Number(row.kg);
                if (!Number.isFinite(value)) return;
                const x = pad + (index / Math.max(1, rows.length - 1)) * (width - pad * 2);
                const y = height - pad - ((value - min) / (max - min)) * (height - pad * 2);
                if (index === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();
        }

        async function refreshFeedState() {
            try {
                const resp = await fetch('/api/settings/feed-state', { cache: 'no-store' });
                if (!resp.ok) return;
                const data = await resp.json();
                setFeedText('currentFeedKg', data.current_feed_kg);
                updateBinBar(data.current_feed_kg);
                setFeedText('feedLiveKg', data.feed_live_kg);
                setFeedText('currentFeedRaw', data.current_feed_raw);
                setFeedText('feedAverageRaw', data.feed_average_raw);
                setFeedText('feedKgUpdated', data.feed_kg_updated_age);
                setFeedText('feedStabilityLabel', data.feed_stability_label);
                setFeedText('feedNoiseKg', data.feed_noise_kg);
                setFeedText('feedNoiseRaw', data.feed_noise_raw_units);
                setFeedText('feedMinuteChange', data.feed_minute_change_kg);
                setFeedText('feedRefillStatus', data.feed_refill_status);
                updateMovement(data);
                drawFeedTrace(data.feed_trace_rows);
                const tareButton = document.getElementById('setFeedTareButton');
                const calibrateButton = document.getElementById('calibrateFeedButton');
                if (tareButton) tareButton.disabled = !data.feed_raw_available;
                if (calibrateButton) calibrateButton.disabled = !data.feed_calibration_ready;
            } catch (err) {
            }
        }

        refreshFeedState();
        setInterval(refreshFeedState, 1000);
    </script>
</body>
</html>
"""


HX711_DIAGNOSTICS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} HX711 Diagnostics</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root { --bg:#5b5b5b; --panel:rgba(115,115,115,0.96); --panel-2:rgba(104,104,104,0.98); --line:#8a8a8a; --text:#ececec; --muted:#d2d2d2; --ok:#bff2cb; --warn:#ffe19a; --bad:#ffc4cb; }
        body { margin:0; color: var(--text); font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; background: var(--bg); }
        .wrap { max-width:1100px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color: var(--text); text-decoration:none; font-size:18px; }
        .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
        .panel { background: var(--panel); border: 1px solid var(--line); border-radius:20px; padding:18px; }
        h1 { margin:0 0 8px 0; font-size:34px; }
        h2 { margin:0 0 12px 0; font-size:24px; }
        .sub { color: var(--muted); margin-bottom:16px; font-size:18px; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:12px 0; border-bottom: 1px solid #d5dde6; font-size:18px; }
        .detail:last-child { border-bottom: 0; }
        .label { color: var(--muted); }
        .value { text-align:right; overflow-wrap:anywhere; }
        .pill { display:inline-block; border-radius:999px; padding:4px 10px; border: 1px solid var(--line); font-weight:700; }
        .ok { color: var(--ok); border-color: #2f9e3a; }
        .warn { color: var(--warn); border-color: #f08a12; }
        .bad { color: var(--bad); border-color: #d64545; }
        .actions { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:14px; }
        button { min-height:62px; border-radius:16px; border: 1px solid #d5dde6; background: #ffffff; color: var(--text); font-size:19px; font-weight:700; cursor:pointer; }
        pre { white-space:pre-wrap; word-break:break-word; margin:0; padding:12px; border-radius:14px; background: #4f4f4f; border: 1px solid #d5dde6; max-height:300px; overflow:auto; }
        @media (max-width: 900px) { .grid, .actions { grid-template-columns:1fr; } h1 { font-size:28px; } }
    </style>
</head>
<body>
    <div class="wrap">
        <nav class="page-nav" aria-label="Page navigation"><a class="page-nav-btn" href="{{ url_for('feed_settings_view') }}" data-nav-back>← Back</a><a class="page-nav-btn" href="{{ url_for('index') }}">⌂ Overview</a></nav>
        <div class="grid">
            <div class="panel">
                <h1>Shed {{ shed_no }} HX711 Diagnostics</h1>
                <div class="sub">Live feed weighing signal path from Pico, HX711, and controller calibration.</div>
                <div class="detail"><span class="label">Diagnosis</span><span id="diagnosis" class="value pill {{ diagnosis_class }}">{{ diagnosis }}</span></div>
                <div class="detail"><span class="label">Raw Feed Units</span><span id="feedRaw" class="value">{{ feed_raw_units }}</span></div>
                <div class="detail"><span class="label">Smoothed Raw</span><span id="feedRawSmoothed" class="value">{{ feed_raw_smoothed }}</span></div>
                <div class="detail"><span class="label">Published Average Raw</span><span id="feedAverageRaw" class="value">{{ feed_average_raw }}</span></div>
                <div class="detail"><span class="label">Feed KG</span><span id="feedKg" class="value">{{ feed_kg }}</span></div>
                <div class="detail"><span class="label">Live Feed KG</span><span id="feedKgLive" class="value">{{ feed_kg_live }}</span></div>
                <div class="detail"><span class="label">Updated</span><span id="lastSensor" class="value">{{ last_sensor_age }}</span></div>
                <div class="actions">
                    <form method="post" action="{{ url_for('hx711_reset_pico_view') }}"><button type="submit">Soft Reset Pico</button></form>
                    <form method="post" action="{{ url_for('hx711_clear_feed_average_view') }}"><button type="submit">Clear Feed Average</button></form>
                </div>
            </div>
            <div class="panel">
                <h2>HX711 Pins</h2>
                <div class="detail"><span class="label">DOUT/DT Pin</span><span class="value">GP14</span></div>
                <div class="detail"><span class="label">SCK/CLK Pin</span><span class="value">GP15</span></div>
                <div class="detail"><span class="label">DOUT Before Read</span><span id="doutBefore" class="value">{{ hx711_dout_before }}</span></div>
                <div class="detail"><span class="label">SCK Before Read</span><span id="sckBefore" class="value">{{ hx711_sck_before }}</span></div>
                <div class="detail"><span class="label">Ready Before Read</span><span id="readyBefore" class="value">{{ hx711_ready_before }}</span></div>
                <div class="detail"><span class="label">DOUT After Read</span><span id="doutAfter" class="value">{{ hx711_dout }}</span></div>
                <div class="detail"><span class="label">SCK After Read</span><span id="sckAfter" class="value">{{ hx711_sck }}</span></div>
                <div class="detail"><span class="label">Ready After Read</span><span id="readyAfter" class="value">{{ hx711_ready }}</span></div>
            </div>
            <div class="panel">
                <h2>Pico / Serial</h2>
                <div class="detail"><span class="label">Pico</span><span id="picoStatus" class="value">{{ pico_status }}</span></div>
                <div class="detail"><span class="label">Packet Kind</span><span id="packetKind" class="value">{{ pico_packet_kind }}</span></div>
                <div class="detail"><span class="label">Checkpoint</span><span id="checkpoint" class="value">{{ pico_checkpoint }}</span></div>
                <div class="detail"><span class="label">Boot Count</span><span id="bootCount" class="value">{{ pico_boot_count }}</span></div>
                <div class="detail"><span class="label">Reset Cause</span><span id="resetCause" class="value">{{ pico_reset_cause }}</span></div>
                <div class="detail"><span class="label">Serial Port</span><span id="serialPort" class="value">{{ serial_port }}</span></div>
            </div>
            <div class="panel">
                <h2>Calibration</h2>
                <div class="detail"><span class="label">Tare Raw</span><span id="tareRaw" class="value">{{ feed_tare_raw }}</span></div>
                <div class="detail"><span class="label">KG Per Raw Unit</span><span id="kgPerRaw" class="value">{{ feed_kg_per_raw_unit }}</span></div>
                <div class="detail"><span class="label">Capacity KG</span><span id="capacityKg" class="value">{{ feed_capacity_kg }}</span></div>
                <div class="detail"><span class="label">Raw Noise</span><span id="rawNoise" class="value">{{ feed_noise_raw_units }}</span></div>
                <div class="detail"><span class="label">KG Noise</span><span id="kgNoise" class="value">{{ feed_noise_kg }}</span></div>
            </div>
            <div class="panel">
                <h2>Alarms</h2>
                <pre id="alarmsText">{{ alarms_text }}</pre>
            </div>
            <div class="panel">
                <h2>Latest Pico Packet</h2>
                <pre id="packetText">{{ raw_packet_text }}</pre>
            </div>
        </div>
    </div>
    <script>
        function setText(id, value) {
            const el = document.getElementById(id);
            if (el) el.textContent = value || '--';
        }
        function setDiagnosis(cls, text) {
            const el = document.getElementById('diagnosis');
            if (!el) return;
            el.className = 'value pill ' + (cls || 'warn');
            el.textContent = text || '--';
        }
        async function refreshHx711() {
            try {
                const resp = await fetch('{{ url_for('hx711_diagnostics_state_api') }}', { cache: 'no-store' });
                if (!resp.ok) return;
                const d = await resp.json();
                setDiagnosis(d.diagnosis_class, d.diagnosis);
                setText('feedRaw', d.feed_raw_units);
                setText('feedRawSmoothed', d.feed_raw_smoothed);
                setText('feedAverageRaw', d.feed_average_raw);
                setText('feedKg', d.feed_kg);
                setText('feedKgLive', d.feed_kg_live);
                setText('lastSensor', d.last_sensor_age);
                setText('doutBefore', d.hx711_dout_before);
                setText('sckBefore', d.hx711_sck_before);
                setText('readyBefore', d.hx711_ready_before);
                setText('doutAfter', d.hx711_dout);
                setText('sckAfter', d.hx711_sck);
                setText('readyAfter', d.hx711_ready);
                setText('picoStatus', d.pico_status);
                setText('packetKind', d.pico_packet_kind);
                setText('checkpoint', d.pico_checkpoint);
                setText('bootCount', d.pico_boot_count);
                setText('resetCause', d.pico_reset_cause);
                setText('serialPort', d.serial_port);
                setText('tareRaw', d.feed_tare_raw);
                setText('kgPerRaw', d.feed_kg_per_raw_unit);
                setText('capacityKg', d.feed_capacity_kg);
                setText('rawNoise', d.feed_noise_raw_units);
                setText('kgNoise', d.feed_noise_kg);
                setText('alarmsText', d.alarms_text);
                setText('packetText', d.raw_packet_text);
            } catch (err) {}
        }
        refreshHx711();
        setInterval(refreshHx711, 1000);
    </script>
</body>
</html>
"""


ALLOCATION_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ shed_display_name }} Allocation</title>
""" + ENTRY_PAGE_HEAD + """
    <style>
        .pens { display: grid; gap: 12px; }
        .pen { border-radius: 14px; background: var(--card); padding: 16px 18px; border-left: 6px solid var(--green); }
        .pen-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .pen-name { font-size: 26px; font-weight: 600; color: var(--navy); }
        .pen-birds { margin-left: auto; text-align: right; }
        .pen-birds b { font-size: 28px; font-weight: 600; color: var(--navy); }
        .pen-birds span { display: block; font-size: 13px; color: var(--muted); }
        .pen-meta { margin: 2px 0 12px; font-size: 15px; color: var(--muted); }
        .pen-form { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 10px; align-items: end; }
        .list { border-radius: 14px; background: var(--card); overflow: hidden; }
        .row { display: grid; grid-template-columns: 1.1fr 1.6fr 1fr 1fr 1fr; gap: 10px; align-items: center; padding: 10px 14px; border-top: 1px solid var(--track); }
        .row:first-child { border-top: 0; }
        .row-name { font-size: 20px; font-weight: 600; color: var(--text); }
        .row-name small { display: block; font-size: 14px; font-weight: 500; color: var(--muted); }
        .row input[type="number"], .row button { min-height: 54px; }
        @media (max-width: 860px) {
            .pen-form { grid-template-columns: 1fr 1fr 1fr; }
            .pen-form .field-wrap { grid-column: 1 / -1; }
            .row { grid-template-columns: 1fr 1fr 1fr; }
            .row-name, .row input { grid-column: 1 / -1; }
        }
    </style>
</head>
<body>
    <header class="topbar">
        <a class="back" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a>
        <a class="back" href="{{ url_for('index') }}">⌂ Overview</a>
        <div class="title cond">Shed allocation</div>
        <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
    </header>

    <div class="wrap">
        {% if msg %}<div class="msg auto-dismiss {% if not ok %}error{% endif %}">{{ msg }}</div>{% endif %}

        <div class="stats">
            <div class="stat"><div class="stat-label">Birds in {{ shed_display_name }}</div><div class="stat-value cond">{{ total_birds }}</div><div class="stat-sub">Placed (live)</div></div>
            <div class="stat"><div class="stat-label">Pens</div><div class="stat-value cond">{{ active_rows|length }}</div><div class="stat-sub">{{ "Active" if active_rows else "None running" }}</div></div>
            <div class="stat"><div class="stat-label">Crop</div><div class="stat-value cond" style="font-size: 24px; padding-top: 6px">{{ crop_code }}</div><div class="stat-sub">{{ "Started " ~ crop_started if crop_started else "No active crop" }}</div></div>
        </div>

        <section>
            <h2 class="section-title">Birds in this shed</h2>
            {% if active_rows %}
            <div class="pens">
                {% for row in active_rows %}
                <div class="pen">
                    <div class="pen-head">
                        <div class="pen-name cond">For {{ row.dest_shed_label }}</div>
                        <span class="pill on">Active</span>
                        <div class="pen-birds"><b class="cond">{{ row.placed_display }} ({{ row.live_display }})</b><span>Placed (live)</span></div>
                    </div>
                    <div class="pen-meta">Started {{ row.started_at }} · Crop {{ row.crop_code }}</div>
                    <form class="pen-form" method="post" action="{{ url_for('save_entry_for_dest', dest_shed=row.dest_shed) }}">
                        <input type="hidden" name="return_to" value="allocation">
                        <div class="field-wrap">
                            <label class="field" for="placed{{ row.dest_shed }}">Birds placed</label>
                            <input id="placed{{ row.dest_shed }}" type="number" name="placed_bird_count" min="0" step="1" inputmode="numeric" enterkeyhint="done" value="{{ '' if row.placed_bird_count == 0 else row.placed_bird_count }}">
                        </div>
                        <button class="primary" type="submit">Save</button>
                        {% if row.can_move %}
                        <button formaction="{{ url_for('move_entry_for_dest', dest_shed=row.dest_shed) }}" type="submit" onclick="return confirm('Move these birds from {{ shed_display_name }} to {{ row.dest_shed_label }}?');">Move to {{ row.dest_shed_label }}</button>
                        {% else %}
                        <button type="button" disabled>Move</button>
                        {% endif %}
                        <button class="danger" formaction="{{ url_for('end_entry_for_dest', dest_shed=row.dest_shed) }}" type="submit" onclick="return confirm('End the {{ row.dest_shed_label }} pen in {{ shed_display_name }}?');">End</button>
                    </form>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <div class="card hint">No birds in {{ shed_display_name }} at the moment. Enter a count for a shed below and press Start.</div>
            {% endif %}
        </section>

        <section>
            <h2 class="section-title">Start a pen</h2>
            <div class="list">
                {% for row in idle_rows %}
                <form class="row" method="post" action="{{ url_for('start_entry_for_dest', dest_shed=row.dest_shed) }}">
                    <input type="hidden" name="return_to" value="allocation">
                    <div class="row-name cond">For {{ row.dest_shed_label }}{% if row.placed_bird_count %}<small>{{ row.placed_display }} saved, not started</small>{% endif %}</div>
                    <input type="number" name="placed_bird_count" min="0" step="1" inputmode="numeric" enterkeyhint="done" placeholder="Birds placed" aria-label="Birds placed for {{ row.dest_shed_label }}" value="{{ '' if row.placed_bird_count == 0 else row.placed_bird_count }}">
                    <button formaction="{{ url_for('save_entry_for_dest', dest_shed=row.dest_shed) }}" type="submit">Save</button>
                    <button class="go" type="submit">Start</button>
                    {% if row.placed_bird_count %}
                    <button class="danger" formaction="{{ url_for('end_entry_for_dest', dest_shed=row.dest_shed) }}" type="submit" onclick="return confirm('Clear the saved count for {{ row.dest_shed_label }}?');">Clear</button>
                    {% else %}
                    <span></span>
                    {% endif %}
                </form>
                {% endfor %}
            </div>
        </section>
    </div>
<script>
setTimeout(() => { document.querySelectorAll('.auto-dismiss').forEach((el) => { el.style.display = 'none'; }); }, 10000);
</script>
</body>
</html>
"""


MORTALITY_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Mortality</title>
""" + ENTRY_PAGE_HEAD + """
    <style>
        .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
        .form { display: grid; gap: 16px; }
        .sheds { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
        .shed-opt input { position: absolute; opacity: 0; pointer-events: none; }
        .shed-opt span { display: flex; flex-direction: column; justify-content: center; min-height: 64px; padding: 6px 14px; border-radius: 12px; border: 1px solid #c5d0dc; background: var(--card-2); cursor: pointer; }
        .shed-opt b { font-size: 20px; font-weight: 600; }
        .shed-opt small { font-size: 14px; color: var(--muted); }
        .shed-opt input:checked + span { background: var(--navy); border-color: var(--navy); color: #ffffff; }
        .shed-opt input:checked + span small { color: #d5e2f0; }
        .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .stats { grid-template-columns: 1fr 1fr; margin-bottom: 14px; }
        .log { border-radius: 14px; background: var(--card); overflow: hidden; }
        .log-row { display: grid; grid-template-columns: 1.3fr 1fr 0.6fr 1.2fr; gap: 10px; align-items: center; min-height: 50px; padding: 8px 16px; border-top: 1px solid var(--track); font-size: 16px; }
        .log-row:first-child { border-top: 0; }
        .log-row.head { min-height: 40px; font-size: 13px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; background: var(--card-2); }
        .log-row .loss { font-weight: 600; font-size: 18px; color: var(--navy); }
        .log-row .note { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        @media (max-width: 860px) {
            .cols { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <header class="topbar">
        <a class="back" href="{{ url_for('controller_settings_view') }}" data-nav-back>← Back</a>
        <a class="back" href="{{ url_for('index') }}">⌂ Overview</a>
        <div class="title cond">Mortality</div>
        <img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
    </header>

    <div class="wrap">
        {% if status_msg %}<div class="msg auto-dismiss {% if not status_ok %}error{% endif %}">{{ status_msg }}</div>{% endif %}
        <div class="cols">
            <section>
                <h2 class="section-title">Record losses</h2>
                <div class="card">
                    {% if target_rows %}
                    <form class="form" method="post" action="{{ url_for('mortality_add_view') }}">
                        <div>
                            <label class="field">Which birds</label>
                            <div class="sheds">
                                {% for row in target_rows %}
                                <label class="shed-opt">
                                    <input type="radio" name="dest_shed" value="{{ row.dest_shed }}" {% if loop.first %}checked{% endif %}>
                                    <span><b class="cond">For {{ row.dest_shed_label }}</b><small>{{ row.birds_display }} live</small></span>
                                </label>
                                {% endfor %}
                            </div>
                        </div>
                        <div class="two">
                            <div>
                                <label class="field" for="bird_loss">Birds lost</label>
                                <input id="bird_loss" type="number" name="bird_loss" min="1" step="1" inputmode="numeric" enterkeyhint="done" value="" required>
                            </div>
                            <div>
                                <label class="field" for="mortality_date">Day</label>
                                <select id="mortality_date" name="mortality_date">
                                    {% for day in mortality_days %}<option value="{{ day.value }}">{{ day.label }}</option>{% endfor %}
                                </select>
                            </div>
                        </div>
                        <div>
                            <label class="field" for="note">Note (optional)</label>
                            <input id="note" type="text" name="note" value="" placeholder="e.g. culls, heat">
                        </div>
                        <button class="primary" type="submit">Record mortality</button>
                    </form>
                    {% else %}
                    <div class="hint">No birds in this shed to record losses against. Start a pen on the Shed allocation page first.</div>
                    {% endif %}
                </div>
            </section>

            <section style="margin-top: 0">
                <h2 class="section-title">This crop · {{ active_crop_code }}</h2>
                <div class="stats">
                    <div class="stat"><div class="stat-label">Mortality</div><div class="stat-value cond">{{ mortality_total }}</div><div class="stat-sub">Birds lost this crop</div></div>
                    <div class="stat"><div class="stat-label">Live birds</div><div class="stat-value cond">{{ active_birds }}</div><div class="stat-sub">In active pens</div></div>
                </div>
                <div class="log">
                    <div class="log-row head"><span>When</span><span>Pen</span><span>Lost</span><span>Note</span></div>
                    {% for row in history_rows %}
                    <div class="log-row"><span>{{ row.ts_label }}</span><span>{{ row.dest_shed_label }}</span><span class="loss cond">{{ row.bird_loss }}</span><span class="note">{{ row.note if row.note else "--" }}</span></div>
                    {% else %}
                    <div class="log-row"><span class="hint" style="grid-column: 1 / -1">No mortality logged for this crop yet.</span></div>
                    {% endfor %}
                </div>
            </section>
        </div>
    </div>
<script>
setTimeout(() => { document.querySelectorAll('.auto-dismiss').forEach((el) => { el.style.display = 'none'; }); }, 10000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    maybe_refresh_from_dashboard()
    maybe_heartbeat_to_dashboard()
    ctx = build_home_context()
    cfg = load_config()
    msg = request.args.get("msg", "")
    ok = request.args.get("ok", "1") == "1"
    ctx["msg"] = msg
    ctx["ok"] = ok
    ctx["hide_home_alerts"] = HIDE_HOME_ALERTS_DURING_SETUP and commissioning_mode_enabled(cfg)
    return render_template_string(OVERVIEW_HTML, **ctx)


@app.route("/classic")
def classic_view():
    maybe_refresh_from_dashboard()
    maybe_heartbeat_to_dashboard()
    ctx = build_home_context()
    cfg = load_config()
    msg = request.args.get("msg", "")
    ok = request.args.get("ok", "1") == "1"
    ctx["msg"] = msg
    ctx["ok"] = ok
    ctx["hide_home_alerts"] = HIDE_HOME_ALERTS_DURING_SETUP and commissioning_mode_enabled(cfg)
    return render_template_string(HTML, **ctx)


@app.route("/history/climate")
def climate_history_view():
    cfg = load_config()
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())
    days = list(sensors.get("climate_days") or [])
    days.reverse()
    return render_template_string(
        CLIMATE_HISTORY_HTML,
        shed_no=cfg["shed_no"],
        today=datetime.now().strftime("%Y-%m-%d"),
        rows=[climate_day_display(rec) for rec in days],
    )


@app.route("/settings")
def controller_settings_view():
    maybe_refresh_from_dashboard()
    maybe_heartbeat_to_dashboard()
    ctx = build_home_context()
    cfg = load_config()
    # Always reconcile the settings page with the live repo state on disk after updates.
    update_status = load_update_status()
    live_git = get_local_git_status()
    update_status["branch"] = live_git.get("branch", update_status.get("branch", "main"))
    update_status["local_commit"] = live_git.get("local_commit", update_status.get("local_commit", "--"))
    if update_status.get("remote_commit") == update_status.get("local_commit"):
        update_status["update_available"] = False
        update_status["restart_required"] = False
        if live_git.get("ok"):
            update_status["status"] = "Already on latest version"
    checked_at = update_status.get("checked_at")
    ctx["update_status"] = update_status
    ctx["update_checked_at"] = fmt_ts(checked_at) if checked_at else "--"
    ctx["auto_update_enabled"] = cfg.get("auto_update_enabled", False)
    auto_status = load_auto_update_status()
    ctx["auto_update_last"] = ("%s · %s" % (fmt_ts(auto_status.get("last_run_ts")), auto_status.get("result") or "--")) if auto_status.get("last_run_ts") else "Not run yet"
    ctx["msg"] = request.args.get("msg", "")
    ctx["current_mode"] = current_mode_label(cfg)
    ctx["current_mode_key"] = cfg.get("deployment_mode", "commissioning")
    ctx["next_mode_key"] = "live" if commissioning_mode_enabled(cfg) else "commissioning"
    ctx["next_mode_label"] = "Live" if commissioning_mode_enabled(cfg) else "Commissioning"
    return render_template_string(SETTINGS_HTML, **ctx)


@app.route("/settings/update/check", methods=["POST"])
def check_update_view():
    status = check_for_update()
    wants_json = "application/json" in str(request.headers.get("Accept", "")).lower() or request.headers.get("X-Requested-With") == "fetch"
    if wants_json:
        payload = dict(status)
        checked_at = payload.get("checked_at")
        payload["checked_at_label"] = fmt_ts(checked_at) if checked_at else "--"
        return jsonify(payload)
    return redirect(url_for("controller_settings_view"))


def install_controller_update(trigger="manual"):
    # Pull the latest code for this controller's branch, deploy Pico firmware if it
    # changed, then restart. Returns (installed, pico_message). Used by the Install
    # update button and the nightly auto update.
    status = check_for_update()
    if not status.get("update_available"):
        return False, ""

    branch = status.get("branch") or "main"
    remote_commit = status.get("remote_commit") or "--"
    previous_commit = status.get("local_commit") or "--"
    code, stdout, stderr = run_git_command(["pull", "--ff-only", "origin", branch], timeout=60)
    save_update_status({
        "checked_at": int(time.time()),
        "branch": branch,
        "ok": code == 0,
        "status": "Update applied. Restarting controller..." if code == 0 else (stderr or stdout or "Update failed"),
        "restart_required": code == 0,
        "update_available": False if code == 0 else True,
        "local_commit": remote_commit if code == 0 else status.get("local_commit", "--"),
        "remote_commit": remote_commit,
    })

    if code != 0:
        try:
            record_controller_event("controller_update_failed", "Controller update failed (%s)" % trigger, stderr or stdout or "", push_to_office=True)
        except Exception:
            pass
        return False, ""

    pico_message = "Pico firmware already current."
    pico_status_ok = True
    pico_deployed = False
    if pico_firmware_needs_deploy():
        pico_deployed = True
        pico_status = deploy_pico_firmware()
        pico_status_ok = bool(pico_status.get("ok"))
        pico_message = str(pico_status.get("status") or "Pico firmware deploy failed")
    else:
        local_hash = pico_firmware_hash()
        save_pico_update_status({
            "checked_at": int(time.time()),
            "local_hash": local_hash,
            "ok": True,
            "status": "Pico firmware already current",
        })

    save_update_status({
        "checked_at": int(time.time()),
        "branch": branch,
        "ok": pico_status_ok,
        "status": "Update applied. Restarting controller... %s" % pico_message,
        "restart_required": True,
        "update_available": False,
        "local_commit": remote_commit,
        "remote_commit": remote_commit,
    })
    try:
        record_controller_event(
            "controller_updated",
            "Controller updated (%s)" % trigger,
            "%s -> %s. %s" % (previous_commit, remote_commit, pico_message),
            push_to_office=True,
        )
    except Exception:
        pass

    restart_delay_seconds = 2.5
    if pico_deployed:
        pause_sensor_threads()
        restart_delay_seconds = 5.0
        mutate_state(lambda s: s.update({
            "pending_pico_update_recovery": True,
            "pending_pico_update_recovery_set_ts": int(time.time()),
            "last_pico_recovery_status": "Waiting for Pico after firmware update",
        }))
        try:
            record_controller_event(
                "controller_update_restart",
                "Controller quiesced after Pico deploy",
                "Preparing full controller restart after Pico firmware update",
                push_to_office=False,
            )
        except Exception:
            pass

    restart_service_or_self(restart_delay_seconds)
    return True, pico_message


@app.route("/settings/update/auto", methods=["POST"])
def toggle_auto_update_view():
    cfg = load_config()
    cfg["auto_update_enabled"] = request.form.get("enabled") == "1"
    save_config(cfg)
    record_controller_event("auto_update_toggled", "Nightly auto update %s" % ("on" if cfg["auto_update_enabled"] else "off"), "")
    return redirect(url_for("controller_settings_view"))


@app.route("/settings/update/apply", methods=["POST"])
def apply_update_view():
    installed, pico_message = install_controller_update("manual")
    if not installed:
        return redirect(url_for("controller_settings_view"))
    return render_template_string(
        """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Updating Controller</title>
    <meta http-equiv="refresh" content="6; url={{ url_for('controller_settings_view') }}">
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
            <div class="sub">The latest code has been pulled. {{ pico_message }} This controller is restarting now and will return to settings automatically.</div>
        </div>
    </div>
</body>
</html>
        """,
        pico_message=pico_message,
    )

@app.route("/settings/mode/switch", methods=["POST"])
def switch_controller_mode_view():
    cfg = load_config()
    target_mode = str(request.form.get("target_mode", "") or "").strip().lower()
    entered_pin = str(request.form.get("mode_pin", "") or "").strip()
    expected_pin = str(cfg.get("mode_switch_pin", DEFAULT_CONFIG["mode_switch_pin"]) or DEFAULT_CONFIG["mode_switch_pin"]).strip()

    if target_mode not in ["commissioning", "live"]:
        return redirect(url_for("controller_settings_view", msg="Invalid mode selection"))
    if not entered_pin or entered_pin != expected_pin:
        return redirect(url_for("controller_settings_view", msg="Mode switch PIN incorrect"))

    cfg["deployment_mode"] = target_mode
    cfg["commissioning_mode"] = target_mode == "commissioning"
    save_config(cfg)
    return redirect(url_for("controller_settings_view", msg="Controller switched to %s mode" % current_mode_label(cfg)))


KIOSK_BROWSER_PATTERN = r"chromium.*--kiosk"


def kiosk_browser_running():
    try:
        return subprocess.run(["pgrep", "-f", KIOSK_BROWSER_PATTERN], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def close_kiosk_browser_delayed(delay_seconds=1.5):
    # Closes only the full-screen Chromium the kiosk launcher started; the controller
    # service keeps running. Delayed so this response reaches the screen first.
    def worker():
        time.sleep(delay_seconds)
        try:
            subprocess.run(["pkill", "-f", KIOSK_BROWSER_PATTERN], capture_output=True, timeout=5)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


@app.route("/settings/system/exit-kiosk", methods=["POST"])
def controller_exit_kiosk_view():
    if not kiosk_browser_running():
        return redirect(url_for("controller_settings_view", msg="The shed screen is not running in kiosk mode on this controller"))
    record_controller_event("kiosk_closed", "Closed shed screen", "Returned to the Raspberry Pi desktop")
    close_kiosk_browser_delayed()
    return render_template_string(EXIT_KIOSK_HTML)


@app.route("/settings/system/reboot", methods=["POST"])
def controller_reboot_view():
    ok, detail = run_system_action("reboot")
    if not ok:
        return redirect(url_for("controller_settings_view", msg="Reboot failed: %s" % detail))
    return render_template_string(
        """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Rebooting Controller</title>
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
            <h1>↻ Rebooting Controller</h1>
            <div class="sub">This Pi is restarting now. The shed screen should return automatically after boot.</div>
        </div>
    </div>
</body>
</html>
        """
    )


@app.route("/settings/system/shutdown", methods=["POST"])
def controller_shutdown_view():
    ok, detail = run_system_action("shutdown")
    if not ok:
        return redirect(url_for("controller_settings_view", msg="Shutdown failed: %s" % detail))
    return render_template_string(
        """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shutting Down Controller</title>
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
            <h1>⏻ Shutting Down Controller</h1>
            <div class="sub">This Pi is powering down now. Wait for the screen to go dark before disconnecting power.</div>
        </div>
    </div>
</body>
</html>
        """
    )


@app.route("/allocation")
def allocation_view():
    maybe_refresh_from_dashboard()
    cfg = load_config()
    state = load_state()
    allocation_rows = build_allocation_rows(state)
    i = 0
    while i < len(allocation_rows):
        allocation_rows[i]["started_at"] = fmt_ts(allocation_rows[i]["placement_epoch"])
        allocation_rows[i]["can_move"] = (
            entry_home_shed_no(allocation_rows[i]["dest_shed"]) != cfg["shed_no"]
            and allocation_rows[i]["crop_active"] == 1
            and int(allocation_rows[i]["bird_count"] or 0) > 0
        )
        allocation_rows[i]["placed_display"] = fmt_value(allocation_rows[i]["placed_bird_count"], "i")
        allocation_rows[i]["live_display"] = fmt_value(allocation_rows[i]["bird_count"], "i")
        i += 1

    active_rows = [r for r in allocation_rows if r["crop_active"] == 1]
    idle_rows = [r for r in allocation_rows if r["crop_active"] != 1]
    placed_total = sum(int(r["placed_bird_count"] or 0) for r in active_rows)
    live_total = sum(int(r["bird_count"] or 0) for r in active_rows)
    first_epoch = min([r["placement_epoch"] for r in active_rows if r["placement_epoch"]] or [None])
    return render_template_string(
        ALLOCATION_HTML,
        shed_no=cfg["shed_no"],
        shed_display_name=shed_display_name_from_number(cfg["shed_no"]),
        active_rows=active_rows,
        idle_rows=idle_rows,
        total_birds="%s (%s)" % (fmt_value(placed_total, "i"), fmt_value(live_total, "i")) if active_rows else "--",
        crop_code=active_rows[0]["crop_code"] if active_rows else "--",
        crop_started=fmt_ts(first_epoch) if first_epoch else "",
        msg=request.args.get("msg", ""),
        ok=request.args.get("ok", "1") == "1",
    )


@app.route("/mortality")
def mortality_view():
    maybe_refresh_from_dashboard()
    cfg = load_config()
    payload = fetch_mortality_from_dashboard(cfg["shed_no"])
    state = load_state()
    target_rows = payload.get("target_rows", [])
    if not isinstance(target_rows, list):
        target_rows = []
    history_rows = payload.get("history_rows", [])
    if not isinstance(history_rows, list):
        history_rows = []
    i = 0
    while i < len(target_rows):
        target_rows[i]["dest_shed_label"] = target_rows[i].get("dest_shed_label") or entry_shed_label(target_rows[i].get("dest_shed"))
        target_rows[i]["birds_display"] = fmt_value(target_rows[i].get("bird_count"), "i")
        i += 1
    i = 0
    while i < len(history_rows):
        history_rows[i]["dest_shed_label"] = history_rows[i].get("dest_shed_label") or entry_shed_label(history_rows[i].get("dest_shed"))
        i += 1
    status_msg = request.args.get("msg", "")
    status_ok = request.args.get("ok", "1") == "1"
    return render_template_string(
        MORTALITY_HTML,
        shed_no=cfg["shed_no"],
        shed_display_name=shed_display_name_from_number(cfg["shed_no"]),
        active_crop_id=payload.get("active_crop_id"),
        active_crop_code=fmt_crop_code(payload.get("active_crop_id"), active_crop_epoch_from_entries(state.get("entries", {}), payload.get("active_crop_id"))),
        target_rows=target_rows,
        history_rows=history_rows,
        mortality_total=fmt_value(payload.get("mortality_total"), "i"),
        active_birds=fmt_value(payload.get("active_birds"), "i"),
        mortality_days=mortality_day_options(active_crop_epoch_from_entries(state.get("entries", {}), active_crop_id_from_entries(state.get("entries", {})))),
        status_msg=status_msg,
        status_ok=status_ok,
    )


@app.route("/mortality/add", methods=["POST"])
def mortality_add_view():
    cfg = load_config()
    try:
        dest_shed = int(request.form.get("dest_shed", "").strip())
        bird_loss = int(request.form.get("bird_loss", "").strip())
        if not valid_entry_shed(dest_shed) or bird_loss <= 0:
            raise ValueError()
    except Exception:
        return redirect_back_with_status("mortality_view", False, "Invalid mortality entry")

    note = str(request.form.get("note", "") or "").strip()
    date_text = str(request.form.get("mortality_date", "") or "").strip()
    ok, msg = post_mortality_to_dashboard(cfg["shed_no"], dest_shed, bird_loss, note=note, date_text=date_text)
    if ok:
        pull_from_dashboard(load_state())
        record_controller_event("mortality_recorded", "Recorded mortality", "%s Loss %d%s" % (entry_shed_label(dest_shed), bird_loss, (" for %s" % date_text) if date_text else ""), push_to_office=True)
    return redirect_back_with_status("mortality_view", ok, msg if msg else ("Mortality recorded" if ok else "Mortality failed"))


@app.route("/health")
def controller_health_view():
    maybe_refresh_from_dashboard()
    cfg = load_config()
    state = load_state()
    entry = get_entry_for_dest(state, cfg["shed_no"])
    sensors = state.get("sensors", default_sensor_state())
    now_ts = int(time.time())
    augers = ensure_augers_state(sensors)
    active_auger_keys = enabled_auger_keys(cfg)
    auger_rows = []
    i = 0
    while i < len(AUGER_DEFS):
        auger_key, label = AUGER_DEFS[i]
        label = auger_label_for(cfg, auger_key, label)
        auger = augers.get(auger_key, {})
        waiting_override = auger_is_waiting_override(auger_key, augers, active_auger_keys, cfg=cfg)
        auger_rows.append({
            "label": label,
                "status": "Waiting" if waiting_override else auger_status_text(auger),
                "runtime": "Off / waiting" if waiting_override else auger_runtime_text(auger, now_ts=now_ts),
                "last_run": auger_last_run_text(auger),
        })
        i += 1
    if lighting_enabled(cfg):
        auger_rows.append({
            "label": lighting_label_for(cfg),
            "status": lighting_status_text(sensors),
            "runtime": lighting_runtime_text(sensors, now_ts=now_ts),
            "last_run": lighting_last_change_text(sensors),
        })
    alarm_rows = build_alarm_rows(state)
    controller_alerts = []
    i = 0
    while i < len(alarm_rows):
        controller_alerts.append("%s: %s" % (alarm_rows[i]["title"], alarm_rows[i]["detail"]))
        i += 1

    return render_template_string(
        HEALTH_HTML,
        shed_no=cfg["shed_no"],
        dashboard_url=cfg["dashboard_url"],
        controller_ip=local_ip_address(),
        serial_port=detect_serial_port(),
        last_sensor=fmt_ts(sensors.get("last_sensor_ts")),
        last_sensor_age=fmt_age_seconds(sensors.get("last_sensor_ts")),
        last_sync=fmt_ts(state.get("last_sync_ts")),
        last_sync_age=fmt_age_seconds(state.get("last_sync_ts")),
        last_backup=fmt_ts(state.get("last_backup_ts")),
        last_backup_age=fmt_age_seconds(state.get("last_backup_ts")),
        last_backup_status=state.get("last_backup_status", "") or "--",
        state_version=state.get("state_version", 0),
        state_updated_at=fmt_ts(state.get("state_updated_ts")),
        state_updated_age=fmt_age_seconds(state.get("state_updated_ts")),
        last_seen_office_sync_version=state.get("last_seen_office_sync_version", 0),
        last_seen_office_sync_at=fmt_ts(state.get("last_seen_office_sync_ts")),
        last_seen_office_sync_age=fmt_age_seconds(state.get("last_seen_office_sync_ts")),
        updated_at=fmt_ts(entry.get("updated_ts")),
        started_at=fmt_ts(entry.get("placement_epoch")),
        lighting_status=lighting_status_text(sensors),
        lighting_runtime=lighting_runtime_text(sensors, now_ts=now_ts),
        lighting_last_change=lighting_last_change_text(sensors),
        last_serial_line=sensors.get("last_serial_line", ""),
        pico_trace_summary=pico_trace_summary(sensors),
        pico_recovery_status=state.get("last_pico_recovery_status", "") or "",
        sensors=sensors,
        auger_rows=auger_rows,
        controller_alerts=controller_alerts,
        entry=entry,
    )


@app.route("/events")
def controller_events_view():
    cfg = load_config()
    return render_template_string(
        CONTROLLER_EVENTS_HTML,
        shed_no=cfg["shed_no"],
        rows=get_controller_events(250),
    )


@app.route("/commissioning")
def commissioning_view():
    maybe_refresh_from_dashboard()
    cfg = load_config()
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())
    return render_template_string(
        COMMISSIONING_HTML,
        shed_no=cfg["shed_no"],
        state_version=state.get("state_version", 0),
        state_updated_at=fmt_ts(state.get("state_updated_ts")),
        state_updated_age=fmt_age_seconds(state.get("state_updated_ts")),
        last_seen_office_sync_version=state.get("last_seen_office_sync_version", 0),
        last_seen_office_sync_at=fmt_ts(state.get("last_seen_office_sync_ts")),
        last_seen_office_sync_age=fmt_age_seconds(state.get("last_seen_office_sync_ts")),
        temp_c=fmt_value(sensors.get("temp_c"), "f1"),
        rh_pct=fmt_value(sensors.get("rh_pct"), "f0"),
        water_lpm=fmt_value(sensors.get("water_lpm"), "f2"),
        flow_total_pulses=fmt_value(sensors.get("flow_total_pulses"), "i"),
        feed_kg=fmt_value(sensors.get("feed_kg"), "f0"),
        feed_raw_units=fmt_value(feed_raw_display_units(sensors), "f2"),
        lighting_status=lighting_status_text(sensors),
        raw_json=json.dumps(sensors.get("raw", {}), indent=2, sort_keys=True),
        last_serial_line=sensors.get("last_serial_line", ""),
        pico_trace_summary=pico_trace_summary(sensors),
        pico_recovery_status=state.get("last_pico_recovery_status", "") or "",
    )


@app.route("/config")
def controller_config_view():
    cfg = load_config()
    state = load_state()
    return render_template_string(
        CONFIG_HTML,
        shed_no=cfg["shed_no"],
        cfg=cfg,
        host_ips=host_ipv4_display(),
        last_backup=fmt_ts(state.get("last_backup_ts")),
        last_backup_status=state.get("last_backup_status", "") or "--",
    )


@app.route("/config/save", methods=["POST"])
def save_controller_config_view():
    cfg = load_config()
    try:
        cfg["shed_no"] = int(request.form.get("shed_no", cfg["shed_no"]))
    except Exception:
        pass
    cfg["dashboard_url"] = str(request.form.get("dashboard_url", cfg["dashboard_url"]) or cfg["dashboard_url"]).strip().rstrip("/")
    cfg["serial_port"] = str(request.form.get("serial_port", cfg["serial_port"]) or cfg["serial_port"]).strip()
    try:
        cfg["serial_baudrate"] = int(request.form.get("serial_baudrate", cfg["serial_baudrate"]))
    except Exception:
        pass
    try:
        cfg["touch_refresh_seconds"] = max(0.25, float(request.form.get("touch_refresh_seconds", cfg["touch_refresh_seconds"])))
    except Exception:
        pass
    cfg["serial_enabled"] = request.form.get("serial_enabled") == "on"
    cfg["sync_on_sensor_update"] = request.form.get("sync_on_sensor_update") == "on"
    cfg["cross_auger_enabled"] = request.form.get("cross_auger_enabled") == "on"
    cfg["auger_left_enabled"] = request.form.get("auger_left_enabled") == "on"
    cfg["auger_right_enabled"] = request.form.get("auger_right_enabled") == "on"
    cfg["lighting_enabled"] = request.form.get("lighting_enabled") == "on"
    cfg["cross_auger_label"] = str(request.form.get("cross_auger_label", cfg["cross_auger_label"]) or "").strip() or "Cross Auger"
    cfg["auger_left_label"] = str(request.form.get("auger_left_label", cfg["auger_left_label"]) or "").strip() or "Auger Left"
    cfg["auger_right_label"] = str(request.form.get("auger_right_label", cfg["auger_right_label"]) or "").strip() or "Auger Right"
    cfg["lighting_label"] = str(request.form.get("lighting_label", cfg["lighting_label"]) or "").strip() or "Lighting"
    if request.form.get("layout_front_end") in SHED_LAYOUT_ENDS:
        cfg["layout_front_end"] = request.form.get("layout_front_end")
    if request.form.get("layout_bin_corner") in SHED_LAYOUT_CORNERS:
        cfg["layout_bin_corner"] = request.form.get("layout_bin_corner")
    if request.form.get("layout_door_end") in SHED_LAYOUT_ENDS:
        cfg["layout_door_end"] = request.form.get("layout_door_end")
    save_config(cfg)
    return redirect(url_for("controller_config_view"))


@app.route("/alarms")
def controller_alarms_view():
    cfg = load_config()
    state = mutate_state(lambda s: reconcile_alarm_history(s))
    return render_template_string(
        ALARMS_HTML,
        shed_no=cfg["shed_no"],
        alarm_rows=current_alarm_snapshot(state),
        alarm_history_rows=get_alarm_history(200),
    )


@app.route("/alarms/clear", methods=["POST"])
def clear_controller_alarms_view():
    def mutator(state):
        sensors = state.get("sensors", default_sensor_state())
        sensors["alarms"] = []
        sensors["controller_alarms"] = []
        state["sensors"] = sensors
        if "failed" in str(state.get("last_push_status", "")).lower():
            state["last_push_status"] = "Waiting"
        if str(state.get("last_backup_status", "")).startswith("Backup failed"):
            state["last_backup_status"] = "Waiting"
    mutate_state(mutator)
    return redirect(url_for("controller_alarms_view"))


@app.route("/backup/create")
def create_backup_view():
    path = create_backup_zip("manual")
    mutate_state(lambda state: state.update({
        "last_backup_ts": int(time.time()),
        "last_backup_status": "Backup OK: %s" % os.path.basename(path),
    }))
    return redirect(url_for("controller_config_view"))


@app.route("/backup/latest")
def download_latest_backup_view():
    auth_error = require_office_token()
    if auth_error:
        return auth_error
    backups = list_backup_files()
    if not backups:
        path = create_backup_zip("manual")
    else:
        path = backups[0]
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.route("/export/config")
def export_config_view():
    path = os.path.join(DATA_DIR, "controller_config.json")
    return send_file(path, as_attachment=True, download_name="controller_config.json")


@app.route("/export/state")
def export_state_view():
    path = os.path.join(DATA_DIR, "controller_state.json")
    return send_file(path, as_attachment=True, download_name="controller_state.json")


@app.route("/settings/temp")
def temp_settings_view():
    cfg = load_config()
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())
    return render_template_string(
        RANGE_SETTINGS_HTML,
        shed_no=cfg["shed_no"],
        title="Temperature",
        subtitle="Adjust the temperature thresholds for the home tile warning glow.",
        current_value=fmt_value(sensors.get("temp_c"), "f1"),
        unit="C",
        save_url=url_for("save_temp_settings"),
        low_label="Temp Red Low C",
        high_label="Temp Red High C",
        amber_label="Temp Amber Margin C",
        low_value=cfg.get("temp_low_c", 18.0),
        high_value=cfg.get("temp_high_c", 24.0),
        amber_margin=cfg.get("temp_amber_margin_c", 1.0),
        step="0.1",
        inputmode="decimal",
        button_label="Save Temperature Limits",
        hint="The red-below and red-above values are the hard limits. The amber margin creates an amber warning zone just inside those limits.",
    )


@app.route("/settings/temp/save", methods=["POST"])
def save_temp_settings():
    cfg = load_config()
    try:
        temp_low_c = float(request.form.get("low_value", "").strip())
        temp_high_c = float(request.form.get("high_value", "").strip())
        temp_amber_margin_c = float(request.form.get("amber_margin", "").strip())
    except Exception:
        return redirect(url_for("temp_settings_view", ok=0, msg='Not saved, check the numbers'))

    if temp_low_c >= temp_high_c:
        return redirect(url_for("temp_settings_view", ok=0, msg='Not saved, check the numbers'))
    if temp_amber_margin_c < 0:
        return redirect(url_for("temp_settings_view", ok=0, msg='Not saved, check the numbers'))

    cfg["temp_low_c"] = temp_low_c
    cfg["temp_high_c"] = temp_high_c
    cfg["temp_amber_margin_c"] = temp_amber_margin_c
    cfg["climate_limits_updated_ts"] = int(time.time())
    save_config(cfg)
    sync_climate_limits_to_office()
    return redirect(url_for("temp_settings_view", ok=1, msg='Temperature limits saved'))


@app.route("/settings/rh")
def rh_settings_view():
    cfg = load_config()
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())
    return render_template_string(
        RANGE_SETTINGS_HTML,
        shed_no=cfg["shed_no"],
        title="Humidity",
        subtitle="Adjust the humidity thresholds for the home tile warning glow.",
        current_value=fmt_value(sensors.get("rh_pct"), "f0"),
        unit="%RH",
        save_url=url_for("save_rh_settings"),
        low_label="RH Red Low %",
        high_label="RH Red High %",
        amber_label="RH Amber Margin %",
        low_value=cfg.get("rh_low_pct", 40.0),
        high_value=cfg.get("rh_high_pct", 80.0),
        amber_margin=cfg.get("rh_amber_margin_pct", 5.0),
        step="1",
        inputmode="numeric",
        button_label="Save Humidity Limits",
        hint="The red-below and red-above values are the hard limits. The amber margin creates an amber warning zone just inside those limits.",
    )


@app.route("/settings/rh/save", methods=["POST"])
def save_rh_settings():
    cfg = load_config()
    try:
        rh_low_pct = float(request.form.get("low_value", "").strip())
        rh_high_pct = float(request.form.get("high_value", "").strip())
        rh_amber_margin_pct = float(request.form.get("amber_margin", "").strip())
    except Exception:
        return redirect(url_for("rh_settings_view", ok=0, msg='Not saved, check the numbers'))

    if rh_low_pct >= rh_high_pct:
        return redirect(url_for("rh_settings_view", ok=0, msg='Not saved, check the numbers'))
    if rh_amber_margin_pct < 0:
        return redirect(url_for("rh_settings_view", ok=0, msg='Not saved, check the numbers'))

    cfg["rh_low_pct"] = rh_low_pct
    cfg["rh_high_pct"] = rh_high_pct
    cfg["rh_amber_margin_pct"] = rh_amber_margin_pct
    cfg["climate_limits_updated_ts"] = int(time.time())
    save_config(cfg)
    sync_climate_limits_to_office()
    return redirect(url_for("rh_settings_view", ok=1, msg='Humidity limits saved'))


def build_water_settings_context(cfg, state):
    sensors = state.get("sensors", default_sensor_state())
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
            sensors = state.get("sensors", default_sensor_state())
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
            calibration_can_start = True
            calibration_remaining = "0m 00s"
            calibration_pulse_delta = fmt_value(calib.get("pulse_delta"), "i")

    live_pulse_last_delta = "--"
    live_pulse_last_seconds = "--"
    live_pulse_window_delta = "--"
    live_pulse_window_seconds = "--"
    try:
        last_delta = int(sensors.get("water_last_pulse_delta"))
        last_elapsed_s = int(sensors.get("water_last_elapsed_s"))
        live_pulse_last_delta = fmt_value(max(0, last_delta), "i")
        live_pulse_last_seconds = "%ss" % max(1, last_elapsed_s)
    except Exception:
        pass
    try:
        window_delta = 0
        window_seconds = 0
        i = 0
        samples = sensors.get("flow_rate_samples", [])
        while i < len(samples):
            sample = samples[i]
            i += 1
            window_delta += max(0, int(sample.get("pulse_delta", 0)))
            window_seconds += max(1, int(sample.get("elapsed_s", 1)))
        live_pulse_window_delta = fmt_value(window_delta, "i")
        live_pulse_window_seconds = "%ss" % max(1, window_seconds)
    except Exception:
        pass

    return {
        "shed_no": cfg["shed_no"],
        "current_value": fmt_value(sensors.get("water_lpm"), "f2"),
        "current_value_raw": fmt_value(sensors.get("water_lpm_raw"), "f2"),
        "water_low_lpm": fmt_value(cfg.get("water_low_lpm", 0.1), "f2"),
        "water_pulses_per_litre": fmt_value(cfg.get("water_pulses_per_litre", 450.0), "f1"),
        "total_flow_pulses": fmt_value(sensors.get("flow_total_pulses"), "i"),
        "live_pulse_last_delta": live_pulse_last_delta,
        "live_pulse_last_seconds": live_pulse_last_seconds,
        "live_pulse_window_delta": live_pulse_window_delta,
        "live_pulse_window_seconds": live_pulse_window_seconds,
        "calibration_status": calibration_status,
        "calibration_remaining": calibration_remaining,
        "calibration_pulse_delta": calibration_pulse_delta,
        "calibration_can_start": calibration_can_start,
        "calibration_active": calibration_active,
        "calibration_ready": calibration_ready,
    }


@app.route("/settings/water")
def water_settings_view():
    cfg = load_config()
    state = load_state()
    return render_template_string(WATER_SETTINGS_HTML, **build_water_settings_context(cfg, state))


@app.route("/api/settings/water-state")
def water_settings_state_api():
    cfg = load_config()
    state = load_state()
    return jsonify(build_water_settings_context(cfg, state))


@app.route("/settings/water/save", methods=["POST"])
def save_water_settings():
    cfg = load_config()
    try:
        threshold_value = float(request.form.get("threshold_value", "").strip())
    except Exception:
        return redirect(url_for("water_settings_view", ok=0, msg='Not saved, check the number'))
    cfg["water_low_lpm"] = threshold_value
    save_config(cfg)
    return redirect(url_for("water_settings_view", ok=1, msg='Low flow alarm saved'))


@app.route("/settings/water/pulses-per-litre", methods=["POST"])
def save_water_pulses_per_litre():
    cfg = load_config()
    try:
        pulses_per_litre = float(request.form.get("pulses_per_litre", "").strip())
        if pulses_per_litre <= 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("water_settings_view", ok=0, msg='Not saved, check the number'))
    cfg["water_pulses_per_litre"] = pulses_per_litre
    save_config(cfg)
    return redirect(url_for("water_settings_view", ok=1, msg='Pulses per litre saved'))


@app.route("/settings/water/calibration/start", methods=["POST"])
def start_water_calibration():
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())
    try:
        total_pulses = int(sensors.get("flow_total_pulses"))
    except Exception:
        return redirect(url_for("water_settings_view", ok=0, msg='The test could not start'))

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
    return redirect(url_for("water_settings_view", ok=1, msg='5 minute test started'))


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
    return redirect(url_for("water_settings_view", ok=1, msg='Test cancelled'))


@app.route("/settings/water/calibration/finish", methods=["POST"])
def finish_water_calibration():
    try:
        meter_litres = float(request.form.get("meter_litres", "").strip())
        if meter_litres <= 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("water_settings_view", ok=0, msg='Not saved, check the meter litres'))

    state = load_state()
    calib = state.get("water_calibration", {})
    try:
        pulse_delta = int(calib.get("pulse_delta"))
    except Exception:
        pulse_delta = None
    if pulse_delta is None or pulse_delta <= 0:
        return redirect(url_for("water_settings_view", ok=0, msg='Run the 5 minute test first'))

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
    return redirect(url_for("water_settings_view", ok=1, msg='New pulses per litre saved'))


def build_feed_settings_context(cfg, state):
    sensors = state.get("sensors", default_sensor_state())
    feed_movement = feed_movement_display_context(sensors, state.get("entries", {}))
    feed_raw = sensors.get("feed_raw_units")
    feed_raw_display = feed_raw_display_units(sensors)
    feed_raw_available = feed_raw not in [None, ""]
    feed_calibration_ready = feed_raw_available and cfg.get("feed_tare_raw") not in [None, ""]
    try:
        settling_remaining_s = max(0, int(sensors.get("feed_refill_settling_until_ts")) - int(time.time()))
    except Exception:
        settling_remaining_s = 0
    trace_rows = []
    samples = sensors.get("feed_published_samples", [])
    if isinstance(samples, list):
        i = 0
        while i < len(samples):
            sample = samples[i]
            i += 1
            try:
                sample_ts = int(sample.get("ts"))
                sample_kg = float(sample.get("kg"))
            except Exception:
                continue
            trace_rows.append({
                "ts": sample_ts,
                "label": datetime.fromtimestamp(sample_ts).strftime("%H:%M"),
                "kg": round(sample_kg, 1),
            })
    return {
        "shed_no": cfg["shed_no"],
        "current_feed_kg": fmt_value(sensors.get("feed_kg"), "f0"),
        "feed_live_kg": fmt_value(sensors.get("feed_kg_live"), "f1"),
        "current_feed_raw": fmt_value(feed_raw_display, "f1"),
        "feed_average_raw": fmt_value(sensors.get("feed_average_raw_units"), "f1"),
        "feed_kg_updated_age": fmt_age_seconds(sensors.get("feed_kg_updated_ts")),
        "feed_minute_change_kg": fmt_value(sensors.get("feed_minute_change_kg"), "f1"),
        "feed_noise_raw_units": fmt_value(sensors.get("feed_noise_raw_units"), "f1"),
        "feed_noise_kg": fmt_value(sensors.get("feed_noise_kg"), "f1"),
        "feed_stability_label": str(sensors.get("feed_stability_label") or "Waiting for samples"),
        "feed_refill_status": ("Settling for %s" % fmt_duration_short(settling_remaining_s)) if settling_remaining_s > 0 else "Ready",
        "feed_movement": feed_movement,
        "feed_trace_rows": trace_rows,
        "feed_low_kg": fmt_value(cfg.get("feed_low_kg", 2000.0), "f0"),
        "feed_capacity_kg": fmt_value(cfg.get("feed_capacity_kg", 16000.0), "f0"),
        "feed_tare_raw": fmt_value(cfg.get("feed_tare_raw"), "f1"),
        "feed_kg_per_raw_unit": fmt_value(cfg.get("feed_kg_per_raw_unit"), "f4"),
        "feed_raw_available": feed_raw_available,
        "feed_calibration_ready": feed_calibration_ready,
        "feed_calibration_rows": feed_calibration_history_rows(),
        "feed_calibration_can_undo": feed_calibration_undo_row() is not None,
    }


def fmt_logic_level(value):
    if value in [None, ""]:
        return "--"
    try:
        value_i = int(value)
    except Exception:
        return str(value)
    if value_i == 0:
        return "LOW / 0"
    if value_i == 1:
        return "HIGH / 1"
    return str(value)


def fmt_ready(value):
    if value is True:
        return "Ready"
    if value is False:
        return "Not Ready"
    return "--"


def hx711_diagnosis(cfg, sensors):
    raw = sensors.get("raw", {}) if isinstance(sensors.get("raw", {}), dict) else {}
    alarms = sensors.get("alarms", [])
    alarm_text = " ".join(str(item) for item in alarms) if isinstance(alarms, list) else ""
    feed_raw = sensors.get("feed_raw_units")
    if feed_raw in [None, ""]:
        feed_raw = raw.get("feed_raw_units")

    dout = sensors.get("hx711_dout")
    if dout in [None, ""]:
        dout = raw.get("hx711_dout")
    dout_before = sensors.get("hx711_dout_before")
    if dout_before in [None, ""]:
        dout_before = raw.get("hx711_dout_before")

    if "HX711 not ready" in alarm_text:
        return "bad", "HX711 not ready: DOUT is likely stuck high or not connected"

    try:
        feed_raw_f = float(feed_raw)
    except Exception:
        feed_raw_f = None

    try:
        dout_i = int(dout)
    except Exception:
        dout_i = None
    try:
        dout_before_i = int(dout_before)
    except Exception:
        dout_before_i = None

    if feed_raw_f == 0.0 and (dout_i == 0 or dout_before_i == 0):
        return "bad", "Raw is zero and DOUT is low: suspect HX711 stuck low, short to ground, or failed module"
    if feed_raw_f == 0.0:
        return "bad", "Raw is exactly zero: suspect HX711 data path or module fault"
    if feed_raw_f is None:
        return "bad", "No feed raw value arriving from Pico"
    if cfg.get("feed_tare_raw") in [None, ""] or cfg.get("feed_kg_per_raw_unit") in [None, ""]:
        return "warn", "Raw is present but feed calibration is incomplete"
    return "ok", "HX711 raw feed data is arriving"


def build_hx711_diagnostics_context(cfg, state):
    sensors = state.get("sensors", default_sensor_state())
    raw = sensors.get("raw", {}) if isinstance(sensors.get("raw", {}), dict) else {}
    diagnosis_class, diagnosis = hx711_diagnosis(cfg, sensors)
    alarms = sensors.get("alarms", [])
    controller_alarms = sensors.get("controller_alarms", [])
    all_alarms = []
    if isinstance(alarms, list):
        all_alarms.extend(str(item) for item in alarms)
    if isinstance(controller_alarms, list):
        all_alarms.extend(str(item.get("message") if isinstance(item, dict) else item) for item in controller_alarms)
    try:
        raw_packet_text = json.dumps(raw, indent=2, sort_keys=True)
    except Exception:
        raw_packet_text = str(raw)

    def raw_or_sensor(key):
        value = sensors.get(key)
        if value in [None, ""]:
            value = raw.get(key)
        return value

    return {
        "shed_no": cfg["shed_no"],
        "diagnosis": diagnosis,
        "diagnosis_class": diagnosis_class,
        "feed_raw_units": fmt_value(raw_or_sensor("feed_raw_units"), "f1"),
        "feed_raw_smoothed": fmt_value(feed_raw_display_units(sensors), "f1"),
        "feed_average_raw": fmt_value(sensors.get("feed_average_raw_units"), "f1"),
        "feed_kg": fmt_value(sensors.get("feed_kg"), "f1"),
        "feed_kg_live": fmt_value(sensors.get("feed_kg_live"), "f1"),
        "last_sensor_age": fmt_age_seconds(sensors.get("last_sensor_ts")),
        "hx711_dout": fmt_logic_level(raw_or_sensor("hx711_dout")),
        "hx711_sck": fmt_logic_level(raw_or_sensor("hx711_sck")),
        "hx711_ready": fmt_ready(raw_or_sensor("hx711_ready")),
        "hx711_dout_before": fmt_logic_level(raw_or_sensor("hx711_dout_before")),
        "hx711_sck_before": fmt_logic_level(raw_or_sensor("hx711_sck_before")),
        "hx711_ready_before": fmt_ready(raw_or_sensor("hx711_ready_before")),
        "pico_status": sensor_status_text(sensors),
        "pico_packet_kind": str(sensors.get("pico_packet_kind") or "--"),
        "pico_checkpoint": str(sensors.get("pico_checkpoint") or "--"),
        "pico_boot_count": fmt_value(sensors.get("pico_boot_count"), "i"),
        "pico_reset_cause": str(sensors.get("pico_reset_cause") or "--"),
        "serial_port": str(sensors.get("serial_reader_port") or detect_serial_port() or "--"),
        "feed_tare_raw": fmt_value(cfg.get("feed_tare_raw"), "f1"),
        "feed_kg_per_raw_unit": fmt_value(cfg.get("feed_kg_per_raw_unit"), "f4"),
        "feed_capacity_kg": fmt_value(cfg.get("feed_capacity_kg"), "f0"),
        "feed_noise_raw_units": fmt_value(sensors.get("feed_noise_raw_units"), "f1"),
        "feed_noise_kg": fmt_value(sensors.get("feed_noise_kg"), "f1"),
        "alarms_text": "\n".join(all_alarms) if all_alarms else "No active Pico/controller alarms.",
        "raw_packet_text": raw_packet_text if raw_packet_text not in ["{}", ""] else "No full Pico packet received yet.",
    }


@app.route("/settings/hx711")
def hx711_diagnostics_view():
    cfg = load_config()
    state = load_state()
    return render_template_string(HX711_DIAGNOSTICS_HTML, **build_hx711_diagnostics_context(cfg, state))


@app.route("/api/settings/hx711-state")
def hx711_diagnostics_state_api():
    cfg = load_config()
    state = load_state()
    return jsonify(build_hx711_diagnostics_context(cfg, state))


@app.route("/settings/hx711/reset-pico", methods=["POST"])
def hx711_reset_pico_view():
    status = soft_reset_pico()
    return redirect(url_for("hx711_diagnostics_view", msg=str(status.get("status") or "")))


@app.route("/settings/hx711/clear-average", methods=["POST"])
def hx711_clear_feed_average_view():
    mutate_state(lambda s: reset_feed_average_state(s.get("sensors", default_sensor_state())))
    return redirect(url_for("hx711_diagnostics_view"))


@app.route("/settings/feed")
def feed_settings_view():
    cfg = load_config()
    state = load_state()
    return render_template_string(FEED_SETTINGS_HTML, **build_feed_settings_context(cfg, state))


@app.route("/api/settings/feed-state")
def feed_settings_state_api():
    cfg = load_config()
    state = load_state()
    return jsonify(build_feed_settings_context(cfg, state))


@app.route("/settings/feed/save", methods=["POST"])
def save_feed_settings():
    cfg = load_config()
    try:
        threshold_value = float(request.form.get("threshold_value", "").strip())
    except Exception:
        return redirect(url_for("feed_settings_view", ok=0, msg='Not saved, check the number'))
    cfg["feed_low_kg"] = threshold_value
    save_config(cfg)
    return redirect(url_for("feed_settings_view", ok=1, msg='Low feed warning saved'))


@app.route("/settings/feed/capacity/save", methods=["POST"])
def save_feed_capacity():
    cfg = load_config()
    try:
        capacity = float(request.form.get("feed_capacity_kg", "").strip())
        if capacity <= 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("feed_settings_view", ok=0, msg='Not saved, check the number'))
    cfg["feed_capacity_kg"] = capacity
    save_config(cfg)
    return redirect(url_for("feed_settings_view", ok=1, msg='Bin capacity saved'))


@app.route("/settings/feed/tare", methods=["POST"])
def set_feed_tare():
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())
    try:
        feed_raw = float(sensors.get("feed_raw_units"))
    except Exception:
        return redirect(url_for("feed_settings_view", ok=0, msg='No live scale reading to tare from'))
    cfg = load_config()
    previous = feed_calibration_snapshot(cfg)
    cfg["feed_tare_raw"] = feed_raw
    save_config(cfg)
    append_feed_calibration_history(
        "tare_saved",
        previous,
        feed_calibration_snapshot(cfg),
        detail="Tare set from raw %.1f" % feed_raw,
    )
    mutate_state(lambda s: reset_feed_average_state(s.get("sensors", default_sensor_state())))
    return redirect(url_for("feed_settings_view", ok=1, msg='Tare set'))


@app.route("/settings/feed/known-weight/save", methods=["POST"])
def save_feed_known_weight():
    cfg = load_config()
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())

    try:
        known_weight_kg = float(request.form.get("known_weight_kg", "").strip())
        if known_weight_kg <= 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("feed_settings_view", ok=0, msg='Not calibrated, check the weight and tare'))

    try:
        feed_raw = float(sensors.get("feed_raw_units"))
        tare_raw = float(cfg.get("feed_tare_raw"))
    except Exception:
        return redirect(url_for("feed_settings_view", ok=0, msg='Not calibrated, check the weight and tare'))

    raw_delta = feed_raw - tare_raw
    if raw_delta <= 0:
        return redirect(url_for("feed_settings_view", ok=0, msg='Not calibrated, check the weight and tare'))

    previous = feed_calibration_snapshot(cfg)
    cfg["feed_kg_per_raw_unit"] = known_weight_kg / raw_delta
    save_config(cfg)
    append_feed_calibration_history(
        "known_weight_saved",
        previous,
        feed_calibration_snapshot(cfg),
        detail="%.1f KG from raw delta %.1f" % (known_weight_kg, raw_delta),
    )

    def reset_and_publish(s):
        sensors = s.get("sensors", default_sensor_state())
        reset_feed_average_state(sensors)
        update_feed_from_raw(sensors)

    mutate_state(reset_and_publish)
    return redirect(url_for("feed_settings_view", ok=1, msg='Scale calibrated'))


@app.route("/settings/feed/calibration/undo", methods=["POST"])
def undo_feed_calibration():
    rows = load_feed_calibration_history()
    if not rows:
        return redirect(url_for("feed_settings_view", ok=0, msg='Nothing to undo'))
    target = rows[-1]
    if not isinstance(target, dict) or not bool(target.get("undoable", False)) or target.get("undone_ts") not in [None, ""]:
        return redirect(url_for("feed_settings_view", ok=0, msg='Nothing to undo'))
    previous = target.get("previous", {})
    if not isinstance(previous, dict):
        return redirect(url_for("feed_settings_view", ok=0, msg='Nothing to undo'))

    cfg = load_config()
    current = feed_calibration_snapshot(cfg)
    cfg["feed_tare_raw"] = previous.get("feed_tare_raw")
    cfg["feed_kg_per_raw_unit"] = previous.get("feed_kg_per_raw_unit")
    save_config(cfg)
    target["undone_ts"] = int(time.time())
    rows[-1] = target
    rows.append({
        "ts": int(time.time()),
        "action": "undo",
        "previous": current,
        "updated": feed_calibration_snapshot(cfg),
        "detail": "Reverted %s" % str(target.get("action") or "calibration").replace("_", " "),
        "undoable": False,
        "undone_ts": None,
    })
    save_feed_calibration_history(rows)

    def reset_and_publish(s):
        sensors = s.get("sensors", default_sensor_state())
        reset_feed_average_state(sensors)
        update_feed_from_raw(sensors)

    mutate_state(reset_and_publish)
    return redirect(url_for("feed_settings_view", ok=1, msg='Last calibration change undone'))


def render_metric_history(metric_key, metric_title, y_axis_title, color, fmt, series_defs=None):
    # series_defs: [(metric_key, label, axis_title, color, fmt), ...]; one entry draws a
    # single-metric page, several draw them together on their own axes.
    series_defs = series_defs or [(metric_key, metric_title, y_axis_title, color, fmt)]
    shed_no = load_config()["shed_no"]
    payload = fetch_current_crop_hourly_history(shed_no, hourly=True)
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    crop_id = payload.get("crop_id") if isinstance(payload, dict) else None
    crop_code = payload.get("crop_code") if isinstance(payload, dict) else fmt_crop_code(crop_id)

    labels = [row.get("label") for row in rows]
    epochs = [row.get("epoch") for row in rows]
    series = []
    for key, label, axis_title, series_color, series_fmt in series_defs:
        series.append({
            "label": label,
            "axis_title": axis_title,
            "color": series_color,
            "values": [row.get(key) for row in rows],
        })
    view_rows = []
    for row in rows:
        view_rows.append({
            "label": row.get("label"),
            "values": [fmt_value(row.get(d[0]), d[4]) for d in series_defs],
        })

    return render_template_string(
        HISTORY_HTML,
        shed_no=shed_no,
        crop_id=crop_id,
        crop_code=crop_code,
        metric_title=metric_title,
        series=series,
        rows=view_rows,
        table_rows=list(reversed(view_rows)),
        labels=labels,
        epochs=epochs,
        log_tab=metric_key,
    )


def redirect_back_with_status(default_endpoint, ok, msg):
    target = str(request.form.get("return_to", "") or request.args.get("return_to", "") or "").strip()
    allowed = {
        "index": "index",
        "allocation": "allocation_view",
        "mortality": "mortality_view",
        "settings": "controller_settings_view",
    }
    endpoint = allowed.get(target, default_endpoint)
    return redirect(url_for(endpoint, ok=1 if ok else 0, msg=msg))


@app.route("/history/water")
def water_history_view():
    return render_metric_history("water", "Water History", "Water L", "#5fd0d8", "f1")


@app.route("/history/feed")
def feed_history_view():
    return render_metric_history("feed", "Feed History", "Feed KG", "#d9b86a", "f1")



@app.route("/history/feed/augers")
def auger_runs_view():
    cfg = load_config()
    return render_template_string(
        AUGER_RUNS_HTML,
        shed_no=cfg["shed_no"],
        rows=get_auger_runs(500),
    )


@app.route("/api/history/feed/augers")
def auger_runs_api_view():
    auth_error = require_office_token()
    if auth_error:
        return auth_error
    try:
        limit = int(request.args.get("limit", "200"))
    except Exception:
        limit = 200
    if limit <= 0:
        limit = 200
    if limit > 1000:
        limit = 1000
    return jsonify({
        "ok": True,
        "rows": get_auger_runs(limit),
        "generated_at": int(time.time()),
    })


def save_entry_for_dest_impl(dest_shed, placed_bird_count):
    if not valid_entry_shed(dest_shed):
        return False, "Invalid shed"

    def mutator(state):
        entry = get_entry_for_dest(state, dest_shed)
        if placed_bird_count == 0:
            clear_entry_for_dest(state, dest_shed)
        else:
            try:
                old_placed = int(entry.get("placed_bird_count") or entry.get("bird_count") or 0)
            except Exception:
                old_placed = 0
            try:
                old_live = int(entry.get("bird_count") or 0)
            except Exception:
                old_live = 0
            inferred_mortality = max(0, old_placed - old_live)
            entry["placed_bird_count"] = placed_bird_count
            if int(entry.get("crop_active", 0) or 0) == 1:
                entry["bird_count"] = max(0, placed_bird_count - inferred_mortality)
            else:
                entry["bird_count"] = placed_bird_count
            entry["pens"] = []
            entry["updated_ts"] = int(time.time())
            entry["updated_by"] = "controller"
            set_entry_for_dest(state, dest_shed, entry)
        state["entries_updated_ts"] = int(time.time())

    state = mutate_state(mutator)
    record_controller_event("entry_saved", "Saved placed bird count", "%s = %d" % (entry_shed_label(dest_shed), placed_bird_count), push_to_office=True)
    return push_to_dashboard(state)


@app.route("/entry/<int:dest_shed>/save", methods=["POST"])
def save_entry_for_dest(dest_shed):
    raw = request.form.get("placed_bird_count", request.form.get("bird_count", "")).strip()
    try:
        placed_bird_count = int(raw)
        if placed_bird_count < 0:
            raise ValueError()
    except Exception:
        return redirect_back_with_status("index", False, "Invalid placed bird count")

    ok, sync_msg = save_entry_for_dest_impl(dest_shed, placed_bird_count)
    return redirect_back_with_status("index", ok, sync_msg if sync_msg else "Saved")


def start_entry_for_dest_impl(dest_shed, placed_bird_count_override=None):
    if not valid_entry_shed(dest_shed):
        return False, "Invalid shed"

    state = load_state()
    if placed_bird_count_override is not None:
        entry = get_entry_for_dest(state, dest_shed)
        entry["placed_bird_count"] = placed_bird_count_override
        entry["bird_count"] = placed_bird_count_override
        entry["pens"] = []
        set_entry_for_dest(state, dest_shed, entry)
    entry = get_entry_for_dest(state, dest_shed)
    if entry["bird_count"] <= 0:
        return False, "Set birds before starting"

    def mutator(state):
        entry = get_entry_for_dest(state, dest_shed)
        if placed_bird_count_override is not None:
            entry["placed_bird_count"] = placed_bird_count_override
            entry["bird_count"] = placed_bird_count_override
            entry["pens"] = []
        entry["crop_active"] = 1
        if int(entry.get("placed_bird_count") or 0) < int(entry.get("bird_count") or 0):
            entry["placed_bird_count"] = entry["bird_count"]
        if entry["placement_epoch"] is None:
            entry["placement_epoch"] = int(time.time())
        entry["updated_ts"] = int(time.time())
        entry["updated_by"] = "controller"
        set_entry_for_dest(state, dest_shed, entry)
        state["entries_updated_ts"] = int(time.time())

    state = mutate_state(mutator)
    record_controller_event("entry_started", "Started entry", entry_shed_label(dest_shed), push_to_office=True)
    return push_to_dashboard(state, pull_back=False)


@app.route("/pen/add", methods=["POST"])
def add_pen():
    side = str(request.form.get("side", "rear") or "rear").strip().lower()
    try:
        dest_shed = int(request.form.get("dest_shed", ""))
    except Exception:
        return redirect_back_with_status("index", False, "Pick which shed the birds are for")
    if not valid_entry_shed(dest_shed):
        return redirect_back_with_status("index", False, "Invalid shed")
    try:
        placed_bird_count = int(str(request.form.get("placed_bird_count", "") or "").strip())
        if placed_bird_count <= 0:
            raise ValueError()
    except Exception:
        return redirect_back_with_status("index", False, "Enter how many birds were placed")
    current = load_state()
    if get_entry_for_dest(current, dest_shed)["bird_count"] > 0:
        return redirect_back_with_status("index", False, "%s already has a pen in this shed" % entry_shed_label(dest_shed))
    # Same count as the office: pens that are started and have birds in them.
    active_pens = [k for k in current.get("entries", {})
                   if get_entry_for_dest(current, k)["crop_active"] == 1 and get_entry_for_dest(current, k)["bird_count"] > 0]
    if len(active_pens) >= 4:
        return redirect_back_with_status("index", False, "A shed holds 4 pens at most")

    ok, sync_msg = start_entry_for_dest_impl(dest_shed, placed_bird_count_override=placed_bird_count)

    def mutator(state):
        if get_entry_for_dest(state, dest_shed)["bird_count"] <= 0:
            return
        entries = state.get("entries", {})
        order = [k for k in ordered_entry_keys(entries, state.get("pen_order", []), load_config().get("shed_no")) if k != str(dest_shed)]
        if side == "front":
            order.insert(0, str(dest_shed))
        else:
            order.append(str(dest_shed))
        state["pen_order"] = order
        state["pen_order_ts"] = int(time.time())

    mutate_state(mutator)
    return redirect_back_with_status("index", ok, sync_msg if sync_msg else "Pen added")


@app.route("/entry/<int:dest_shed>/start", methods=["POST"])
def start_entry_for_dest(dest_shed):
    placed_bird_count_override = None
    raw = str(request.form.get("placed_bird_count", request.form.get("bird_count", "")) or "").strip()
    if raw != "":
        try:
            placed_bird_count_override = int(raw)
            if placed_bird_count_override < 0:
                raise ValueError()
        except Exception:
            return redirect_back_with_status("index", False, "Invalid placed bird count")
    ok, sync_msg = start_entry_for_dest_impl(dest_shed, placed_bird_count_override=placed_bird_count_override)
    return redirect_back_with_status("index", ok, sync_msg if sync_msg else "Started")


def move_entry_for_dest_impl(dest_shed):
    cfg = load_config()
    if not valid_entry_shed(dest_shed):
        return False, "Invalid shed"
    if entry_home_shed_no(dest_shed) == cfg["shed_no"]:
        return False, "Cannot move to same shed"

    state = load_state()
    entry = get_entry_for_dest(state, dest_shed)
    if entry["bird_count"] <= 0 or entry["crop_active"] != 1:
        return False, "Only active entries with birds can move"

    ok = post_move_to_dashboard(cfg["shed_no"], dest_shed)
    if not ok:
        return False, "Move failed"

    # Clear the moved entry locally immediately so background sync cannot
    # re-post the old source allocation back to the office before the pull completes.
    mutate_state(lambda state: (clear_entry_for_dest(state, dest_shed), state.update({"entries_updated_ts": int(time.time())})))
    pull_from_dashboard(load_state())
    record_controller_event("entry_moved", "Moved entry via office", entry_shed_label(dest_shed), push_to_office=True)
    return True, "Entry moved to %s" % shed_display_name_from_number(entry_home_shed_no(dest_shed))


@app.route("/entry/<int:dest_shed>/move", methods=["POST"])
def move_entry_for_dest(dest_shed):
    ok, sync_msg = move_entry_for_dest_impl(dest_shed)
    return redirect_back_with_status("allocation_view", ok, sync_msg if sync_msg else "Moved")


def end_entry_for_dest_impl(dest_shed):
    if not valid_entry_shed(dest_shed):
        return False, "Invalid shed"

    def mutator(state):
        clear_entry_for_dest(state, dest_shed)
        state["last_sync_ts"] = int(time.time())
        state["entries_updated_ts"] = int(time.time())

    state = mutate_state(mutator)
    record_controller_event("entry_ended", "Ended entry", entry_shed_label(dest_shed), push_to_office=True)
    return push_to_dashboard(state)


@app.route("/entry/<int:dest_shed>/end", methods=["POST"])
def end_entry_for_dest(dest_shed):
    ok, sync_msg = end_entry_for_dest_impl(dest_shed)
    return redirect_back_with_status("index", ok, sync_msg if sync_msg else "Ended")


@app.route("/save", methods=["POST"])
def save_entry():
    return save_entry_for_dest(load_config()["shed_no"])


@app.route("/start", methods=["POST"])
def start_entry():
    return start_entry_for_dest(load_config()["shed_no"])


@app.route("/end", methods=["POST"])
def end_entry():
    return end_entry_for_dest(load_config()["shed_no"])


@app.route("/pull", methods=["POST"])
def pull_now():
    state = load_state()
    ok, msg = pull_from_dashboard(state)
    return redirect(url_for("index", ok=1 if ok else 0, msg=msg))


@app.route("/push", methods=["POST"])
def push_now():
    state = load_state()
    ok, msg = push_to_dashboard(state)
    return redirect(url_for("index", ok=1 if ok else 0, msg=msg))


@app.route("/api/dashboard-sync", methods=["POST"])
def dashboard_sync():
    auth_error = require_office_token()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or {}
    cfg = load_config()

    try:
        incoming_shed_no = int(payload.get("shed_no"))
    except Exception:
        incoming_shed_no = None

    if incoming_shed_no != cfg["shed_no"]:
        return jsonify({"ok": False, "error": "Shed number mismatch"}), 400

    adopt_office_climate_limits(payload.get("climate_limits"))

    def mutator(state):
        incoming_entries = payload.get("entries", {})
        if isinstance(incoming_entries, dict):
            state["entries"] = {}
            for key in incoming_entries:
                state["entries"][str(key)] = clean_entry_record(incoming_entries.get(key, {}))
            state["entries_updated_ts"] = int(time.time())
        summary = payload.get("summary", {})
        if isinstance(summary, dict):
            state["dashboard_summary"] = {
                "water_7to7": summary.get("water_7to7"),
                "feed_7to7": summary.get("feed_7to7"),
                "mortality_total": summary.get("mortality_total"),
            }
        try:
            state["last_seen_office_sync_version"] = int(payload.get("sync_version") or 0)
        except Exception:
            state["last_seen_office_sync_version"] = 0
        state["last_seen_office_sync_ts"] = payload.get("generated_ts")
        state["last_sync_ts"] = int(time.time())
        state["last_sync_status"] = "Dashboard push received"

    mutate_state(mutator)
    record_controller_event("office_push_received", "Office pushed state to controller", "Sync version %s" % (payload.get("sync_version") or 0))
    return jsonify({"ok": True, "shed_no": cfg["shed_no"]})


@app.route("/api/pico-ingest", methods=["POST"])
def pico_ingest():
    payload = request.get_json(silent=True) or {}
    state = mutate_state(lambda s: apply_sensor_packet(s, payload))
    if load_config().get("sync_on_sensor_update"):
        auto_sync_if_changed(state, pull_back=False)
    return jsonify({"ok": True, "last_sensor_ts": state["sensors"]["last_sensor_ts"]})


@app.route("/api/state", methods=["GET"])
def api_state():
    cfg = load_config()
    state = load_state()
    return jsonify({
        "shed_no": cfg["shed_no"],
        "dashboard_url": cfg["dashboard_url"],
        "serial_port": detect_serial_port(),
        "available_ports": serial_available_ports(),
        "state": state,
    })


@app.route("/api/home-state", methods=["GET"])
def api_home_state():
    maybe_refresh_from_dashboard()
    maybe_heartbeat_to_dashboard()
    return jsonify(build_home_context())


@app.route("/api/water-stream", methods=["GET"])
def api_water_stream():
    def event_stream():
        while True:
            payload = build_water_stream_payload()
            yield "data: %s\n\n" % json.dumps(payload)
            time.sleep(1.0)

    return Response(event_stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


if __name__ == "__main__":
    cfg = load_config()
    ensure_data_dir()
    start_serial_thread()
    start_monitor_thread()
    start_background_sync_thread()
    start_auto_update_thread()
    app.run(host="0.0.0.0", port=cfg["listen_port"])
