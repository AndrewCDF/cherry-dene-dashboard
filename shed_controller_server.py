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
from datetime import datetime
from urllib.parse import urlparse

try:
    import serial
    import serial.tools.list_ports
except Exception:
    serial = None

app = Flask(__name__)
CDF_APP_ICON_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ios",
    "CherryDeneMobile",
    "Assets.xcassets",
    "AppIcon.appiconset",
    "AppIcon-1024.png",
)

CDF_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#5b5b5b"/>
      <stop offset="100%" stop-color="#3f3f3f"/>
    </linearGradient>
    <linearGradient id="panel" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#4a4a4a"/>
      <stop offset="100%" stop-color="#343434"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="24" stdDeviation="28" flood-color="#000000" flood-opacity="0.28"/>
    </filter>
  </defs>
  <rect width="1024" height="1024" rx="224" fill="url(#bg)"/>
  <rect x="98" y="98" width="828" height="828" rx="184" fill="url(#panel)" filter="url(#shadow)"/>
  <rect x="126" y="126" width="772" height="772" rx="156" fill="none" stroke="#35d07f" stroke-width="26"/>
  <text x="512" y="610" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="304" font-weight="700" letter-spacing="-20" fill="#f3f3f3">CDF</text>
</svg>"""

TOUCH_OPTIMIZE_HEAD = (
    '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-title" content="CDF">'
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
    '.cdf-number-pad__key--url{font-size:18px;}'
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
  const valueEl = document.getElementById('cdfNumberPadValue');
  const decimalBtn = document.getElementById('cdfNumberPadDecimal');
  const httpBtn = document.getElementById('cdfNumberPadHttp');
  const colonBtn = document.getElementById('cdfNumberPadColon');
  const slashBtn = document.getElementById('cdfNumberPadSlash');
  let activeInput = null;
  let dragScroll = null;
  let suppressClickUntil = 0;

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
    if (target && target.matches && target.matches('input[type="number"], input[data-cdf-urlpad]')) {
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
    if (target && target.matches && target.matches('input[type="number"], input[data-cdf-urlpad]')) {
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
    if (!isUrlPadInput(activeInput) && key === '.' && (!supportsDecimal(activeInput) || current.includes('.'))) return;
    if (!isUrlPadInput(activeInput) && current === '0' && key !== '.') {
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
            if "</body>" in body and 'cdf-number-pad-script' not in body:
                body = body.replace("</body>", NUMBER_PAD_BODY + "</body>", 1)
            response.set_data(body)
            response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception:
        pass
    return response

DATA_DIR = "controller_data"
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
SHED_NUMBERS = [1, 2, 3, 4, 6, 7, 8, 9, 10]
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
}

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
BACKUP_KEEP_COUNT = 6
PICO_AUTO_RECOVERY_FREEZE_SECONDS = 90
PICO_AUTO_RECOVERY_COOLDOWN_SECONDS = 10 * 60
PICO_POST_UPDATE_RECOVERY_WAIT_SECONDS = 20
PICO_REBOOT_SETTLE_SECONDS = 2.0
PICO_RECONNECT_TIMEOUT_SECONDS = 20.0
PICO_RECONNECT_PACKET_TIMEOUT_SECONDS = 4.0
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


def list_backup_files():
    base = backups_dir()
    out = []
    try:
        names = sorted(os.listdir(base), reverse=True)
    except Exception:
        return out
    i = 0
    while i < len(names):
        name = names[i]
        path = os.path.join(base, name)
        if os.path.isfile(path) and name.endswith(".zip"):
            out.append(path)
        i += 1
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
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        i = 0
        while i < len(files):
            src = files[i]
            if os.path.exists(src):
                zf.write(src, arcname=os.path.basename(src))
            i += 1
    backups = list_backup_files()
    i = BACKUP_KEEP_COUNT
    while i < len(backups):
        try:
            os.remove(backups[i])
        except Exception:
            pass
        i += 1
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
    }


def default_feed_tracking_state():
    return {
        "last_feed_kg": None,
        "last_feed_ts": None,
        "pending_delivery_kg": 0.0,
        "current_day_key": None,
        "current_day_burn_kg": 0.0,
        "recent_daily_burn_kg": [],
        "avg_daily_burn_kg": None,
        "last_delivery_ts": None,
        "last_delivery_kg": None,
    }


def clean_feed_tracking_state(data):
    if not isinstance(data, dict):
        data = {}

    out = default_feed_tracking_state()
    out.update(data)

    try:
        out["last_feed_kg"] = float(out.get("last_feed_kg")) if out.get("last_feed_kg") not in [None, ""] else None
    except Exception:
        out["last_feed_kg"] = None
    try:
        out["last_feed_ts"] = int(out.get("last_feed_ts")) if out.get("last_feed_ts") not in [None, ""] else None
    except Exception:
        out["last_feed_ts"] = None
    try:
        out["pending_delivery_kg"] = float(out.get("pending_delivery_kg") or 0.0)
    except Exception:
        out["pending_delivery_kg"] = 0.0
    out["current_day_key"] = str(out.get("current_day_key") or "") or None
    try:
        out["current_day_burn_kg"] = float(out.get("current_day_burn_kg") or 0.0)
    except Exception:
        out["current_day_burn_kg"] = 0.0
    try:
        out["avg_daily_burn_kg"] = float(out.get("avg_daily_burn_kg")) if out.get("avg_daily_burn_kg") not in [None, ""] else None
    except Exception:
        out["avg_daily_burn_kg"] = None
    try:
        out["last_delivery_ts"] = int(out.get("last_delivery_ts")) if out.get("last_delivery_ts") not in [None, ""] else None
    except Exception:
        out["last_delivery_ts"] = None
    try:
        out["last_delivery_kg"] = float(out.get("last_delivery_kg")) if out.get("last_delivery_kg") not in [None, ""] else None
    except Exception:
        out["last_delivery_kg"] = None

    cleaned_days = []
    rows = out.get("recent_daily_burn_kg", [])
    if isinstance(rows, list):
        i = 0
        while i < len(rows):
            rec = rows[i]
            if isinstance(rec, dict):
                key = str(rec.get("day_key") or "").strip()
                try:
                    burn = float(rec.get("burn_kg") or 0.0)
                except Exception:
                    burn = 0.0
                if key:
                    cleaned_days.append({
                        "day_key": key,
                        "burn_kg": round(max(0.0, burn), 3),
                    })
            i += 1
    out["recent_daily_burn_kg"] = cleaned_days[-7:]
    return out


def feed_tracking_day_key(ts):
    dt_obj = datetime.fromtimestamp(int(ts)) - timedelta(hours=7)
    return dt_obj.strftime("%Y-%m-%d")


def update_feed_tracking(state, feed_kg, now_ts):
    try:
        feed_kg = float(feed_kg)
    except Exception:
        return None

    tracker = clean_feed_tracking_state(state.get("feed_tracking", {}))
    active_crop = total_birds_from_entries(state.get("entries", {})) > 0
    day_key = feed_tracking_day_key(now_ts)
    detected_delivery_kg = None

    if tracker["current_day_key"] is None:
        tracker["current_day_key"] = day_key
    elif tracker["current_day_key"] != day_key:
        tracker["recent_daily_burn_kg"].append({
            "day_key": tracker["current_day_key"],
            "burn_kg": round(max(0.0, tracker.get("current_day_burn_kg") or 0.0), 3),
        })
        tracker["recent_daily_burn_kg"] = tracker["recent_daily_burn_kg"][-7:]
        tracker["current_day_key"] = day_key
        tracker["current_day_burn_kg"] = 0.0

    last_feed_kg = tracker.get("last_feed_kg")
    if last_feed_kg is not None:
        delta = feed_kg - float(last_feed_kg)
        noise_threshold_kg = 5.0
        delivery_threshold_kg = 150.0

        if delta <= -noise_threshold_kg:
            if active_crop:
                tracker["current_day_burn_kg"] = round(
                    max(0.0, float(tracker.get("current_day_burn_kg") or 0.0) + (-delta)),
                    3,
                )
            if tracker.get("pending_delivery_kg", 0.0) >= delivery_threshold_kg:
                detected_delivery_kg = round(float(tracker.get("pending_delivery_kg") or 0.0), 1)
                tracker["last_delivery_ts"] = int(now_ts)
                tracker["last_delivery_kg"] = detected_delivery_kg
            tracker["pending_delivery_kg"] = 0.0
        elif delta >= noise_threshold_kg:
            if active_crop:
                tracker["pending_delivery_kg"] = round(float(tracker.get("pending_delivery_kg") or 0.0) + delta, 3)
            else:
                tracker["pending_delivery_kg"] = 0.0
        else:
            if active_crop and tracker.get("pending_delivery_kg", 0.0) >= delivery_threshold_kg:
                detected_delivery_kg = round(float(tracker.get("pending_delivery_kg") or 0.0), 1)
                tracker["last_delivery_ts"] = int(now_ts)
                tracker["last_delivery_kg"] = detected_delivery_kg
            tracker["pending_delivery_kg"] = 0.0

    tracker["last_feed_kg"] = round(feed_kg, 3)
    tracker["last_feed_ts"] = int(now_ts)

    burn_values = []
    recent_days = tracker.get("recent_daily_burn_kg", [])
    i = 0
    while i < len(recent_days):
        try:
            burn = float(recent_days[i].get("burn_kg") or 0.0)
            if burn > 0:
                burn_values.append(burn)
        except Exception:
            pass
        i += 1
    try:
        current_day_burn = float(tracker.get("current_day_burn_kg") or 0.0)
        if current_day_burn > 0:
            burn_values.append(current_day_burn)
    except Exception:
        pass
    tracker["avg_daily_burn_kg"] = average_last_n(burn_values, 3)

    state["feed_tracking"] = tracker
    return detected_delivery_kg


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
        "feed_tracking": default_feed_tracking_state(),
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
    state["feed_tracking"] = clean_feed_tracking_state(state.get("feed_tracking", {}))
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
    while i < len(SHED_NUMBERS):
        dest_shed = SHED_NUMBERS[i]
        rec = get_entry_for_dest(state, dest_shed)
        rows.append({
            "dest_shed": dest_shed,
            "bird_count": rec["bird_count"],
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
            parts.append("Shed %d: %s" % (keys[i], fmt_value(rec["bird_count"], "i")))
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
    payload["controller_meta"] = {
        "temp_c": sensors.get("temp_c"),
        "rh_pct": sensors.get("rh_pct"),
        "temp_low_c": cfg.get("temp_low_c"),
        "temp_high_c": cfg.get("temp_high_c"),
        "temp_amber_margin_c": cfg.get("temp_amber_margin_c"),
        "rh_low_pct": cfg.get("rh_low_pct"),
        "rh_high_pct": cfg.get("rh_high_pct"),
        "rh_amber_margin_pct": cfg.get("rh_amber_margin_pct"),
        "water_lpm": sensors.get("water_lpm"),
        "water_low_lpm": cfg.get("water_low_lpm"),
        "water_total_litres": water_total_litres,
        "feed_kg": sensors.get("feed_kg"),
        "feed_low_kg": cfg.get("feed_low_kg"),
        "lighting_on": sensors.get("lighting_on"),
        "lighting_enabled": lighting_enabled(cfg),
        "lighting_label": lighting_label_for(cfg),
        "lighting_last_changed_ts": sensors.get("lighting_last_changed_ts"),
        "feed_daily_burn_kg": state.get("feed_tracking", {}).get("avg_daily_burn_kg"),
        "last_feed_delivery_ts": state.get("feed_tracking", {}).get("last_delivery_ts"),
        "last_feed_delivery_kg": state.get("feed_tracking", {}).get("last_delivery_kg"),
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


def fetch_current_crop_hourly_history(shed_no):
    try:
        with dashboard_request("/api/shed/%d/current-crop/hourly" % shed_no, method="GET") as resp:
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


def post_mortality_to_dashboard(shed_no, dest_shed, bird_loss, note=""):
    try:
        with dashboard_request(
            "/api/shed/%d/mortality" % shed_no,
            method="POST",
            payload={
                "dest_shed": dest_shed,
                "bird_loss": bird_loss,
                "note": note,
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
            incoming = payload.get("entries", {})
            if isinstance(incoming, dict):
                state["entries"] = {}
                for key in incoming:
                    state["entries"][str(key)] = clean_entry_record(incoming.get(key, {}))
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
    birds_placed_raw = birds_remaining_raw + mortality_total_raw if birds_remaining_raw > 0 else 0
    birds_display = fmt_value(birds_remaining_raw if birds_remaining_raw > 0 else None, "i")
    if birds_placed_raw > 0:
        birds_display = "%s (%s)" % (
            fmt_value(birds_remaining_raw, "i"),
            fmt_value(birds_placed_raw, "i"),
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

    return {
        "shed_no": cfg["shed_no"],
        "host_ips": host_ipv4_display(),
        "dashboard_url": cfg["dashboard_url"],
        "serial_port": detect_serial_port(),
        "refresh_seconds": max(0.25, float(cfg["touch_refresh_seconds"])),
        "sync_status": sync_status,
        "sync_class": sync_class,
        "sync_short": "%s • %s" % (short_status_text("sync", sync_status), fmt_age_seconds(state.get("last_sync_ts"))),
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


def pico_frozen(sensors, stale_after_s=STALE_SENSOR_SECONDS, now_ts=None):
    sensor_age = sensor_age_seconds(sensors, now_ts=now_ts)
    return sensor_age is not None and sensor_age > int(stale_after_s)


def pico_warning_banner_text(sensors, now_ts=None):
    sensor_age = sensor_age_seconds(sensors, now_ts=now_ts)
    if sensor_age is None or sensor_age <= STALE_SENSOR_SECONDS:
        return ""
    return "Pico frozen. No sensor update received for %s." % fmt_age_seconds(sensors.get("last_sensor_ts"))


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
    return " • ".join(parts)


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


def update_feed_from_raw(sensors):
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

    cfg = load_config()
    tare = cfg.get("feed_tare_raw")
    scale = cfg.get("feed_kg_per_raw_unit")
    capacity = cfg.get("feed_capacity_kg")

    if tare in [None, ""] or scale in [None, ""]:
        return

    try:
        tare = float(tare)
        scale = float(scale)
        capacity = float(capacity) if capacity not in [None, ""] else None
    except Exception:
        return

    if scale <= 0:
        return

    feed_kg = max(0.0, (feed_raw - tare) * scale)
    if capacity is not None and capacity > 0:
        feed_kg = min(feed_kg, capacity)
    sensors["feed_kg"] = round(feed_kg, 1)


def apply_sensor_packet(state, packet):
    sensors = state.get("sensors", default_sensor_state())
    now_ts = int(time.time())
    packet_kind = str(packet.get("packet_kind") or "full").strip().lower()

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
        "status": "device_status",
        "device_status": "device_status",
    }

    for key in key_map:
        if key in packet:
            sensors[key_map[key]] = packet.get(key)

    if isinstance(packet.get("alarms"), list) and packet_kind != "checkpoint":
        sensors["alarms"] = packet.get("alarms")

    sensors["pico_connected"] = True
    sensors["last_sensor_ts"] = now_ts
    sensors["last_serial_line"] = json.dumps(packet)

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
    update_feed_from_raw(sensors)
    detected_delivery_kg = update_feed_tracking(state, sensors.get("feed_kg"), now_ts)
    evaluate_augers(sensors, now_ts=now_ts)
    state["sensors"] = sensors
    if bool(state.get("pending_pico_update_recovery")):
        state["pending_pico_update_recovery"] = False
        state["pending_pico_update_recovery_set_ts"] = None
        state["last_pico_recovery_status"] = "Pico returned after update"
        state["last_pico_recovery_result_ts"] = now_ts
    if detected_delivery_kg is not None:
        record_controller_event(
            "feed_delivery_auto",
            "Feed delivery auto-detected",
            "Detected %.1f KG feed increase" % detected_delivery_kg,
            push_to_office=True,
        )

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


def serial_error_update(message):
    def mutator(state):
        sensors = state.get("sensors", default_sensor_state())
        sensors["pico_connected"] = False
        sensors["device_status"] = message
        state["sensors"] = sensors
        reconcile_alarm_history(state)
    mutate_state(mutator)


def serial_reader_loop():
    while not SERIAL_STOP.is_set():
        cfg = load_config()

        if not cfg.get("serial_enabled"):
            serial_error_update("Serial disabled")
            SERIAL_STOP.wait(2.0)
            continue

        if serial is None:
            serial_error_update("pyserial not installed")
            SERIAL_STOP.wait(5.0)
            continue

        port = detect_serial_port()
        if not port:
            serial_error_update("Pico offline: no Pico serial device found")
            SERIAL_STOP.wait(3.0)
            continue

        try:
            conn = serial.Serial(
                port=port,
                baudrate=cfg["serial_baudrate"],
                timeout=cfg["serial_timeout"],
            )
        except Exception as exc:
            serial_error_update("Pico offline: %s" % exc)
            SERIAL_STOP.wait(3.0)
            continue

        mutate_state(lambda state: apply_sensor_packet(state, {"status": "Pico connected on %s" % port}))

        try:
            while not SERIAL_STOP.is_set():
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
                    mutate_state(lambda state: _record_raw_serial_line(state, line))
                    continue

                state = mutate_state(lambda s: apply_sensor_packet(s, packet))
                if packet.get("packet_kind") != "checkpoint" and load_config().get("sync_on_sensor_update"):
                    auto_sync_if_changed(state, pull_back=False)
        finally:
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
                "No fresh Pico packet arrived after controller restart",
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
                "No sensor update received for %s" % fmt_age_seconds(state.get("sensors", {}).get("last_sensor_ts")),
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
    <title>Shed {{ shed_no }} Controller</title>
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
            box-shadow: 0 0 20px rgba(0, 0, 0, 0.08);
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
            text-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .hero-crop.inactive {
            text-shadow:
                0 0 10px rgba(255,119,119,0.95),
                0 0 20px rgba(255,119,119,0.65),
                0 0 34px rgba(255,119,119,0.35);
        }
        .hero-datetime.active {
            text-shadow:
                0 0 10px rgba(53,208,127,0.90),
                0 0 18px rgba(53,208,127,0.55),
                0 0 28px rgba(53,208,127,0.28);
        }
        .hero-datetime.inactive {
            text-shadow:
                0 0 10px rgba(255,119,119,0.90),
                0 0 18px rgba(255,119,119,0.55),
                0 0 28px rgba(255,119,119,0.28);
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
            border-color: rgba(53,208,127,0.90);
            box-shadow:
                0 0 10px rgba(53,208,127,0.28),
                0 0 18px rgba(53,208,127,0.16);
        }
        .hero-birds.inactive,
        .hero-age.inactive,
        .hero-mortality.inactive {
            border-color: rgba(255,119,119,0.90);
            box-shadow:
                0 0 10px rgba(255,119,119,0.24),
                0 0 18px rgba(255,119,119,0.14);
        }
        .hero-age.lighting-on {
            border-color: rgba(53,208,127,0.90);
            box-shadow:
                0 0 10px rgba(53,208,127,0.28),
                0 0 18px rgba(53,208,127,0.16);
        }
        .hero-age.lighting-off {
            border-color: rgba(255,119,119,0.90);
            box-shadow:
                0 0 10px rgba(255,119,119,0.24),
                0 0 18px rgba(255,119,119,0.14);
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
            color: #fff3c3;
            opacity: 1;
            filter: drop-shadow(0 0 8px rgba(255, 208, 106, 0.75));
        }
        .hero-light-icon.lighting-off {
            color: #d5d5d5;
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
        .pill.ok { border-color: rgba(123,225,170,0.45); color: var(--green); }
        .pill.warn { border-color: rgba(255,208,106,0.45); color: var(--amber); }
        .pill.bad { border-color: rgba(255,119,119,0.45); color: var(--red); }
        .hero-pills {
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #8b8b8b;
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
        .auger-grid-shell {
            grid-column: 1 / span 3;
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
        .metric.flow-green {
            border-color: #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .metric.flow-red,
        .metric.feed-red {
            border-color: #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
        }
        .metric.temp-green {
            border-color: #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .metric.temp-warn {
            border-color: #ffd06a;
            box-shadow:
                0 0 10px rgba(255,208,106,0.95),
                0 0 20px rgba(255,208,106,0.65),
                0 0 34px rgba(255,208,106,0.35);
        }
        .metric.temp-red {
            border-color: #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
        }
        .metric.rh-green {
            border-color: #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .metric.rh-warn {
            border-color: #ffd06a;
            box-shadow:
                0 0 10px rgba(255,208,106,0.95),
                0 0 20px rgba(255,208,106,0.65),
                0 0 34px rgba(255,208,106,0.35);
        }
        .metric.rh-red {
            border-color: #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
        }
        .metric.feed-green {
            border-color: #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .metric.state-green {
            border-color: #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .metric.state-warn {
            border-color: #ffd06a;
            box-shadow:
                0 0 10px rgba(255,208,106,0.95),
                0 0 20px rgba(255,208,106,0.65),
                0 0 34px rgba(255,208,106,0.35);
        }
        .metric.state-red {
            border-color: #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
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
            display: block;
            width: 100%;
            margin-top: 10px;
            padding-top: 8px;
            border-top: 1px solid rgba(255,255,255,0.16);
            font-size: 24px;
            line-height: 1.2;
            color: var(--text);
            font-weight: 700;
            text-align: center;
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
            border: 1px solid #818181;
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
            border: 1px solid #8a8a8a;
            background: linear-gradient(180deg, #7a7a7a, #676767);
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
        button {
            min-height: 78px;
            width: 100%;
            border-radius: 16px;
            border: 1px solid #8a8a8a;
            background: linear-gradient(180deg, #7d7d7d, #696969);
            color: var(--text);
            font-size: 24px;
            font-weight: 700;
            cursor: pointer;
        }
        button:active {
            transform: scale(0.99);
        }
        .danger {
            border-color: #7f4b53;
            background: linear-gradient(180deg, #542e34, #3e2328);
        }
        .secondary {
            border-color: #8a8a8a;
            background: linear-gradient(180deg, #757575, #636363);
            font-size: 20px;
        }
        .msg {
            margin-bottom: 16px;
            padding: 14px 16px;
            border-radius: 16px;
            border: 1px solid #385f6f;
            background: rgba(33, 71, 88, 0.42);
            font-size: 18px;
        }
        .msg.error {
            border-color: #7f4b53;
            background: rgba(89, 42, 49, 0.42);
        }
        .msg.warn {
            border-color: rgba(255,208,106,0.45);
            background: rgba(89, 68, 27, 0.35);
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
            border-bottom: 1px solid #818181;
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
            border: 1px solid rgba(255,119,119,0.35);
            background: rgba(84, 34, 34, 0.38);
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
                            <h1 id="headerTitle" class="{{ crop_class }}">CDF - SHED {{ shed_no }}</h1>
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
                            <div class="hero-age {{ lighting_badge_class }}" id="lightingBox">
                                <span class="hero-age-label">Lighting</span>
                                <span id="lightingHeroIcon" class="hero-age-val hero-light-icon {{ lighting_badge_class }}">💡</span>
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
                        <div class="metric-sub">C</div>
                    </div>
                </a>
                <a class="metric-link" href="{{ url_for('rh_settings_view') }}">
                    <div id="rhTile" class="metric metric-mini {{ rh_glow }}">
                        <div class="metric-label">RH</div>
                        <div class="metric-val" id="rhValue">{{ rh_pct }}</div>
                        <div class="metric-sub">%RH</div>
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
                    <div class="metric-label">Water Yesterday 7am-7am</div>
                    <div class="metric-val" id="water7to7Value">{{ water_7to7 }}</div>
                    <div class="metric-sub">Litres</div>
                </div>
            </a>
            {% if auger_tiles %}
            <div class="auger-grid-shell count-{{ auger_count }}">
                {% for auger in auger_tiles %}
                <div id="auger-{{ auger.key }}" class="metric {{ auger.glow }}">
                    <div class="metric-label">{{ auger.label }}</div>
                    <div class="metric-val" style="font-size:30px;" data-auger-status>{{ auger.status }}</div>
                    <div class="metric-sub" data-auger-runtime>{% if auger.runtime %}{{ auger.runtime }}{% else %}&nbsp;{% endif %}</div>
                    <div class="metric-sub metric-sub-auger-last" data-auger-last-run>{{ auger.last_run }}</div>
                </div>
                {% endfor %}
            </div>
            {% endif %}
            <a class="metric-link" href="{{ url_for('feed_history_view') }}">
                <div class="metric">
                    <div class="metric-label">Feed Yesterday 7am-7am</div>
                    <div class="metric-val" id="feed7to7Value">{{ feed_7to7 }}</div>
                    <div class="metric-sub">KG</div>
                </div>
            </a>
        </div>

        <div class="main-grid">
            <div class="panel">
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

            const lightingHeroIcon = document.getElementById('lightingHeroIcon');
            if (lightingHeroIcon) {
                lightingHeroIcon.classList.remove('lighting-on', 'lighting-off');
                lightingHeroIcon.classList.add(data.lighting_badge_class || 'lighting-off');
            }
            const lightingBox = document.getElementById('lightingBox');
            if (lightingBox) {
                lightingBox.classList.remove('lighting-on', 'lighting-off');
                lightingBox.classList.add(data.lighting_badge_class || 'lighting-off');
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


SETTINGS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Settings</title>
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
        .grid {
            display: grid;
            grid-template-columns: 1.05fr 0.95fr;
            gap: 16px;
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
        .action-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
        }
        .action-form {
            margin: 0;
        }
        .button-link {
            display: block;
            min-height: 74px;
            width: 100%;
            border-radius: 16px;
            border: 1px solid #8a8a8a;
            background: linear-gradient(180deg, #7a7a7a, #676767);
            color: var(--text);
            font-size: 20px;
            font-weight: 700;
            text-decoration: none;
            text-align: center;
            line-height: 74px;
            white-space: nowrap;
        }
        .button-icon {
            margin-right: 10px;
        }
        .full-panel {
            margin-top: 16px;
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
            border-bottom: 1px solid #818181;
            font-size: 18px;
        }
        .detail:last-child {
            border-bottom: 0;
        }
        .label {
            color: var(--muted);
        }
        .status-note {
            margin: 12px 0 0;
            color: var(--muted);
            font-size: 16px;
        }
        .status-note.is-busy {
            color: var(--text);
        }
        .msg {
            margin-bottom: 16px;
            padding: 12px 14px;
            border-radius: 14px;
            border: 1px solid #8a8a8a;
            background: rgba(115, 115, 115, 0.96);
            font-size: 18px;
        }
        .button-row {
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
            margin-top: 14px;
            max-width: 560px;
            margin-left: auto;
            margin-right: auto;
        }
        .update-split {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-top: 12px;
        }
        .update-box {
            background: var(--panel-2);
            border: 1px solid var(--line);
            border-radius: 16px;
            padding: 16px;
        }
        .update-box h2 {
            margin: 0 0 10px 0;
            font-size: 24px;
        }
        .collapse {
            margin-top: 14px;
        }
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid var(--line);
            border-radius: 12px;
            background: rgba(86, 86, 86, 0.96);
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker {
            display: none;
        }
        .collapse[open] summary {
            margin-bottom: 12px;
        }
        .button-row form {
            width: 100%;
            margin: 0;
        }
        button {
            min-height: 74px;
            width: 100%;
            border-radius: 16px;
            border: 1px solid #8a8a8a;
            background: linear-gradient(180deg, #7a7a7a, #676767);
            color: var(--text);
            font-size: 20px;
            font-weight: 700;
            cursor: pointer;
        }
        button.secondary {
            background: linear-gradient(180deg, #737373, #626262);
        }
        @media (max-width: 900px) {
            .grid {
                grid-template-columns: 1fr;
            }
            .update-split {
                grid-template-columns: 1fr;
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
                <h1>Shed {{ shed_no }} Settings</h1>
                <div class="sub">Controller tools, alarms, logs, config, and commissioning.</div>
                <div class="action-grid">
                    <a class="button-link" href="{{ url_for('allocation_view') }}">Shed Allocation</a>
                    <a class="button-link" href="{{ url_for('controller_alarms_view') }}">Alarms{% if alarm_count %} ({{ alarm_count }}){% endif %}</a>
                    <a class="button-link" href="{{ url_for('commissioning_view') }}">Commissioning</a>
                    <a class="button-link" href="{{ url_for('controller_config_view') }}">Controller Config</a>
                    <a class="button-link" href="{{ url_for('controller_health_view') }}">Controller Health</a>
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
                <div class="sub">Current shed state and latest controller heartbeat.</div>
                <div class="detail-list">
                    <div class="detail"><span class="label">Crop Active</span><span>{{ "Yes" if entry.crop_active == 1 else "No" }}</span></div>
                    <div class="detail"><span class="label">Started</span><span>{{ started_at }}</span></div>
                    <div class="detail"><span class="label">Updated By</span><span>{{ entry.updated_by }}</span></div>
                    <div class="detail"><span class="label">Updated At</span><span>{{ updated_at }}</span></div>
                    <div class="detail"><span class="label">Sync</span><span>{{ sync_short }}</span></div>
                    <div class="detail"><span class="label">Pico</span><span>{{ sensor_status_short }}</span></div>
                </div>
            </div>
        </div>
        <div class="panel full-panel">
            <h1 style="font-size:28px;">Software Update</h1>
            <div class="sub">Check for a newer controller version. When the pulled update includes Pico firmware changes, they are deployed automatically too.</div>
            <div class="update-split">
                <div class="update-box">
                    <h2>Controller Update</h2>
                    <div class="detail-list">
                        <div class="detail"><span class="label">Last Check</span><span id="controllerUpdateChecked">{{ update_checked_at }}</span></div>
                    </div>
                    <div id="controllerUpdateStatus" class="status-note">{{ update_status.status }}</div>
                    <div class="button-row">
                        <form id="controllerUpdateCheckForm" method="post" action="{{ url_for('check_update_view') }}">
                            <button id="controllerUpdateCheckButton" class="secondary" type="submit">Check for Update</button>
                        </form>
                        <form id="controllerUpdateApplyForm" method="post" action="{{ url_for('apply_update_view') }}" {% if not update_status.update_available %}style="display:none;"{% endif %}>
                            <button type="submit">Update Controller</button>
                        </form>
                    </div>
                    {% if update_status.restart_required %}
                    <div class="status-note">Latest code has been pulled. A controller restart is required to run the new version.</div>
                    {% endif %}
                    <details class="collapse">
                        <summary>Show Version Details</summary>
                        <div class="detail-list">
                            <div class="detail"><span class="label">Branch</span><span id="controllerUpdateBranch">{{ update_status.branch }}</span></div>
                            <div class="detail"><span class="label">Current Version</span><span id="controllerUpdateCurrent">{{ update_status.local_commit }}</span></div>
                            <div class="detail"><span class="label">Latest Version</span><span id="controllerUpdateLatest">{{ update_status.remote_commit }}</span></div>
                        </div>
                    </details>
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
                        <form method="post" action="{{ url_for('switch_controller_mode_view') }}">
                            <input type="hidden" name="target_mode" value="{{ next_mode_key }}">
                            <input type="number" name="mode_pin" inputmode="numeric" enterkeyhint="done" placeholder="Enter mode PIN" style="width:100%; min-height:64px; border-radius:14px; border:1px solid #8a8a8a; background:#686868; color:#ececec; font-size:22px; padding:10px 14px; box-sizing:border-box; margin-bottom:12px;">
                            <button type="submit">{{ "Go Live" if next_mode_key == "live" else "Return to Commissioning" }}</button>
                        </form>
                    </div>
                </div>
                <div class="update-box">
                    <h2>Mode Notes</h2>
                    <div class="detail-list">
                        <div class="detail"><span class="label">Commissioning</span><span>Setup safeguards on</span></div>
                        <div class="detail"><span class="label">Live</span><span>Production behavior on</span></div>
                    </div>
                    <div class="status-note">Use commissioning while wiring and proving sensors. Switch to live once the shed is ready for normal alarms and behavior.</div>
                </div>
            </div>
        </div>
    </div>
</body>
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
            border-bottom: 1px solid #818181;
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
            border: 1px solid rgba(255,119,119,0.35);
            background: rgba(84, 34, 34, 0.38);
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
        <div class="topbar"><a href="{{ url_for('controller_settings_view') }}">← Back</a></div>
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
        body { margin:0; color:var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background:#5b5b5b; }
        .wrap { max-width:1024px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color:var(--text); text-decoration:none; font-size:18px; }
        .grid { display:grid; grid-template-columns:1.2fr 0.8fr; gap:16px; }
        .panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:18px; }
        h1 { margin:0 0 8px 0; font-size:38px; }
        .sub { color:var(--muted); margin-bottom:16px; font-size:18px; }
        .field { margin-bottom:14px; }
        .group-title { margin:18px 0 10px 0; font-size:18px; color:var(--text); }
        label { display:block; color:var(--muted); margin-bottom:8px; font-size:15px; }
        input[type="text"], input[type="number"] { width:100%; min-height:64px; border-radius:16px; border:1px solid var(--line); background:#686868; color:var(--text); font-size:24px; padding:10px 14px; box-sizing:border-box; }
        .value-readout { min-height:64px; border-radius:16px; border:1px solid var(--line); background:#5f5f5f; color:var(--text); font-size:22px; padding:14px; box-sizing:border-box; display:flex; align-items:center; word-break:break-word; }
        .check { display:flex; align-items:center; justify-content:space-between; padding:12px 0; border-bottom:1px solid #818181; font-size:18px; }
        .check:last-child { border-bottom:0; }
        input[type="checkbox"] { width:28px; height:28px; }
        button, .button-link { display:block; width:100%; min-height:68px; border-radius:16px; border:1px solid #8a8a8a; background:linear-gradient(180deg, #7d7d7d, #696969); color:var(--text); font-size:20px; font-weight:700; text-decoration:none; text-align:center; line-height:68px; cursor:pointer; }
        .button-link { margin-top:12px; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:12px 0; border-bottom:1px solid #818181; font-size:16px; }
        .detail:last-child { border-bottom:0; }
        .hint { color:var(--muted); font-size:15px; margin-top:12px; }
        .auger-grid { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; margin-top:10px; }
        .auger-card { border:1px solid #818181; border-radius:16px; padding:14px; background:#636363; }
        .auger-card h3 { margin:0 0 12px 0; font-size:18px; color:var(--text); }
        .auger-card .check { padding:10px 0 0 0; border-bottom:0; }
        @media (max-width: 900px) { .grid { grid-template-columns:1fr; } .auger-grid { grid-template-columns:1fr; } }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('controller_settings_view') }}">← Back</a></div>
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
        body { margin:0; color:var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background:#5b5b5b; }
        .wrap { max-width:1024px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color:var(--text); text-decoration:none; font-size:18px; }
        .panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:18px; }
        h1 { margin:0 0 8px 0; font-size:38px; }
        .sub { color:var(--muted); margin-bottom:16px; font-size:18px; }
        .alarm-list { display:grid; gap:12px; }
        .alarm { padding:14px 16px; border-radius:16px; border:1px solid #818181; background:#686868; }
        .alarm.bad { border-color:rgba(255,119,119,0.45); }
        .alarm.warn { border-color:rgba(255,208,106,0.45); }
        .alarm-title { font-size:20px; font-weight:700; margin-bottom:4px; }
        .alarm-detail { color:var(--muted); font-size:16px; }
        .okbox { padding:18px; border-radius:16px; border:1px solid rgba(123,225,170,0.35); color:var(--green); background:rgba(30,57,42,0.25); font-size:20px; }
        .section-title { margin:22px 0 12px 0; font-size:24px; font-weight:700; }
        .history-table { width:100%; border-collapse:collapse; }
        .history-table th, .history-table td { text-align:left; padding:12px 10px; border-bottom:1px solid #818181; font-size:16px; vertical-align:top; }
        .history-table th { color:var(--muted); font-weight:700; }
        .history-pill { display:inline-block; padding:4px 10px; border-radius:999px; border:1px solid #818181; font-size:13px; font-weight:700; }
        .history-pill.bad { border-color:rgba(255,119,119,0.45); color:var(--red); }
        .history-pill.ok { border-color:rgba(123,225,170,0.45); color:var(--green); }
        button { display:block; width:100%; min-height:68px; border-radius:16px; border:1px solid #8a8a8a; background:linear-gradient(180deg, #7d7d7d, #696969); color:var(--text); font-size:20px; font-weight:700; cursor:pointer; margin-top:16px; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('controller_settings_view') }}">← Back</a></div>
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
        body { margin:0; color:var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background:#5b5b5b; }
        .wrap { max-width:1300px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color:var(--text); text-decoration:none; font-size:18px; }
        .panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:18px; }
        h1 { margin:0 0 8px 0; font-size:38px; }
        .sub { color:var(--muted); margin-bottom:16px; font-size:18px; }
        table { width:100%; border-collapse:collapse; font-size:14px; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; vertical-align:top; }
        th { color:#f0f0f0; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('controller_settings_view') }}">← Back</a></div>
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
        body { margin:0; color:var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background:#5b5b5b; }
        .wrap { max-width:1200px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color:var(--text); text-decoration:none; font-size:18px; }
        .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
        .panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:18px; }
        h1 { margin:0 0 8px 0; font-size:38px; }
        .sub { color:var(--muted); margin-bottom:16px; font-size:18px; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #818181; font-size:16px; }
        .detail:last-child { border-bottom:0; }
        .label { color:var(--muted); }
        .mono { font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:13px; color:#f0f0f0; word-break:break-word; background:var(--panel2); border:1px solid #818181; border-radius:14px; padding:12px; }
        @media (max-width: 900px) { .grid { grid-template-columns:1fr; } }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('controller_settings_view') }}">← Back</a></div>
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
                <div class="detail"><span class="label">Feed Raw</span><span>{{ feed_raw_units }}</span></div>
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
            border: 1px solid #8a8a8a;
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
            border: 1px solid #818181;
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
            border-bottom: 1px solid #818181;
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
        <div class="topbar"><a href="{{ url_for('controller_settings_view') }}">← Back</a></div>
        <div class="panel">
            <h1>Shed {{ shed_no }} {{ metric_title }}</h1>
            <div class="sub">Current crop {{ crop_code }} hourly {{ metric_title|lower }} history.</div>
            {% if extra_link_href %}
            <div class="action-row">
                <a class="action-link" href="{{ extra_link_href }}">{{ extra_link_label }}</a>
            </div>
            {% endif %}
            {% if rows %}
            <div class="chart-wrap">
                <div class="chart-box"><canvas id="historyChart"></canvas></div>
            </div>
            {% else %}
            <div class="empty">No hourly history available for the current crop.</div>
            {% endif %}
        </div>
        <div class="panel">
            <h1 style="font-size:26px;">Hourly Table</h1>
            {% if rows %}
            <table>
                <thead>
                    <tr>
                        <th>Hour</th>
                        <th>{{ y_axis_title }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in table_rows %}
                    <tr class="paged-row">
                        <td>{{ row.label }}</td>
                        <td>{{ row.value }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            <div class="table-controls">
                <button type="button" id="historyTableLoadMore" class="action-link">Load next 20</button>
                <div class="empty" id="historyTableInfo" style="font-size:15px; padding:0;"></div>
            </div>
            {% else %}
            <div class="empty">No rows to display.</div>
            {% endif %}
        </div>
    </div>
    <script>
    const labels = {{ labels|tojson }};
    const values = {{ values|tojson }};

    function setupPagedTable(buttonId, infoId, initialCount = 20, step = 20) {
        const rows = Array.from(document.querySelectorAll('.paged-row'));
        const button = document.getElementById(buttonId);
        const info = document.getElementById(infoId);
        if (!rows.length) {
            if (button) button.style.display = 'none';
            if (info) info.textContent = '';
            return;
        }

        let visibleCount = Math.min(initialCount, rows.length);

        function render() {
            rows.forEach((row, index) => {
                row.style.display = index < visibleCount ? '' : 'none';
            });
            if (info) {
                info.textContent = `Showing ${Math.min(visibleCount, rows.length)} of ${rows.length}`;
            }
            if (button) {
                button.style.display = visibleCount < rows.length ? '' : 'none';
            }
        }

        if (button) {
            button.addEventListener('click', () => {
                visibleCount = Math.min(rows.length, visibleCount + step);
                render();
            });
        }

        render();
    }

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
                plugins: { legend: { labels: { color: '#f1f8fb' } } },
                scales: {
                    x: { ticks: { color: '#d2d2d2' }, grid: { color: '#818181' } },
                    y: { ticks: { color: '#d2d2d2' }, grid: { color: '#818181' } }
                }
            }
        });
    }
    setupPagedTable('historyTableLoadMore', 'historyTableInfo');
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
        th, td { border-bottom: 1px solid #818181; padding: 10px 8px; text-align: left; }
        th { color: var(--muted); }
        .empty { color: var(--muted); font-size: 18px; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('feed_history_view') }}">← Back to Feed History</a></div>
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


RANGE_SETTINGS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} {{ title }}</title>
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
            max-width: 860px;
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
        h1 {
            margin: 0 0 8px 0;
            font-size: 38px;
        }
        .sub {
            color: var(--muted);
            margin-bottom: 16px;
            font-size: 18px;
        }
        .current {
            font-size: 34px;
            font-weight: 700;
        }
        .form-rows {
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
        }
        .form-row {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
        }
        label {
            display: block;
            color: var(--muted);
            font-size: 16px;
            margin-bottom: 8px;
        }
        input[type="number"] {
            width: 100%;
            min-height: 72px;
            border-radius: 16px;
            border: 1px solid var(--line);
            background: #686868;
            color: var(--text);
            font-size: 30px;
            padding: 12px 16px;
            box-sizing: border-box;
        }
        button {
            min-height: 72px;
            width: 100%;
            border-radius: 16px;
            border: 1px solid #8a8a8a;
            background: linear-gradient(180deg, #7d7d7d, #696969);
            color: var(--text);
            font-size: 22px;
            font-weight: 700;
            padding: 0 18px;
            cursor: pointer;
            margin-top: 14px;
        }
        .hint {
            color: var(--muted);
            font-size: 16px;
            margin-top: 12px;
        }
        .preview {
            margin-top: 14px;
            padding: 14px;
            border-radius: 16px;
            background: #686868;
            border: 1px solid var(--line);
        }
        .preview-title {
            font-size: 16px;
            font-weight: 700;
            margin-bottom: 10px;
        }
        .preview-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
        }
        .preview-item {
            min-width: 0;
        }
        .preview-pill {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 6px;
            border: 1px solid var(--line);
        }
        .preview-pill.red {
            color: #ffd6d6;
            border-color: #ff5b5b;
            box-shadow: 0 0 8px rgba(255,91,91,0.4);
        }
        .preview-pill.amber {
            color: #ffe7b0;
            border-color: #ffd06a;
            box-shadow: 0 0 8px rgba(255,208,106,0.35);
        }
        .preview-pill.green {
            color: #dff9ea;
            border-color: #35d07f;
            box-shadow: 0 0 8px rgba(53,208,127,0.35);
        }
        .preview-text {
            color: var(--muted);
            font-size: 14px;
            line-height: 1.35;
        }
        @media (max-width: 900px) {
            .form-row {
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 10px;
            }
            label {
                font-size: 14px;
            }
            input[type="number"] {
                min-height: 64px;
                font-size: 24px;
                padding: 10px 12px;
            }
            .preview-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('controller_settings_view') }}">← Back</a></div>
        <div class="panel">
            <h1>Shed {{ shed_no }} {{ title }}</h1>
            <div class="sub">{{ subtitle }}</div>
            <div class="current">Current: {{ current_value }} {{ unit }}</div>
        </div>
        <div class="panel">
            <form method="post" action="{{ save_url }}">
                <div class="form-rows">
                    <div class="form-row">
                        <div>
                            <label for="low_value">{{ low_label }}</label>
                            <input id="low_value" type="number" name="low_value" step="{{ step }}" inputmode="{{ inputmode }}" enterkeyhint="done" value="{{ low_value }}">
                        </div>
                        <div>
                            <label for="high_value">{{ high_label }}</label>
                            <input id="high_value" type="number" name="high_value" step="{{ step }}" inputmode="{{ inputmode }}" enterkeyhint="done" value="{{ high_value }}">
                        </div>
                        <div>
                            <label for="amber_margin">{{ amber_label }}</label>
                            <input id="amber_margin" type="number" name="amber_margin" step="{{ step }}" inputmode="{{ inputmode }}" enterkeyhint="done" value="{{ amber_margin }}">
                        </div>
                    </div>
                </div>
                <button type="submit">{{ button_label }}</button>
            </form>
            <div class="hint">{{ hint }}</div>
            <div class="preview">
                <div class="preview-title">How The Colours Work</div>
                <div class="preview-grid">
                    <div class="preview-item">
                        <div class="preview-pill red">RED</div>
                        <div class="preview-text">Outside the safe range.</div>
                    </div>
                    <div class="preview-item">
                        <div class="preview-pill amber">AMBER</div>
                        <div class="preview-text">Still in range, but within the amber margin near either red limit.</div>
                    </div>
                    <div class="preview-item">
                        <div class="preview-pill green">GREEN</div>
                        <div class="preview-text">Comfortably inside the normal operating range.</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""


WATER_SETTINGS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Water Settings</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root { --bg:#5b5b5b; --panel:rgba(115,115,115,0.96); --line:#8a8a8a; --text:#ececec; --muted:#d2d2d2; }
        body { margin:0; color:var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background:#5b5b5b; }
        .wrap { max-width:860px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color:var(--text); text-decoration:none; font-size:18px; }
        .panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:18px; margin-bottom:16px; }
        h1 { margin:0 0 8px 0; font-size:38px; }
        .sub { color:var(--muted); margin-bottom:16px; font-size:18px; }
        .current { font-size:34px; font-weight:700; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #818181; font-size:18px; }
        .detail:last-child { border-bottom:0; }
        label { display:block; color:var(--muted); font-size:16px; margin-bottom:8px; }
        input[type="number"] { width:100%; min-height:72px; border-radius:16px; border:1px solid var(--line); background:#686868; color:var(--text); font-size:30px; padding:12px 16px; box-sizing:border-box; }
        button { min-height:72px; border-radius:16px; border:1px solid #8a8a8a; background:linear-gradient(180deg, #7d7d7d, #696969); color:var(--text); font-size:22px; font-weight:700; padding:0 18px; cursor:pointer; margin-top:14px; width:100%; }
        .danger { border-color:#7f4b53; background:linear-gradient(180deg, #542e34, #3e2328); }
        .hint { color:var(--muted); font-size:16px; margin-top:12px; }
        .status { font-size:22px; font-weight:700; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('controller_settings_view') }}">← Back</a></div>
        <div class="panel">
            <h1>Shed {{ shed_no }} Water Settings</h1>
            <div class="sub">Adjust the low-flow threshold and calibrate pulses per litre against the shed water meter.</div>
            <div class="current">Current: <span id="waterCurrentValue">{{ current_value }}</span> L/PM</div>
            <div class="detail"><span>Raw pulse L/PM</span><span id="waterCurrentRawValue">{{ current_value_raw }}</span></div>
            <div class="detail"><span>Low flow threshold</span><span>{{ water_low_lpm }} L/PM</span></div>
            <div class="detail"><span>Pulses per litre</span><span id="waterPulsesPerLitre">{{ water_pulses_per_litre }}</span></div>
            <div class="detail"><span>Total flow pulses</span><span id="waterTotalPulses">{{ total_flow_pulses }}</span></div>
        </div>
        <div class="panel">
            <div class="sub">Live pulse activity</div>
            <div class="detail"><span>Latest pulse delta</span><span><span id="livePulseLastDelta">{{ live_pulse_last_delta }}</span> in <span id="livePulseLastSeconds">{{ live_pulse_last_seconds }}</span></span></div>
            <div class="detail"><span>Pulse delta in smoothing window</span><span><span id="livePulseWindowDelta">{{ live_pulse_window_delta }}</span> in <span id="livePulseWindowSeconds">{{ live_pulse_window_seconds }}</span></span></div>
            <div class="detail"><span>Total pulses seen</span><span id="waterTotalPulsesMirror">{{ total_flow_pulses }}</span></div>
            <div class="hint">The main L/PM number uses a short smoothing window. This section still shows the latest raw pulse movement coming back from the Pico.</div>
        </div>
        <div class="panel">
            <form method="post" action="{{ url_for('save_water_settings') }}">
                <label for="threshold_value">Low flow threshold L/PM</label>
                <input id="threshold_value" type="number" name="threshold_value" step="0.01" inputmode="decimal" enterkeyhint="done" value="{{ water_low_lpm }}">
                <button type="submit">Save Low Flow Threshold</button>
            </form>
            <div class="hint">Green is at or above the threshold. Red is below it or missing.</div>
        </div>
        <div class="panel">
            <form method="post" action="{{ url_for('save_water_pulses_per_litre') }}">
                <label for="manual_pulses_per_litre">Manual pulses per litre</label>
                <input id="manual_pulses_per_litre" type="number" name="pulses_per_litre" step="0.01" inputmode="decimal" enterkeyhint="done" value="{{ water_pulses_per_litre }}">
                <button type="submit">Save Pulses Per Litre</button>
            </form>
            <div class="hint">Use this to set a known starting point before running the 5 minute calibration.</div>
        </div>
        <div class="panel">
            <div class="sub">5 minute calibration</div>
            <div class="detail"><span>Status</span><span id="calibrationStatus" class="status">{{ calibration_status }}</span></div>
            <div class="detail"><span>Pulse count in run</span><span id="calibrationPulseDelta">{{ calibration_pulse_delta }}</span></div>
            <div class="detail"><span>Time remaining</span><span id="calibrationRemaining">{{ calibration_remaining }}</span></div>
            <form id="startCalibrationForm" method="post" action="{{ url_for('start_water_calibration') }}" {% if not calibration_can_start %}style="display:none"{% endif %}>
                <button type="submit">Start 5 Minute Calibration</button>
            </form>
            <form id="cancelCalibrationForm" method="post" action="{{ url_for('cancel_water_calibration') }}" {% if not calibration_active %}style="display:none"{% endif %}>
                <button class="danger" type="submit">Cancel Calibration</button>
            </form>
            <form id="finishCalibrationForm" method="post" action="{{ url_for('finish_water_calibration') }}">
                <label for="meter_litres">Litres shown on physical water meter for this 5 minute run</label>
                <input id="meter_litres" type="number" name="meter_litres" step="0.01" inputmode="decimal" enterkeyhint="done" value="" {% if not calibration_ready %}disabled{% endif %}>
                <button id="finishCalibrationButton" type="submit" {% if not calibration_ready %}disabled{% endif %}>Save New Pulses Per Litre</button>
            </form>
            <div id="calibrationHint" class="hint">
                New pulses per litre = counted pulses divided by the litres from the physical meter.
                {% if not calibration_ready %}Complete the 5 minute calibration first to enable saving.{% endif %}
            </div>
        </div>
    </div>
<script>
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
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        :root { --bg:#5b5b5b; --panel:rgba(115,115,115,0.96); --line:#8a8a8a; --text:#ececec; --muted:#d2d2d2; }
        body { margin:0; color:var(--text); font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; background:#5b5b5b; }
        .wrap { max-width:860px; margin:0 auto; padding:18px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color:var(--text); text-decoration:none; font-size:18px; }
        .panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; padding:18px; margin-bottom:16px; }
        h1 { margin:0 0 8px 0; font-size:38px; }
        .sub { color:var(--muted); margin-bottom:16px; font-size:18px; }
        .current { font-size:34px; font-weight:700; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #818181; font-size:18px; }
        .detail:last-child { border-bottom:0; }
        label { display:block; color:var(--muted); font-size:16px; margin-bottom:8px; }
        input[type="number"] { width:100%; min-height:72px; border-radius:16px; border:1px solid var(--line); background:#686868; color:var(--text); font-size:30px; padding:12px 16px; box-sizing:border-box; }
        button { min-height:72px; border-radius:16px; border:1px solid #8a8a8a; background:linear-gradient(180deg, #7d7d7d, #696969); color:var(--text); font-size:22px; font-weight:700; padding:0 18px; cursor:pointer; margin-top:14px; width:100%; }
        .hint { color:var(--muted); font-size:16px; margin-top:12px; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('controller_settings_view') }}">← Back</a></div>
        <div class="panel">
            <h1>Shed {{ shed_no }} Feed Settings</h1>
            <div class="sub">Low-feed warning plus feed bin calibration using tare, bin capacity, and a known weight.</div>
            <div class="current">Current: {{ current_feed_kg }} KG</div>
            <div class="detail"><span>Current raw feed units</span><span>{{ current_feed_raw }}</span></div>
            <div class="detail"><span>Low feed threshold</span><span>{{ feed_low_kg }} KG</span></div>
            <div class="detail"><span>Feed bin capacity</span><span>{{ feed_capacity_kg }} KG</span></div>
            <div class="detail"><span>Tare raw</span><span>{{ feed_tare_raw }}</span></div>
            <div class="detail"><span>KG per raw unit</span><span>{{ feed_kg_per_raw_unit }}</span></div>
        </div>
        <div class="panel">
            <form method="post" action="{{ url_for('save_feed_settings') }}">
                <label for="threshold_value">Low feed threshold KG</label>
                <input id="threshold_value" type="number" name="threshold_value" step="1" inputmode="numeric" enterkeyhint="done" value="{{ feed_low_kg }}">
                <button type="submit">Save Low Feed Threshold</button>
            </form>
        </div>
        <div class="panel">
            <form method="post" action="{{ url_for('save_feed_capacity') }}">
                <label for="feed_capacity_kg">Feed bin capacity KG</label>
                <input id="feed_capacity_kg" type="number" name="feed_capacity_kg" step="1" inputmode="numeric" enterkeyhint="done" value="{{ feed_capacity_kg }}">
                <button type="submit">Save Feed Bin Capacity</button>
            </form>
            <div class="hint">Set this to the full usable weight of feed in the bin.</div>
        </div>
        <div class="panel">
            <div class="sub">Tare</div>
            <form method="post" action="{{ url_for('set_feed_tare') }}">
                <button type="submit" {% if not feed_raw_available %}disabled{% endif %}>Set Tare From Current Empty Bin Reading</button>
            </form>
            <div class="hint">Empty the bin, then press this to store the current raw reading as tare.</div>
        </div>
        <div class="panel">
            <div class="sub">Known Weight Calibration</div>
            <form method="post" action="{{ url_for('save_feed_known_weight') }}">
                <label for="known_weight_kg">Known weight placed in bin KG</label>
                <input id="known_weight_kg" type="number" name="known_weight_kg" step="0.1" inputmode="decimal" enterkeyhint="done" value="">
                <button type="submit" {% if not feed_calibration_ready %}disabled{% endif %}>Calibrate From Current Raw Reading</button>
            </form>
            <div class="hint">
                Put a known weight into the bin after tare has been set.
                {% if not feed_calibration_ready %}A live raw feed reading and tare value are required before calibration can be saved.{% endif %}
            </div>
        </div>
    </div>
</body>
</html>
"""


ALLOCATION_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Allocation</title>
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
        .allocation-list {
            display: grid;
            gap: 12px;
        }
        .allocation-card {
            padding: 14px;
            border-radius: 16px;
            background: var(--panel-2);
            border: 1px solid #818181;
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
            grid-template-columns: minmax(140px, 1.15fr) repeat(4, minmax(92px, 0.88fr));
            gap: 8px;
            align-items: stretch;
        }
        .allocation-form > * {
            min-width: 0;
        }
        input[type="number"] {
            width: 100%;
            min-height: 64px;
            border-radius: 16px;
            border: 1px solid var(--line);
            background: #686868;
            color: var(--text);
            font-size: 28px;
            padding: 10px 14px;
            box-sizing: border-box;
        }
        button {
            min-height: 64px;
            width: 100%;
            border-radius: 16px;
            border: 1px solid #8a8a8a;
            background: linear-gradient(180deg, #7d7d7d, #696969);
            color: var(--text);
            font-size: 19px;
            font-weight: 700;
            padding: 0 12px;
            cursor: pointer;
            white-space: nowrap;
            box-sizing: border-box;
        }
        .secondary {
            border-color: #8f8f8f;
            background: linear-gradient(180deg, #7a7a7a, #656565);
        }
        button:disabled {
            opacity: 0.45;
            cursor: default;
        }
        .danger {
            border-color: #7f4b53;
            background: linear-gradient(180deg, #542e34, #3e2328);
        }
        @media (max-width: 700px) {
            .allocation-form {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('index') }}">← Back</a></div>
        <div class="panel">
            <h1>Shed {{ shed_no }} Allocation</h1>
            <div class="sub">Birds physically in this shed, grouped by their destination shed.</div>
            <div class="allocation-list">
                {% for row in allocation_rows %}
                <div class="allocation-card">
                    <div class="allocation-top">
                        <div>
                            <div class="allocation-title">For Shed {{ row.dest_shed }}</div>
                            <div class="allocation-meta">Started {{ row.started_at }} • Crop {{ row.crop_code }}</div>
                        </div>
                        <div class="allocation-meta">{{ "Active" if row.crop_active == 1 else "Not active" }}</div>
                    </div>
                    <form class="allocation-form" method="post" action="{{ url_for('save_entry_for_dest', dest_shed=row.dest_shed) }}">
                        <input type="hidden" name="return_to" value="allocation">
                        <input type="number" name="bird_count" min="0" step="1" inputmode="numeric" enterkeyhint="done" value="{{ '' if row.bird_count == 0 else row.bird_count }}">
                        <button type="submit">Save</button>
                        <button formaction="{{ url_for('start_entry_for_dest', dest_shed=row.dest_shed) }}" type="submit">Start</button>
                        {% if row.can_move %}
                        <button class="secondary" formaction="{{ url_for('move_entry_for_dest', dest_shed=row.dest_shed) }}" type="submit" onclick="return confirm('Move birds from Shed {{ shed_no }} to Shed {{ row.dest_shed }}?');">Move</button>
                        {% else %}
                        <button class="secondary" type="button" disabled>Move</button>
                        {% endif %}
                        <button class="danger" formaction="{{ url_for('end_entry_for_dest', dest_shed=row.dest_shed) }}" type="submit">End</button>
                    </form>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
</body>
</html>
"""


MORTALITY_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Shed {{ shed_no }} Mortality</title>
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
        .status {
            margin-bottom: 14px;
            padding: 10px 12px;
            border-radius: 12px;
            background: var(--panel);
            border: 1px solid var(--line);
        }
        .status.ok {
            border-color: #41c87d;
            color: #e4ffed;
        }
        .status.err {
            border-color: #c65460;
            color: #ffdbe1;
        }
        .grid {
            display: grid;
            grid-template-columns: 0.92fr 1.08fr;
            gap: 14px;
        }
        .card {
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
        .card h2 {
            margin: 0 0 14px 0;
            font-size: 26px;
        }
        label {
            display: block;
            color: var(--muted);
            margin-bottom: 6px;
            font-size: 15px;
        }
        input[type="number"], input[type="text"], select {
            width: 100%;
            box-sizing: border-box;
            min-height: 58px;
            border-radius: 14px;
            border: 1px solid var(--line);
            background: var(--panel-2);
            color: var(--text);
            font-size: 20px;
            padding: 12px 14px;
            margin-bottom: 12px;
        }
        button {
            min-height: 58px;
            width: 100%;
            border-radius: 14px;
            border: 1px solid #8a8a8a;
            background: linear-gradient(180deg, #7d7d7d, #696969);
            color: var(--text);
            font-size: 20px;
            font-weight: 700;
            padding: 0 18px;
            cursor: pointer;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 15px;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 10px 8px;
            text-align: left;
            vertical-align: middle;
        }
        th {
            color: var(--muted);
        }
        .empty {
            color: var(--muted);
        }
        @media (max-width: 900px) {
            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar"><a href="{{ url_for('index') }}">← Back</a></div>
        <h1>Shed {{ shed_no }} Mortality</h1>
        <div class="sub">Current crop {{ active_crop_code }}. Record losses against an active entry shed.</div>
        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}
        <div class="grid">
            <div class="card">
                <h2>Add Mortality</h2>
                {% if target_rows %}
                <form method="post" action="{{ url_for('mortality_add_view') }}">
                    <label for="dest_shed">Entry Shed</label>
                    <select id="dest_shed" name="dest_shed">
                        {% for row in target_rows %}
                        <option value="{{ row.dest_shed }}">Shed {{ row.dest_shed }} ({{ row.bird_count }} birds)</option>
                        {% endfor %}
                    </select>
                    <label for="bird_loss">Bird Loss</label>
                    <input id="bird_loss" type="number" name="bird_loss" min="1" step="1" inputmode="numeric" enterkeyhint="done" value="">
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
    return render_template_string(HTML, **ctx)


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


@app.route("/settings/update/apply", methods=["POST"])
def apply_update_view():
    status = check_for_update()
    if not status.get("update_available"):
        return redirect(url_for("controller_settings_view"))

    branch = status.get("branch") or "main"
    remote_commit = status.get("remote_commit") or "--"
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
        return redirect(url_for("controller_settings_view"))

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
            allocation_rows[i]["dest_shed"] != cfg["shed_no"]
            and allocation_rows[i]["crop_active"] == 1
            and int(allocation_rows[i]["bird_count"] or 0) > 0
        )
        i += 1

    return render_template_string(
        ALLOCATION_HTML,
        shed_no=cfg["shed_no"],
        allocation_rows=allocation_rows,
    )


@app.route("/mortality")
def mortality_view():
    maybe_refresh_from_dashboard()
    cfg = load_config()
    payload = fetch_mortality_from_dashboard(cfg["shed_no"])
    state = load_state()
    status_msg = request.args.get("msg", "")
    status_ok = request.args.get("ok", "1") == "1"
    return render_template_string(
        MORTALITY_HTML,
        shed_no=cfg["shed_no"],
        active_crop_id=payload.get("active_crop_id"),
        active_crop_code=fmt_crop_code(payload.get("active_crop_id"), active_crop_epoch_from_entries(state.get("entries", {}), payload.get("active_crop_id"))),
        target_rows=payload.get("target_rows", []),
        history_rows=payload.get("history_rows", []),
        mortality_total=fmt_value(payload.get("mortality_total"), "i"),
        active_birds=fmt_value(payload.get("active_birds"), "i"),
        status_msg=status_msg,
        status_ok=status_ok,
    )


@app.route("/mortality/add", methods=["POST"])
def mortality_add_view():
    cfg = load_config()
    try:
        dest_shed = int(request.form.get("dest_shed", "").strip())
        bird_loss = int(request.form.get("bird_loss", "").strip())
        if dest_shed not in SHED_NUMBERS or bird_loss <= 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("mortality_view", ok=0, msg="Invalid mortality entry"))

    note = str(request.form.get("note", "") or "").strip()
    ok, msg = post_mortality_to_dashboard(cfg["shed_no"], dest_shed, bird_loss, note=note)
    if ok:
        pull_from_dashboard(load_state())
        record_controller_event("mortality_recorded", "Recorded mortality", "Entry Shed %d Loss %d" % (dest_shed, bird_loss), push_to_office=True)
    return redirect(url_for("mortality_view", ok=1 if ok else 0, msg=msg if msg else ("Mortality recorded" if ok else "Mortality failed")))


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
        feed_raw_units=fmt_value(sensors.get("feed_raw_units"), "f2"),
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
        return redirect(url_for("temp_settings_view"))

    if temp_low_c >= temp_high_c:
        return redirect(url_for("temp_settings_view"))
    if temp_amber_margin_c < 0:
        return redirect(url_for("temp_settings_view"))

    cfg["temp_low_c"] = temp_low_c
    cfg["temp_high_c"] = temp_high_c
    cfg["temp_amber_margin_c"] = temp_amber_margin_c
    save_config(cfg)
    return redirect(url_for("temp_settings_view"))


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
        return redirect(url_for("rh_settings_view"))

    if rh_low_pct >= rh_high_pct:
        return redirect(url_for("rh_settings_view"))
    if rh_amber_margin_pct < 0:
        return redirect(url_for("rh_settings_view"))

    cfg["rh_low_pct"] = rh_low_pct
    cfg["rh_high_pct"] = rh_high_pct
    cfg["rh_amber_margin_pct"] = rh_amber_margin_pct
    save_config(cfg)
    return redirect(url_for("rh_settings_view"))


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
        return redirect(url_for("water_settings_view"))
    cfg["water_low_lpm"] = threshold_value
    save_config(cfg)
    return redirect(url_for("water_settings_view"))


@app.route("/settings/water/pulses-per-litre", methods=["POST"])
def save_water_pulses_per_litre():
    cfg = load_config()
    try:
        pulses_per_litre = float(request.form.get("pulses_per_litre", "").strip())
        if pulses_per_litre <= 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("water_settings_view"))
    cfg["water_pulses_per_litre"] = pulses_per_litre
    save_config(cfg)
    return redirect(url_for("water_settings_view"))


@app.route("/settings/water/calibration/start", methods=["POST"])
def start_water_calibration():
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())
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


@app.route("/settings/feed")
def feed_settings_view():
    cfg = load_config()
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())
    feed_raw = sensors.get("feed_raw_units")
    feed_raw_available = feed_raw not in [None, ""]
    feed_calibration_ready = feed_raw_available and cfg.get("feed_tare_raw") not in [None, ""]
    return render_template_string(
        FEED_SETTINGS_HTML,
        shed_no=cfg["shed_no"],
        current_feed_kg=fmt_value(sensors.get("feed_kg"), "f0"),
        current_feed_raw=fmt_value(feed_raw, "f1"),
        feed_low_kg=fmt_value(cfg.get("feed_low_kg", 2000.0), "f0"),
        feed_capacity_kg=fmt_value(cfg.get("feed_capacity_kg", 16000.0), "f0"),
        feed_tare_raw=fmt_value(cfg.get("feed_tare_raw"), "f1"),
        feed_kg_per_raw_unit=fmt_value(cfg.get("feed_kg_per_raw_unit"), "f4"),
        feed_raw_available=feed_raw_available,
        feed_calibration_ready=feed_calibration_ready,
    )


@app.route("/settings/feed/save", methods=["POST"])
def save_feed_settings():
    cfg = load_config()
    try:
        threshold_value = float(request.form.get("threshold_value", "").strip())
    except Exception:
        return redirect(url_for("feed_settings_view"))
    cfg["feed_low_kg"] = threshold_value
    save_config(cfg)
    return redirect(url_for("feed_settings_view"))


@app.route("/settings/feed/capacity/save", methods=["POST"])
def save_feed_capacity():
    cfg = load_config()
    try:
        capacity = float(request.form.get("feed_capacity_kg", "").strip())
        if capacity <= 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("feed_settings_view"))
    cfg["feed_capacity_kg"] = capacity
    save_config(cfg)
    return redirect(url_for("feed_settings_view"))


@app.route("/settings/feed/tare", methods=["POST"])
def set_feed_tare():
    state = load_state()
    sensors = state.get("sensors", default_sensor_state())
    try:
        feed_raw = float(sensors.get("feed_raw_units"))
    except Exception:
        return redirect(url_for("feed_settings_view"))
    cfg = load_config()
    cfg["feed_tare_raw"] = feed_raw
    save_config(cfg)
    return redirect(url_for("feed_settings_view"))


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
        return redirect(url_for("feed_settings_view"))

    try:
        feed_raw = float(sensors.get("feed_raw_units"))
        tare_raw = float(cfg.get("feed_tare_raw"))
    except Exception:
        return redirect(url_for("feed_settings_view"))

    raw_delta = feed_raw - tare_raw
    if raw_delta <= 0:
        return redirect(url_for("feed_settings_view"))

    cfg["feed_kg_per_raw_unit"] = known_weight_kg / raw_delta
    save_config(cfg)

    mutate_state(lambda s: update_feed_from_raw(s.get("sensors", default_sensor_state())))
    return redirect(url_for("feed_settings_view"))


def render_metric_history(metric_key, metric_title, y_axis_title, color, fmt):
    shed_no = load_config()["shed_no"]
    payload = fetch_current_crop_hourly_history(shed_no)
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    crop_id = payload.get("crop_id") if isinstance(payload, dict) else None
    crop_code = payload.get("crop_code") if isinstance(payload, dict) else fmt_crop_code(crop_id)

    view_rows = []
    labels = []
    values = []

    i = 0
    while i < len(rows):
        row = rows[i]
        raw_val = row.get(metric_key)
        labels.append(row.get("label"))
        values.append(raw_val)
        view_rows.append({
            "label": row.get("label"),
            "value": fmt_value(raw_val, fmt),
        })
        i += 1

    return render_template_string(
        HISTORY_HTML,
        shed_no=shed_no,
        crop_id=crop_id,
        crop_code=crop_code,
        metric_title=metric_title,
        y_axis_title=y_axis_title,
        color=color,
        rows=view_rows,
        table_rows=list(reversed(view_rows)),
        labels=labels,
        values=values,
        extra_link_href=url_for("auger_runs_view") if metric_key == "feed" else None,
        extra_link_label="Auger Run Timestamps" if metric_key == "feed" else "",
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
    return render_metric_history("water", "Water History", "Water L", "#4db6ff", "f1")


@app.route("/history/feed")
def feed_history_view():
    return render_metric_history("feed", "Feed History", "Feed KG", "#7be1aa", "f1")


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


def save_entry_for_dest_impl(dest_shed, bird_count):
    if dest_shed not in SHED_NUMBERS:
        return False, "Invalid shed"

    def mutator(state):
        entry = get_entry_for_dest(state, dest_shed)
        if bird_count == 0:
            clear_entry_for_dest(state, dest_shed)
        else:
            entry["bird_count"] = bird_count
            entry["pens"] = []
            entry["updated_ts"] = int(time.time())
            entry["updated_by"] = "controller"
            set_entry_for_dest(state, dest_shed, entry)
        state["entries_updated_ts"] = int(time.time())

    state = mutate_state(mutator)
    record_controller_event("entry_saved", "Saved bird count", "Entry Shed %d = %d" % (dest_shed, bird_count), push_to_office=True)
    return push_to_dashboard(state)


@app.route("/entry/<int:dest_shed>/save", methods=["POST"])
def save_entry_for_dest(dest_shed):
    raw = request.form.get("bird_count", "").strip()
    try:
        bird_count = int(raw)
        if bird_count < 0:
            raise ValueError()
    except Exception:
        return redirect_back_with_status("index", False, "Invalid bird count")

    ok, sync_msg = save_entry_for_dest_impl(dest_shed, bird_count)
    return redirect_back_with_status("index", ok, sync_msg if sync_msg else "Saved")


def start_entry_for_dest_impl(dest_shed, bird_count_override=None):
    if dest_shed not in SHED_NUMBERS:
        return False, "Invalid shed"

    state = load_state()
    if bird_count_override is not None:
        entry = get_entry_for_dest(state, dest_shed)
        entry["bird_count"] = bird_count_override
        entry["pens"] = []
        set_entry_for_dest(state, dest_shed, entry)
    entry = get_entry_for_dest(state, dest_shed)
    if entry["bird_count"] <= 0:
        return False, "Set birds before starting"

    def mutator(state):
        entry = get_entry_for_dest(state, dest_shed)
        if bird_count_override is not None:
            entry["bird_count"] = bird_count_override
            entry["pens"] = []
        entry["crop_active"] = 1
        if entry["placement_epoch"] is None:
            entry["placement_epoch"] = int(time.time())
        entry["updated_ts"] = int(time.time())
        entry["updated_by"] = "controller"
        set_entry_for_dest(state, dest_shed, entry)
        state["entries_updated_ts"] = int(time.time())

    state = mutate_state(mutator)
    record_controller_event("entry_started", "Started entry", "Entry Shed %d" % dest_shed, push_to_office=True)
    return push_to_dashboard(state, pull_back=False)


@app.route("/entry/<int:dest_shed>/start", methods=["POST"])
def start_entry_for_dest(dest_shed):
    bird_count_override = None
    raw = str(request.form.get("bird_count", "") or "").strip()
    if raw != "":
        try:
            bird_count_override = int(raw)
            if bird_count_override < 0:
                raise ValueError()
        except Exception:
            return redirect_back_with_status("index", False, "Invalid bird count")
    ok, sync_msg = start_entry_for_dest_impl(dest_shed, bird_count_override=bird_count_override)
    return redirect_back_with_status("index", ok, sync_msg if sync_msg else "Started")


def move_entry_for_dest_impl(dest_shed):
    cfg = load_config()
    if dest_shed not in SHED_NUMBERS:
        return False, "Invalid shed"
    if dest_shed == cfg["shed_no"]:
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
    record_controller_event("entry_moved", "Moved entry via office", "Entry Shed %d" % dest_shed, push_to_office=True)
    return True, "Entry moved to Shed %d" % dest_shed


@app.route("/entry/<int:dest_shed>/move", methods=["POST"])
def move_entry_for_dest(dest_shed):
    ok, sync_msg = move_entry_for_dest_impl(dest_shed)
    return redirect_back_with_status("allocation_view", ok, sync_msg if sync_msg else "Moved")


def end_entry_for_dest_impl(dest_shed):
    if dest_shed not in SHED_NUMBERS:
        return False, "Invalid shed"

    def mutator(state):
        clear_entry_for_dest(state, dest_shed)
        state["last_sync_ts"] = int(time.time())
        state["entries_updated_ts"] = int(time.time())

    state = mutate_state(mutator)
    record_controller_event("entry_ended", "Ended entry", "Entry Shed %d" % dest_shed, push_to_office=True)
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
    app.run(host="0.0.0.0", port=cfg["listen_port"])
