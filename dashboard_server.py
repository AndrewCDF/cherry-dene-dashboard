from flask import Flask, render_template_string, abort, url_for, request, redirect, jsonify, Response, send_file
import json
import os
import re
import socket
import smtplib
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta
from email.message import EmailMessage
from markupsafe import Markup, escape
from xml.sax.saxutils import escape as xml_escape

app = Flask(__name__)
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
CDF_APP_ICON_PATH = os.path.join(
    APP_ROOT, "ios", "CherryDeneMobile", "Assets.xcassets", "AppIcon.appiconset", "AppIcon-1024.png"
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
FAVICON_HEAD_HTML = (
    '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
    '<link rel="manifest" href="/manifest.webmanifest">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-title" content="CDF">'
    '<meta name="theme-color" content="#5b5b5b">'
)


def render_page_nav():
    previous_href = request.referrer or url_for("dashboard")
    dashboard_href = url_for("dashboard")
    return Markup(
        (
            '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">'
            '<a href="{previous_href}" onclick="if (window.history.length > 1) {{ window.history.back(); return false; }}" '
            'style="display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:10px 16px;'
            'border-radius:999px;border:1px solid #8a8a8a;background:#686868;color:#ececec;text-decoration:none;'
            'font-weight:700;line-height:1;box-shadow:inset 0 1px 0 rgba(255,255,255,0.06);">'
            '← Previous Page</a>'
            '<a href="{dashboard_href}" '
            'style="display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:10px 16px;'
            'border-radius:999px;border:1px solid #8a8a8a;background:#686868;color:#ececec;text-decoration:none;'
            'font-weight:700;line-height:1;box-shadow:inset 0 1px 0 rgba(255,255,255,0.06);">'
            'Return To Dashboard</a>'
            "</div>"
        ).format(
            previous_href=escape(previous_href),
            dashboard_href=escape(dashboard_href),
        )
    )


app.jinja_env.globals["render_page_nav"] = render_page_nav


@app.route("/favicon.ico")
@app.route("/favicon.svg")
def favicon_view():
    return Response(CDF_FAVICON_SVG, mimetype="image/svg+xml")


@app.route("/apple-touch-icon.png")
@app.route("/apple-touch-icon-precomposed.png")
def apple_touch_icon_view():
    return send_file(CDF_APP_ICON_PATH, mimetype="image/png", max_age=300)


@app.route("/manifest.webmanifest")
def web_manifest_view():
    return jsonify({
        "name": "Cherry Dene Dashboard",
        "short_name": "CDF",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#5b5b5b",
        "theme_color": "#5b5b5b",
        "icons": [
            {
                "src": "/apple-touch-icon.png",
                "sizes": "1024x1024",
                "type": "image/png",
            }
        ],
    })


SERVICE_WORKER_JS = """self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (err) {
    payload = { title: 'Cherry Dene Dashboard', body: event.data ? event.data.text() : '' };
  }
  const title = payload.title || 'Cherry Dene Dashboard';
  const options = {
    body: payload.body || '',
    icon: payload.icon || '/apple-touch-icon.png',
    badge: payload.badge || '/apple-touch-icon.png',
    tag: payload.tag || 'cdf-notification',
    data: payload.data || {},
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(url);
      }
    })
  );
});
"""


@app.route("/service-worker.js")
def service_worker_view():
    return Response(
        SERVICE_WORKER_JS,
        mimetype="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


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
            if "<head>" in body and 'rel="icon"' not in body:
                body = body.replace('<head>', '<head>' + FAVICON_HEAD_HTML, 1)
                response.set_data(body)
                response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception:
        pass
    return response

DATA_DIR = os.path.join(APP_ROOT, "data")
SHED_NUMBERS = [1, 2, 3, 4, 6, 7, 8, 9, 10]
OFFICE_BACKUP_KEEP_COUNT = 6
OFFICE_AUTO_BACKUP_INTERVAL_SECONDS = 3600
OFFICE_AUTO_BACKUP_CHECK_SECONDS = 60
FEED_RECORDING_MIN_DROP_KG = 1.0
FEED_RECORDING_REFILL_RISE_KG = 8.0
FEED_RECORDING_NOISE_FACTOR = 2.0
FEED_REFILL_SETTLING_SECONDS = 5 * 60
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
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=parent)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def write_bytes_file_atomic(path, payload):
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=parent)
    with os.fdopen(fd, "wb") as f:
        f.write(payload)
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


def write_named_json_lines_atomic(filename, payloads):
    path = os.path.join(DATA_DIR, filename)
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=parent)
    with os.fdopen(fd, "w") as f:
        i = 0
        while i < len(payloads):
            f.write(json.dumps(payloads[i]))
            f.write("\n")
            i += 1
    os.replace(tmp, path)


def backups_dir():
    cfg = read_json_file(os.path.join(DATA_DIR, "office_config.json"), {})
    if isinstance(cfg, dict):
        backup_dir = str(cfg.get("backup_dir", "") or "").strip()
        if backup_dir:
            if os.path.isabs(backup_dir):
                return backup_dir
            return os.path.join(office_repo_dir(), backup_dir)
    return os.path.join(DATA_DIR, "backups")


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
        if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172.16.") or ip.startswith("172.17.") or ip.startswith("172.18.") or ip.startswith("172.19.") or ip.startswith("172.2"):
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


def fmt_datetime_local_value(epoch_ts):
    if epoch_ts in [None, ""]:
        return datetime.now().strftime("%Y-%m-%dT%H:%M")
    try:
        return datetime.fromtimestamp(int(epoch_ts)).strftime("%Y-%m-%dT%H:%M")
    except Exception:
        return datetime.now().strftime("%Y-%m-%dT%H:%M")


def parse_datetime_local_value(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.strptime(text, "%Y-%m-%dT%H:%M")
    except Exception:
        return None
    return int(time.mktime(dt.timetuple()))


def load_office_config():
    data = read_json_file(os.path.join(DATA_DIR, "office_config.json"), {})
    return data if isinstance(data, dict) else {}


def save_office_config(data):
    write_json_file_atomic(os.path.join(DATA_DIR, "office_config.json"), data if isinstance(data, dict) else {})


def parse_email_recipients(value):
    if isinstance(value, list):
        parts = value
    else:
        parts = re.split(r"[,;\n]+", str(value or ""))
    out = []
    i = 0
    while i < len(parts):
        item = str(parts[i] or "").strip()
        if item and item not in out:
            out.append(item)
        i += 1
    return out


def office_email_settings_form_state():
    cfg = load_office_config()

    def text_value(key, default=""):
        value = cfg.get(key, default)
        if value in [None]:
            value = default
        return str(value)

    def bool_value(key, default=False):
        value = cfg.get(key)
        if value in [None, ""]:
            return bool(default)
        return str(value).strip().lower() not in ["0", "false", "no", "off"]

    return {
        "report_email_enabled": bool_value("report_email_enabled", True),
        "report_recipients": parse_email_recipients(cfg.get("report_email_to", "")),
        "report_email_from": text_value("report_email_from", ""),
        "report_smtp_host": text_value("report_smtp_host", ""),
        "report_smtp_port": text_value("report_smtp_port", "587"),
        "report_smtp_username": text_value("report_smtp_username", ""),
        "report_smtp_password": text_value("report_smtp_password", ""),
        "report_smtp_use_tls": bool_value("report_smtp_use_tls", True),
        "report_smtp_use_ssl": bool_value("report_smtp_use_ssl", False),
    }


def save_office_email_settings_from_form(form):
    cfg = load_office_config()

    text_keys = [
        "report_email_from",
        "report_smtp_host",
        "report_smtp_port",
        "report_smtp_username",
        "report_smtp_password",
    ]
    bool_keys = [
        "report_email_enabled",
        "report_smtp_use_tls",
        "report_smtp_use_ssl",
    ]

    i = 0
    while i < len(text_keys):
        key = text_keys[i]
        cfg[key] = str(form.get(key, "") or "").strip()
        i += 1

    i = 0
    while i < len(bool_keys):
        key = bool_keys[i]
        cfg[key] = "1" if str(form.get(key, "") or "").strip().lower() in ["1", "true", "yes", "on"] else "0"
        i += 1

    if not cfg.get("report_smtp_port"):
        cfg["report_smtp_port"] = "587"

    save_office_config(cfg)


def add_office_email_recipient(value):
    recipient = str(value or "").strip()
    if not recipient:
        raise ValueError("Recipient email is required")
    if "@" not in recipient or " " in recipient:
        raise ValueError("Enter a valid recipient email address")
    cfg = load_office_config()
    recipients = parse_email_recipients(cfg.get("report_email_to", ""))
    if recipient not in recipients:
        recipients.append(recipient)
    cfg["report_email_to"] = "\n".join(recipients)
    save_office_config(cfg)


def remove_office_email_recipient(value):
    recipient = str(value or "").strip()
    cfg = load_office_config()
    recipients = parse_email_recipients(cfg.get("report_email_to", ""))
    recipients = [item for item in recipients if item != recipient]
    cfg["report_email_to"] = "\n".join(recipients)
    save_office_config(cfg)


DEFAULT_ENVIRONMENT_LIMITS = {
    "temp_low_c": 18.0,
    "temp_high_c": 24.0,
    "temp_amber_margin_c": 1.0,
    "rh_low_pct": 40.0,
    "rh_high_pct": 80.0,
    "rh_amber_margin_pct": 5.0,
    "water_low_lpm": 0.1,
    "water_amber_buffer_lpm": 0.05,
    "feed_low_kg": 2000.0,
    "feed_amber_buffer_kg": 500.0,
}


def parse_env_limit_value(value, default):
    try:
        return float(value)
    except Exception:
        return float(default)


def clean_environment_limits(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key, default in DEFAULT_ENVIRONMENT_LIMITS.items():
        out[key] = parse_env_limit_value(raw.get(key), default)
    if out["temp_low_c"] >= out["temp_high_c"]:
        out["temp_low_c"] = DEFAULT_ENVIRONMENT_LIMITS["temp_low_c"]
        out["temp_high_c"] = DEFAULT_ENVIRONMENT_LIMITS["temp_high_c"]
    if out["temp_amber_margin_c"] < 0:
        out["temp_amber_margin_c"] = DEFAULT_ENVIRONMENT_LIMITS["temp_amber_margin_c"]
    if out["rh_low_pct"] >= out["rh_high_pct"]:
        out["rh_low_pct"] = DEFAULT_ENVIRONMENT_LIMITS["rh_low_pct"]
        out["rh_high_pct"] = DEFAULT_ENVIRONMENT_LIMITS["rh_high_pct"]
    if out["rh_amber_margin_pct"] < 0:
        out["rh_amber_margin_pct"] = DEFAULT_ENVIRONMENT_LIMITS["rh_amber_margin_pct"]
    if out["water_low_lpm"] < 0:
        out["water_low_lpm"] = DEFAULT_ENVIRONMENT_LIMITS["water_low_lpm"]
    if out["water_amber_buffer_lpm"] < 0:
        out["water_amber_buffer_lpm"] = DEFAULT_ENVIRONMENT_LIMITS["water_amber_buffer_lpm"]
    if out["feed_low_kg"] < 0:
        out["feed_low_kg"] = DEFAULT_ENVIRONMENT_LIMITS["feed_low_kg"]
    if out["feed_amber_buffer_kg"] < 0:
        out["feed_amber_buffer_kg"] = DEFAULT_ENVIRONMENT_LIMITS["feed_amber_buffer_kg"]
    return out


def controller_environment_limits(meta):
    meta = meta if isinstance(meta, dict) else {}
    return clean_environment_limits({
        "temp_low_c": meta.get("temp_low_c"),
        "temp_high_c": meta.get("temp_high_c"),
        "temp_amber_margin_c": meta.get("temp_amber_margin_c"),
        "rh_low_pct": meta.get("rh_low_pct"),
        "rh_high_pct": meta.get("rh_high_pct"),
        "rh_amber_margin_pct": meta.get("rh_amber_margin_pct"),
        "water_low_lpm": meta.get("water_low_lpm"),
        "water_amber_buffer_lpm": meta.get("water_amber_buffer_lpm"),
        "feed_low_kg": meta.get("feed_low_kg"),
        "feed_amber_buffer_kg": meta.get("feed_amber_buffer_kg"),
    })


def office_environment_limits_map():
    cfg = load_office_config()
    raw = cfg.get("shed_environment_limits", {})
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        try:
            shed_no = int(key)
        except Exception:
            continue
        out[str(shed_no)] = clean_environment_limits(value)
    return out


def environment_limits_for_shed(shed_no, office_limits_map=None, controller_meta=None):
    office_limits_map = office_limits_map if isinstance(office_limits_map, dict) else office_environment_limits_map()
    shed_key = str(int(shed_no))
    if shed_key in office_limits_map:
        return clean_environment_limits(office_limits_map.get(shed_key))
    return controller_environment_limits(controller_meta)


def office_environment_settings_row_for_shed(shed_no, controller_meta=None):
    if shed_no not in SHED_NUMBERS:
        return None
    controller_meta = controller_meta if isinstance(controller_meta, dict) else load_controller_meta()
    meta = controller_meta.get(str(int(shed_no)), {}) if isinstance(controller_meta, dict) else {}
    limits = environment_limits_for_shed(shed_no, office_environment_limits_map(), meta)
    return {
        "shed_no": shed_no,
        "temp_low_c": fmt_value(limits.get("temp_low_c"), "f1"),
        "temp_high_c": fmt_value(limits.get("temp_high_c"), "f1"),
        "temp_amber_margin_c": fmt_value(limits.get("temp_amber_margin_c"), "f1"),
        "rh_low_pct": fmt_value(limits.get("rh_low_pct"), "f0"),
        "rh_high_pct": fmt_value(limits.get("rh_high_pct"), "f0"),
        "rh_amber_margin_pct": fmt_value(limits.get("rh_amber_margin_pct"), "f0"),
        "water_low_lpm": fmt_value(limits.get("water_low_lpm"), "f2"),
        "water_amber_buffer_lpm": fmt_value(limits.get("water_amber_buffer_lpm"), "f2"),
        "feed_low_kg": fmt_value(limits.get("feed_low_kg"), "f0"),
        "feed_amber_buffer_kg": fmt_value(limits.get("feed_amber_buffer_kg"), "f0"),
    }


def save_office_environment_settings_for_shed(shed_no, form):
    if shed_no not in SHED_NUMBERS:
        raise ValueError("Invalid shed number")
    cfg = load_office_config()
    raw = cfg.get("shed_environment_limits", {})
    if not isinstance(raw, dict):
        raw = {}
    raw[str(shed_no)] = clean_environment_limits({
        "temp_low_c": form.get("temp_low_c", DEFAULT_ENVIRONMENT_LIMITS["temp_low_c"]),
        "temp_high_c": form.get("temp_high_c", DEFAULT_ENVIRONMENT_LIMITS["temp_high_c"]),
        "temp_amber_margin_c": form.get("temp_amber_margin_c", DEFAULT_ENVIRONMENT_LIMITS["temp_amber_margin_c"]),
        "rh_low_pct": form.get("rh_low_pct", DEFAULT_ENVIRONMENT_LIMITS["rh_low_pct"]),
        "rh_high_pct": form.get("rh_high_pct", DEFAULT_ENVIRONMENT_LIMITS["rh_high_pct"]),
        "rh_amber_margin_pct": form.get("rh_amber_margin_pct", DEFAULT_ENVIRONMENT_LIMITS["rh_amber_margin_pct"]),
        "water_low_lpm": form.get("water_low_lpm", DEFAULT_ENVIRONMENT_LIMITS["water_low_lpm"]),
        "water_amber_buffer_lpm": form.get("water_amber_buffer_lpm", DEFAULT_ENVIRONMENT_LIMITS["water_amber_buffer_lpm"]),
        "feed_low_kg": form.get("feed_low_kg", DEFAULT_ENVIRONMENT_LIMITS["feed_low_kg"]),
        "feed_amber_buffer_kg": form.get("feed_amber_buffer_kg", DEFAULT_ENVIRONMENT_LIMITS["feed_amber_buffer_kg"]),
    })
    cfg["shed_environment_limits"] = raw
    save_office_config(cfg)


def range_glow_class(value, low, high, warn_margin, prefix="env"):
    try:
        value_f = float(value)
    except Exception:
        return "%s-red" % prefix
    if value_f < float(low) or value_f > float(high):
        return "%s-red" % prefix
    if abs(value_f - float(low)) <= float(warn_margin) or abs(value_f - float(high)) <= float(warn_margin):
        return "%s-warn" % prefix
    return "%s-green" % prefix


def low_threshold_glow_class(value, low, amber_buffer, prefix):
    try:
        value_f = float(value)
    except Exception:
        return "%s-red" % prefix
    low_f = float(low)
    amber_top = low_f + max(0.0, float(amber_buffer))
    if value_f < low_f:
        return "%s-red" % prefix
    if value_f <= amber_top:
        return "%s-warn" % prefix
    return "%s-green" % prefix


def crop_reports_root():
    path = os.path.join(DATA_DIR, "crop_reports")
    os.makedirs(path, exist_ok=True)
    return path


def crop_report_status_path():
    return os.path.join(DATA_DIR, "crop_report_status.json")


def load_crop_report_status():
    data = read_json_file(crop_report_status_path(), {})
    return data if isinstance(data, dict) else {}


def save_crop_report_status(data):
    write_json_file_atomic(crop_report_status_path(), data if isinstance(data, dict) else {})


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


def controller_backup_hour_bucket(ts=None):
    try:
        value = int(time.time() if ts is None else ts)
    except Exception:
        value = int(time.time())
    return datetime.fromtimestamp(value).strftime("%Y%m%d%H")


def seconds_until_next_hour(ts=None):
    try:
        value = float(time.time() if ts is None else ts)
    except Exception:
        value = float(time.time())
    remainder = value % 3600.0
    if remainder <= 0:
        return 3600.0
    return max(1.0, 3600.0 - remainder)


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


def maybe_collect_controller_backups(force=False):
    status_map = load_controller_backup_status()
    urls = controller_backup_url_map()
    current_hour_bucket = controller_backup_hour_bucket()
    for controller_key, rec in urls.items():
        last_ts = None
        try:
            last_ts = int(status_map.get(controller_key, {}).get("last_collected_ts"))
        except Exception:
            last_ts = None
        if (not force) and last_ts is not None and controller_backup_hour_bucket(last_ts) == current_hour_bucket:
            continue
        collect_controller_backup(controller_key, rec.get("label", controller_key), rec.get("url", ""), str(rec.get("token", "") or ""))


def controller_backup_worker():
    while True:
        try:
            maybe_collect_controller_backups()
        except Exception as exc:
            log_event("office", "controller_backup_failed", "Automatic controller backup collection failed", detail=str(exc))
        time.sleep(seconds_until_next_hour())


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
        "local_commit_full": local_out or "--",
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

    remote_full = remote_out or "--"
    local_full = local.get("local_commit_full", "--")
    status["remote_commit"] = remote_full[:7] if remote_full and remote_full != "--" else "--"
    status["update_available"] = bool(remote_full and local_full and remote_full != local_full)
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


def format_duration_compact(seconds):
    try:
        total = max(0, int(seconds))
    except Exception:
        return "--"
    if total < 60:
        return "%ss" % total
    if total < 3600:
        return "%dm %02ds" % (total // 60, total % 60)
    return "%dh %02dm" % (total // 3600, (total % 3600) // 60)


def format_clock_compact(ts_value):
    try:
        return datetime.fromtimestamp(int(ts_value)).strftime("%H:%M")
    except Exception:
        return "--"


def format_ts_label(ts_value):
    if ts_value in [None, ""]:
        return "--"
    try:
        return datetime.fromtimestamp(int(ts_value)).strftime("%d %b %Y %H:%M:%S")
    except Exception:
        return "--"


def parse_auger_ts(value):
    if value in [None, "", "--"]:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    for fmt in ["%d %b %Y %H:%M:%S", "%d %b %Y %H:%M", "%Y-%m-%d %H:%M:%S"]:
        try:
            return int(datetime.strptime(text, fmt).timestamp())
        except Exception:
            pass
    return None


def collate_auger_run_records(records, short_max_seconds=15, gap_max_seconds=30):
    if not isinstance(records, list):
        return []
    parsed = []
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if not isinstance(rec, dict):
            continue
        started_ts = rec.get("started_ts")
        stopped_ts = rec.get("stopped_ts") or rec.get("ts")
        if started_ts in [None, ""]:
            started_ts = parse_auger_ts(rec.get("started_at"))
        if stopped_ts in [None, ""]:
            stopped_ts = parse_auger_ts(rec.get("stopped_at"))
        try:
            started_ts = int(started_ts)
            stopped_ts = int(stopped_ts)
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


def format_auger_run_rows(rows, limit=200):
    if not isinstance(rows, list):
        return []
    rows = collate_auger_run_records(rows)
    if limit and limit > 0:
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
            "started_at": format_ts_label(started_ts),
            "stopped_at": format_ts_label(stopped_ts),
            "duration": format_duration_compact(duration_s),
            "run_count": run_count,
            "run_count_label": "%d" % run_count,
        })
    return out


def auger_runs_from_latest_controller_backup(shed_no, limit=200):
    if shed_no not in SHED_NUMBERS:
        return []
    files = list_controller_backup_files("shed_%d" % shed_no)
    if not files:
        return []
    rows = zip_ndjson_member(files[0], "auger_runs.ndjson")
    return format_auger_run_rows(rows, limit=limit)


def fetch_live_auger_runs_from_controller(shed_no, limit=200):
    if shed_no not in SHED_NUMBERS:
        return {"ok": False, "rows": [], "source": "invalid"}
    rec = controller_config_record(str(shed_no))
    sync_url = str(rec.get("sync_url", "") or "").strip().rstrip("/")
    if not sync_url:
        return {"ok": False, "rows": [], "source": "missing_url"}

    headers = {}
    token = str(rec.get("sync_token", "") or "").strip()
    if token:
        headers["X-Controller-Token"] = token
    url = "%s/api/history/feed/augers?limit=%d" % (sync_url, max(1, min(int(limit or 200), 1000)))

    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if not (200 <= int(resp.status) < 300):
                raise RuntimeError("HTTP %d" % int(resp.status))
            payload = json.loads(resp.read().decode("utf-8"))
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        generated_at = payload.get("generated_at") if isinstance(payload, dict) else None
        generated_at_label = ""
        if generated_at not in [None, ""]:
            try:
                generated_at_label = datetime.fromtimestamp(int(generated_at)).strftime("%d %b %Y %H:%M:%S")
            except Exception:
                generated_at_label = ""
        return {
            "ok": True,
            "rows": format_auger_run_rows(rows, limit=limit),
            "source": "live",
            "source_label": "Live controller feed",
            "updated_at": generated_at_label,
        }
    except Exception:
        return {"ok": False, "rows": [], "source": "live_failed"}


def latest_controller_backup_info(controller_key):
    files = list_controller_backup_files(controller_key)
    if not files:
        return {"name": "", "collected_at": None}
    path = files[0]
    try:
        collected_at = int(os.path.getmtime(path))
    except Exception:
        collected_at = None
    return {
        "name": os.path.basename(path),
        "collected_at": collected_at,
    }


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


IMPORTANT_NOTIFICATION_EVENT_TYPES = {
    "crop_report_ready",
    "crop_report_emailed",
    "crop_report_failed",
    "backup_failed",
    "controller_backup_failed",
    "office_updated",
}


def notification_url_for_event(row):
    if not isinstance(row, dict):
        return "/"
    event_type = str(row.get("event_type") or "").strip()
    if event_type.startswith("crop_report_"):
        return "/crop-reports"
    if event_type in ["backup_failed", "controller_backup_failed", "office_updated"]:
        return "/settings"
    shed_no = row.get("shed_no")
    try:
        if shed_no not in [None, ""]:
            return "/shed/%d" % int(shed_no)
    except Exception:
        pass
    return "/"


def build_notification_events_since(since_ts):
    rows = read_all_json_lines("events.ndjson")
    out = []
    i = 0
    while i < len(rows):
        row = rows[i]
        try:
            ts = int(row.get("ts") or 0)
        except Exception:
            ts = 0
        event_type = str(row.get("event_type") or "").strip()
        if ts > int(since_ts or 0) and event_type in IMPORTANT_NOTIFICATION_EVENT_TYPES:
            out.append({
                "id": "evt:%s:%s:%s" % (ts, event_type, str(row.get("detail") or row.get("message") or "").strip()),
                "kind": "event",
                "title": str(row.get("message") or "Cherry Dene Dashboard"),
                "body": str(row.get("detail") or row.get("source") or "").strip(),
                "url": notification_url_for_event(row),
                "ts": ts,
            })
        i += 1
    out.sort(key=lambda r: int(r.get("ts") or 0))
    return out


def build_active_alarm_notifications():
    alarms = []
    alarms_map = active_alarms_by_shed()
    for shed_name, rows in alarms_map.items():
        if not isinstance(rows, list):
            continue
        i = 0
        while i < len(rows):
            row = rows[i]
            if isinstance(row, dict):
                shed_label = str(shed_name or "Shed").strip()
                alarm_key = str(row.get("alarm_key") or "alarm").strip()
                message = str(row.get("message") or alarm_key).strip()
                alarms.append({
                    "id": "alarm:%s:%s:%s" % (shed_label, alarm_key, message),
                    "kind": "alarm",
                    "title": "%s Alarm" % shed_label,
                    "body": message,
                    "url": "/shed/%d" % shed_number_from_name(shed_label) if shed_number_from_name(shed_label) in SHED_NUMBERS else "/",
                })
            i += 1

    borehole_rows = active_borehole_alarms()
    i = 0
    while i < len(borehole_rows):
        row = borehole_rows[i]
        if isinstance(row, dict):
            alarm_key = str(row.get("alarm_key") or "alarm").strip()
            message = str(row.get("message") or alarm_key).strip()
            alarms.append({
                "id": "alarm:borehole:%s:%s" % (alarm_key, message),
                "kind": "alarm",
                "title": "Bore Hole Alarm",
                "body": message,
                "url": "/borehole",
            })
        i += 1
    return alarms


def clean_controller_meta(meta):
    if not isinstance(meta, dict):
        meta = {}

    out = {
        "temp_c": meta.get("temp_c"),
        "rh_pct": meta.get("rh_pct"),
        "temp_low_c": meta.get("temp_low_c"),
        "temp_high_c": meta.get("temp_high_c"),
        "temp_amber_margin_c": meta.get("temp_amber_margin_c"),
        "rh_low_pct": meta.get("rh_low_pct"),
        "rh_high_pct": meta.get("rh_high_pct"),
        "rh_amber_margin_pct": meta.get("rh_amber_margin_pct"),
        "water_lpm": meta.get("water_lpm"),
        "water_low_lpm": meta.get("water_low_lpm"),
        "water_amber_buffer_lpm": meta.get("water_amber_buffer_lpm"),
        "water_total_litres": meta.get("water_total_litres"),
        "feed_kg": meta.get("feed_kg"),
        "feed_kg_updated_ts": meta.get("feed_kg_updated_ts"),
        "feed_noise_kg": meta.get("feed_noise_kg"),
        "feed_low_kg": meta.get("feed_low_kg"),
        "feed_amber_buffer_kg": meta.get("feed_amber_buffer_kg"),
        "lighting_on": meta.get("lighting_on"),
        "lighting_enabled": bool(meta.get("lighting_enabled", False)),
        "lighting_label": meta.get("lighting_label"),
        "lighting_last_changed_ts": meta.get("lighting_last_changed_ts"),
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
        "auger_enabled": {},
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
                "last_started_ts": rec.get("last_started_ts"),
                "last_stopped_ts": rec.get("last_stopped_ts"),
                "last_duration_s": rec.get("last_duration_s"),
                "overrun": bool(rec.get("overrun", False)),
            }

    auger_enabled = meta.get("auger_enabled", {})
    if isinstance(auger_enabled, dict):
        for key in ["cross_auger", "auger_left", "auger_right"]:
            if key in auger_enabled:
                out["auger_enabled"][key] = bool(auger_enabled.get(key, False))

    return out


def dashboard_auger_tiles(controller_meta, now_ts=None, force_red=False):
    if now_ts is None:
        now_ts = int(time.time())
    tiles = []
    augers = controller_meta.get("augers", {})
    auger_enabled = controller_meta.get("auger_enabled", {})
    controller_alarms = controller_meta.get("controller_alarms", [])
    if not isinstance(augers, dict):
        return tiles
    has_enabled_map = isinstance(auger_enabled, dict) and any(
        key in auger_enabled for key in ["cross_auger", "auger_left", "auger_right"]
    )

    for key in ["cross_auger", "auger_left", "auger_right"]:
        if has_enabled_map and not bool(auger_enabled.get(key, False)):
            continue
        rec = augers.get(key, {})
        if not isinstance(rec, dict):
            rec = {}
        label = str(rec.get("label") or key.replace("_", " ").title())
        is_on = bool(rec.get("on", False))
        overrun = bool(rec.get("overrun", False))
        started_ts = rec.get("started_ts")
        last_started_ts = rec.get("last_started_ts")
        last_stopped_ts = rec.get("last_stopped_ts")
        last_duration_s = rec.get("last_duration_s")
        issue = bool(force_red) or overrun
        if not issue and isinstance(controller_alarms, list):
            label_lower = label.strip().lower()
            i = 0
            while i < len(controller_alarms):
                alarm = controller_alarms[i]
                if isinstance(alarm, dict):
                    alarm_key = str(alarm.get("alarm_key", "") or "").strip().lower()
                    message = str(alarm.get("message", "") or "").strip().lower()
                    if (
                        alarm_key.startswith(key)
                        or key in alarm_key
                        or (label_lower and label_lower in message)
                    ):
                        issue = True
                        break
                i += 1
        if is_on:
            timestamp_text = format_clock_compact(started_ts if started_ts not in [None, ""] else last_started_ts)
            try:
                runtime_text = format_duration_compact(max(0, int(now_ts) - int(started_ts)))
            except Exception:
                runtime_text = format_duration_compact(last_duration_s)
        else:
            timestamp_text = format_clock_compact(last_stopped_ts if last_stopped_ts not in [None, ""] else last_started_ts)
            runtime_text = format_duration_compact(last_duration_s)
        glow = "state-red" if issue else "state-green"
        tiles.append({
            "key": key,
            "label": label,
            "timestamp": timestamp_text,
            "runtime": runtime_text,
            "glow": glow,
        })
    return tiles


def save_live_latest_map(data):
    path = os.path.join(DATA_DIR, "live_latest.json")
    write_json_file_atomic(path, data if isinstance(data, dict) else {})


def save_live_snapshot_for_shed(shed_no, meta):
    if not isinstance(meta, dict):
        return

    shed_name = shed_name_from_number(shed_no)
    live_map = latest_live_by_shed()
    rec = dict(live_map.get(shed_name, {}))

    for key in ["temp_c", "rh_pct", "water_lpm", "feed_kg", "water_total_litres"]:
        if meta.get(key) is not None:
            rec[key] = meta.get(key)

    rec["ts"] = meta.get("last_sensor_ts") if meta.get("last_sensor_ts") not in [None, ""] else int(time.time())
    rec["source"] = "controller_sync"
    live_map[shed_name] = rec
    save_live_latest_map(live_map)


def update_shed_hourly_metrics_from_meta(shed_no, meta):
    if not isinstance(meta, dict):
        return False

    try:
        sensor_ts = int(meta.get("last_sensor_ts"))
    except Exception:
        return False
    try:
        water_total_litres = float(meta.get("water_total_litres"))
    except Exception:
        water_total_litres = None
    try:
        feed_kg = float(meta.get("feed_kg"))
    except Exception:
        feed_kg = None
    try:
        feed_sample_ts = int(meta.get("feed_kg_updated_ts"))
    except Exception:
        feed_sample_ts = sensor_ts
    if water_total_litres is None and feed_kg is None:
        return False

    shed_name = shed_name_from_number(shed_no)
    crop_id = get_active_crop_id_for_shed(shed_name)
    out_of_crop = crop_id in [None, ""]
    rows = read_all_json_lines("hourly.ndjson")

    def matches_crop(row):
        if row.get("shed") != shed_name:
            return False
        if out_of_crop:
            return row.get("crop_id") in [None, ""]
        try:
            return int(row.get("crop_id")) == int(crop_id)
        except Exception:
            return False

    def hour_row(hour_epoch):
        i = 0
        while i < len(rows):
            row = rows[i]
            try:
                same_hour = int(row.get("hour_epoch")) == int(hour_epoch)
            except Exception:
                same_hour = False
            if same_hour and matches_crop(row):
                return row
            i += 1
        row = {
            "ts": int(time.time()),
            "shed": shed_name,
            "crop_id": None if out_of_crop else int(crop_id),
            "hour_epoch": int(hour_epoch),
            "out_of_crop": bool(out_of_crop),
            "source": "controller_sync",
        }
        rows.append(row)
        return row

    if water_total_litres is not None:
        row = hour_row((sensor_ts // 3600) * 3600)
        try:
            start_total_litres = float(row.get("start_total_litres"))
        except Exception:
            start_total_litres = water_total_litres
        if water_total_litres < start_total_litres:
            start_total_litres = water_total_litres
        row["start_total_litres"] = start_total_litres
        row["water_total_litres"] = water_total_litres
        row["water_hour_liters"] = round(max(0.0, water_total_litres - start_total_litres), 3)
        row["ts"] = int(time.time())
        row["source"] = "controller_sync"
        row["out_of_crop"] = bool(out_of_crop)

    if feed_kg is not None:
        latest_feed_row = None
        latest_feed_ts = None
        i = 0
        while i < len(rows):
            candidate = rows[i]
            if matches_crop(candidate):
                try:
                    candidate_ts = int(candidate.get("feed_sample_ts"))
                except Exception:
                    candidate_ts = None
                if candidate_ts is not None and (latest_feed_ts is None or candidate_ts > latest_feed_ts):
                    latest_feed_ts = candidate_ts
                    latest_feed_row = candidate
            i += 1

        if latest_feed_ts is None or feed_sample_ts > latest_feed_ts:
            row = hour_row((feed_sample_ts // 3600) * 3600)
            try:
                low_feed_kg = float(latest_feed_row.get("feed_low_kg"))
            except Exception:
                low_feed_kg = feed_kg
            try:
                feed_hour_kg = float(row.get("feed_hour_kg") or 0.0)
            except Exception:
                feed_hour_kg = 0.0
            try:
                settling_until_ts = int(latest_feed_row.get("feed_settling_until_ts"))
            except Exception:
                settling_until_ts = None
            try:
                noise_kg = max(0.0, float(meta.get("feed_noise_kg") or 0.0))
            except Exception:
                noise_kg = 0.0
            min_drop_kg = max(FEED_RECORDING_MIN_DROP_KG, noise_kg * FEED_RECORDING_NOISE_FACTOR)

            if feed_kg >= low_feed_kg + FEED_RECORDING_REFILL_RISE_KG:
                settling_until_ts = feed_sample_ts + FEED_REFILL_SETTLING_SECONDS
                low_feed_kg = feed_kg
            elif settling_until_ts is not None and feed_sample_ts < settling_until_ts:
                low_feed_kg = feed_kg
            elif feed_kg <= low_feed_kg - min_drop_kg:
                settling_until_ts = None
                feed_hour_kg += low_feed_kg - feed_kg
                low_feed_kg = feed_kg
            elif settling_until_ts is not None and feed_sample_ts >= settling_until_ts:
                settling_until_ts = None

            row["feed_hour_kg"] = round(max(0.0, feed_hour_kg), 3)
            row["feed_low_kg"] = round(low_feed_kg, 3)
            row["feed_last_kg"] = round(feed_kg, 3)
            row["feed_sample_ts"] = int(feed_sample_ts)
            row["feed_recording_min_drop_kg"] = round(min_drop_kg, 3)
            row["feed_settling_until_ts"] = settling_until_ts
            row["ts"] = int(time.time())
            row["source"] = "controller_sync"
            row["out_of_crop"] = bool(out_of_crop)

    write_named_json_lines_atomic("hourly.ndjson", rows)
    return True


def save_controller_meta_for_shed(shed_no, meta):
    all_meta = load_controller_meta()
    all_meta[str(int(shed_no))] = clean_controller_meta(meta)
    save_controller_meta(all_meta)


def controller_sync_age(meta):
    try:
        received_ts = int(meta.get("received_ts")) if meta.get("received_ts") not in [None, ""] else None
    except Exception:
        received_ts = None
    if received_ts is None:
        return None
    return max(0, int(time.time()) - received_ts)


def controller_heartbeat_ok(meta, stale_after_s=30):
    sync_age = controller_sync_age(meta)
    return sync_age is not None and sync_age <= int(stale_after_s)


def effective_pico_connected(meta, stale_after_s=30):
    if not controller_heartbeat_ok(meta, stale_after_s=stale_after_s):
        return False
    return bool(meta.get("pico_connected", False))


def controller_online(meta, stale_after_s=30):
    return effective_pico_connected(meta, stale_after_s=stale_after_s)


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
    previous_crop_id = farm_crop.get("current_crop_id")
    try:
        previous_crop_id = int(previous_crop_id) if previous_crop_id not in [None, ""] else None
    except Exception:
        previous_crop_id = None
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
    if previous_crop_id is not None and current_crop_id is None:
        if queue_crop_end_report(previous_crop_id):
            log_event("office", "crop_report_queued", "Full crop summary queued", detail="Crop %s" % previous_crop_id)


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
        "feed_kg": latest_feed_kg_for_shed(shed_name),
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
    push_shed_state_to_controller_async(shed_no)
    return True, "Mortality recorded"


def move_mortality_history_between_sheds(from_shed_name, to_shed_name, dest_shed, crop_id):
    if crop_id in [None, ""]:
        return 0

    rows = read_all_json_lines("mortality.ndjson")
    changed = 0
    i = 0
    while i < len(rows):
        rec = rows[i]
        if str(rec.get("shed")) != str(from_shed_name):
            i += 1
            continue
        try:
            if int(rec.get("dest_shed")) != int(dest_shed):
                i += 1
                continue
        except Exception:
            i += 1
            continue
        try:
            if int(rec.get("crop_id")) != int(crop_id):
                i += 1
                continue
        except Exception:
            i += 1
            continue
        rec["shed"] = str(to_shed_name)
        changed += 1
        i += 1

    if changed > 0:
        write_named_json_lines_atomic("mortality.ndjson", rows)
    return changed


FEED_STOCK_KIND_LABELS = {
    "crop_carryover_credit": "Crop End Carryover (Legacy)",
    "manual_add": "Manual Add",
    "manual_remove": "Manual Remove",
    "shed_allocation": "Manual Shed Feed Entry",
    "shed_return": "Shed Feed Return (Legacy)",
}


def feed_stock_transactions():
    rows = read_all_json_lines("feed_stock.ndjson")
    out = []
    i = 0
    while i < len(rows):
        rec = rows[i]
        if not isinstance(rec, dict):
            i += 1
            continue
        try:
            delta_kg = round(float(rec.get("delta_kg") or 0.0), 3)
        except Exception:
            i += 1
            continue
        if abs(delta_kg) < 0.0005:
            i += 1
            continue
        try:
            ts = int(rec.get("ts") or 0)
        except Exception:
            ts = 0
        try:
            shed_no = int(rec.get("shed_no")) if rec.get("shed_no") not in [None, ""] else None
        except Exception:
            shed_no = None
        try:
            crop_id = int(rec.get("crop_id")) if rec.get("crop_id") not in [None, ""] else None
        except Exception:
            crop_id = None
        try:
            source_crop_id = int(rec.get("source_crop_id")) if rec.get("source_crop_id") not in [None, ""] else None
        except Exception:
            source_crop_id = None
        out.append({
            "ts": ts,
            "kind": str(rec.get("kind") or "manual_add"),
            "delta_kg": delta_kg,
            "shed_no": shed_no,
            "crop_id": crop_id,
            "source_crop_id": source_crop_id,
            "note": str(rec.get("note") or "").strip(),
        })
        i += 1
    out.sort(key=lambda row: int(row.get("ts") or 0))
    return out


def append_feed_stock_transaction(kind, delta_kg, note="", shed_no=None, crop_id=None, source_crop_id=None, ts=None):
    try:
        delta_kg = round(float(delta_kg), 3)
    except Exception:
        return False
    if abs(delta_kg) < 0.0005:
        return False
    try:
        tx_ts = int(ts) if ts not in [None, ""] else int(time.time())
    except Exception:
        tx_ts = int(time.time())
    append_named_json_line("feed_stock.ndjson", {
        "ts": tx_ts,
        "kind": str(kind or "manual_add"),
        "delta_kg": delta_kg,
        "shed_no": None if shed_no in [None, ""] else int(shed_no),
        "crop_id": None if crop_id in [None, ""] else int(crop_id),
        "source_crop_id": None if source_crop_id in [None, ""] else int(source_crop_id),
        "note": str(note or "").strip(),
    })
    return True


def feed_stock_active_target_rows():
    rows = []
    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        shed_name = shed_name_from_number(shed_no)
        crop_id = get_active_crop_id_for_shed(shed_name)
        if crop_id not in [None, ""]:
            rows.append({
                "shed_no": shed_no,
                "shed_name": shed_name,
                "crop_id": int(crop_id),
                "crop_code": fmt_crop_code(crop_id, active_crop_record_for_shed(shed_name).get("placement_epoch")),
            })
        i += 1
    return rows


def feed_stock_allocated_kg_for_target(shed_no, crop_id, rows=None):
    try:
        shed_no = int(shed_no)
        crop_id = int(crop_id)
    except Exception:
        return 0.0
    rows = rows if isinstance(rows, list) else feed_stock_transactions()
    allocated_kg = 0.0
    i = 0
    while i < len(rows):
        rec = rows[i]
        try:
            if int(rec.get("shed_no")) != shed_no or int(rec.get("crop_id")) != crop_id:
                i += 1
                continue
        except Exception:
            i += 1
            continue
        if rec.get("kind") == "shed_allocation":
            allocated_kg += abs(float(rec.get("delta_kg") or 0.0))
        elif rec.get("kind") == "shed_return":
            allocated_kg -= abs(float(rec.get("delta_kg") or 0.0))
        i += 1
    return round(max(0.0, allocated_kg), 3)


def build_feed_stock_context(preselected_shed_no=None):
    tx_rows = feed_stock_transactions()
    display_rows = [row for row in reversed(tx_rows) if row.get("kind") == "shed_allocation"]
    i = 0
    while i < len(display_rows):
        rec = display_rows[i]
        rec["kind_label"] = FEED_STOCK_KIND_LABELS.get(rec.get("kind"), str(rec.get("kind") or "").replace("_", " ").title())
        rec["delta_kg_label"] = fmt_value(rec.get("delta_kg"), "f1")
        rec["feed_kg_label"] = fmt_value(abs(float(rec.get("delta_kg") or 0.0)), "f1")
        try:
            rec["ts_label"] = datetime.fromtimestamp(int(rec.get("ts"))).strftime("%d %b %Y %H:%M")
        except Exception:
            rec["ts_label"] = "--"
        if rec.get("shed_no") not in [None, ""]:
            rec["shed_label"] = shed_name_from_number(rec.get("shed_no"))
        else:
            rec["shed_label"] = "--"
        if rec.get("crop_id") not in [None, ""]:
            rec["crop_label"] = "To %s" % fmt_crop_code(rec.get("crop_id"))
        elif rec.get("source_crop_id") not in [None, ""]:
            rec["crop_label"] = "From %s" % fmt_crop_code(rec.get("source_crop_id"))
        else:
            rec["crop_label"] = "--"
        i += 1

    try:
        preselected_shed_no = int(preselected_shed_no) if preselected_shed_no not in [None, ""] else None
    except Exception:
        preselected_shed_no = None

    return {
        "transaction_rows": display_rows,
        "active_targets": feed_stock_active_target_rows(),
        "preselected_shed_no": preselected_shed_no,
    }


def safe_local_redirect_target(target):
    target = str(target or "").strip()
    if target.startswith("/") and not target.startswith("//"):
        return target
    return None


def append_query_to_url(url, params):
    parts = urllib.parse.urlsplit(str(url or ""))
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    for key, value in params.items():
        query.append((str(key), str(value)))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))


def redirect_with_next(default_endpoint, ok, msg, **values):
    target = safe_local_redirect_target(request.form.get("next", "") or request.args.get("next", ""))
    if target:
        return redirect(append_query_to_url(target, {"ok": 1 if ok else 0, "msg": msg}))
    return redirect(url_for(default_endpoint, ok=1 if ok else 0, msg=msg, **values))


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
    ended_entries = state.get(shed_name, {}).get("ended_entries", {})
    payload_entries = {}

    for key in entries:
        payload_entries[str(key)] = clean_entry_record(entries.get(key, {}))

    crop = active_crop_record_for_shed(shed_name)
    try:
        active_crop_id = int(crop.get("crop_id"))
    except Exception:
        active_crop_id = None

    days = get_daily_history_for_shed(shed_name, max_days=40, crop_id=active_crop_id, include_manual_feed=True)
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


def push_shed_state_to_controller_async(shed_no):
    def worker():
        try:
            push_shed_state_to_controller(shed_no)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def apply_external_shed_entries(shed_no, incoming_entries, source, controller_meta=None):
    state = load_shed_entries_state()
    shed_name = shed_name_from_number(shed_no)
    entries = ensure_shed_entry_bucket(state, shed_name)
    ended_entries = state.get(shed_name, {}).get("ended_entries", {})
    now_ts = int(time.time())
    changed = False
    try:
        controller_seen_sync_version = int((controller_meta or {}).get("last_seen_office_sync_version") or 0)
    except Exception:
        controller_seen_sync_version = 0
    try:
        controller_state_updated_ts = int((controller_meta or {}).get("controller_state_updated_ts") or 0)
    except Exception:
        controller_state_updated_ts = 0
    try:
        controller_entries_updated_ts = int((controller_meta or {}).get("controller_entries_updated_ts") or 0)
    except Exception:
        controller_entries_updated_ts = 0

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
            ended_ts = 0
            try:
                ended_ts = int(ended_entries.get(str(dest_shed)) or 0)
            except Exception:
                ended_ts = 0
            incoming_updated_ts = int(rec.get("updated_ts") or 0)
            if rec["bird_count"] > 0 and ended_ts > 0 and incoming_updated_ts <= ended_ts:
                log_event(
                    "office",
                    "entry_sync_revival_blocked",
                    "Blocked stale controller reactivation",
                    shed_no=shed_no,
                    detail="Entry Shed %d older than dashboard end" % dest_shed,
                )
                continue
            if rec["bird_count"] > 0 and rec["crop_active"] == 1 and rec["crop_id"] is None:
                rec["crop_id"] = crop_id_for_new_start(state)
            other_shed = active_entry_location_for_dest(state, dest_shed, exclude_shed_name=shed_name)
            if rec["bird_count"] > 0 and rec["crop_active"] == 1 and other_shed:
                log_event(
                    "office",
                    "entry_sync_conflict",
                    "Rejected duplicate active entry from controller sync",
                    shed_no=shed_no,
                    detail="Entry Shed %d already active in %s" % (dest_shed, other_shed),
                )
                continue
            cleaned_incoming[str(dest_shed)] = rec

    existing_keys = list(entries.keys())
    for key in existing_keys:
        if key not in cleaned_incoming:
            prev = clean_entry_record(entries.get(key, {}))
            try:
                prev_updated_ts = int(prev.get("updated_ts") or 0)
            except Exception:
                prev_updated_ts = 0
            is_possible_stale_delete = (
                prev["bird_count"] > 0
                and controller_entries_updated_ts <= prev_updated_ts
                and (
                    controller_seen_sync_version <= 0
                    or prev_updated_ts >= controller_seen_sync_version
                )
            )
            if is_possible_stale_delete:
                log_event(
                    "office",
                    "entry_sync_delete_blocked",
                    "Blocked stale controller delete by omission",
                    shed_no=shed_no,
                    detail="Entry Shed %s retained in %s" % (key, shed_name),
                )
                continue
            if prev["bird_count"] > 0 or prev["crop_id"] is not None:
                log_crop_event(shed_name, prev, False)
                ended_entries[str(key)] = max(now_ts, prev_updated_ts)
                changed = True
            del entries[key]

    for key in cleaned_incoming:
        prev = clean_entry_record(entries.get(key, {}))
        new_rec = cleaned_incoming[key]

        same_active_flock = (
            prev["bird_count"] > 0
            and new_rec["bird_count"] > 0
            and prev["crop_active"] == 1
            and new_rec["crop_active"] == 1
            and str(prev.get("crop_id")) == str(new_rec.get("crop_id"))
            and str(prev.get("placement_epoch")) == str(new_rec.get("placement_epoch"))
        )
        try:
            prev_updated_ts = int(prev.get("updated_ts") or 0)
        except Exception:
            prev_updated_ts = 0
        try:
            new_updated_ts = int(new_rec.get("updated_ts") or 0)
        except Exception:
            new_updated_ts = 0

        if same_active_flock and prev_updated_ts > new_updated_ts:
            new_rec = prev

        if prev == new_rec:
            continue

        entries[key] = new_rec
        if new_rec["bird_count"] > 0 and str(key) in ended_entries:
            del ended_entries[str(key)]
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
    if dt_obj.hour < 6:
        dt_obj = dt_obj - timedelta(days=1)
    return dt_obj.strftime("%Y-%m-%d")


def shed_name_from_number(shed_no):
    return "Shed %d" % int(shed_no)


def shed_number_from_name(shed_name):
    match = re.search(r"(\d+)$", str(shed_name or "").strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def latest_feed_kg_for_shed(shed_name):
    shed_no = shed_number_from_name(shed_name)
    if shed_no is None:
        return None
    live = effective_live_for_shed(latest_live_by_shed(), load_controller_meta(), shed_no)
    return _safe_float(live.get("feed_kg"))


def feed_stock_feed_adjustments(rows=None):
    rows = rows if isinstance(rows, list) else feed_stock_transactions()
    out = []
    i = 0
    while i < len(rows):
        rec = rows[i]
        kind = str(rec.get("kind") or "")
        if kind not in ["shed_allocation", "shed_return"]:
            i += 1
            continue
        try:
            shed_no = int(rec.get("shed_no"))
            crop_id = int(rec.get("crop_id"))
            ts = int(rec.get("ts") or 0)
        except Exception:
            i += 1
            continue
        delta_kg = abs(float(rec.get("delta_kg") or 0.0))
        if kind == "shed_return":
            delta_kg = -delta_kg
        if abs(delta_kg) < 0.0005:
            i += 1
            continue
        out.append({
            "shed_no": shed_no,
            "shed_name": shed_name_from_number(shed_no),
            "crop_id": crop_id,
            "ts": ts,
            "delta_kg": round(delta_kg, 3),
            "kind": kind,
        })
        i += 1
    return out


def feed_stock_feed_adjustment_kg_for_shed_crop(shed_name, crop_id, rows=None):
    if crop_id in [None, ""]:
        return 0.0
    rows = rows if isinstance(rows, list) else feed_stock_feed_adjustments()
    total = 0.0
    i = 0
    while i < len(rows):
        rec = rows[i]
        if rec.get("shed_name") != shed_name:
            i += 1
            continue
        try:
            if int(rec.get("crop_id")) != int(crop_id):
                i += 1
                continue
        except Exception:
            i += 1
            continue
        total += float(rec.get("delta_kg") or 0.0)
        i += 1
    return round(total, 3)


def feed_stock_feed_adjustment_hour_map_for_shed_crop(shed_name, crop_id, rows=None):
    out = {}
    if crop_id in [None, ""]:
        return out
    rows = rows if isinstance(rows, list) else feed_stock_feed_adjustments()
    i = 0
    while i < len(rows):
        rec = rows[i]
        if rec.get("shed_name") != shed_name:
            i += 1
            continue
        try:
            if int(rec.get("crop_id")) != int(crop_id):
                i += 1
                continue
            dt_obj = datetime.fromtimestamp(int(rec.get("ts") or 0)).replace(minute=0, second=0, microsecond=0)
            hour_epoch = int(dt_obj.timestamp())
        except Exception:
            i += 1
            continue
        out[hour_epoch] = round(float(out.get(hour_epoch) or 0.0) + float(rec.get("delta_kg") or 0.0), 3)
        i += 1
    return out


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


def get_hourly_history_for_shed(shed_name, max_points=168, crop_id=None, include_manual_feed=False):
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
        else:
            if p.get("crop_id") not in [None, ""]:
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
            "out_of_crop": bool(p.get("out_of_crop", False)),
        })
        i += 1

    rows.sort(key=lambda x: x["epoch"])
    if include_manual_feed and crop_id not in [None, ""]:
        manual_hour_map = feed_stock_feed_adjustment_hour_map_for_shed_crop(shed_name, crop_id)
        if manual_hour_map:
            existing = {}
            i = 0
            while i < len(rows):
                existing[int(rows[i]["epoch"])] = rows[i]
                i += 1
            for hour_epoch in sorted(manual_hour_map.keys()):
                delta_kg = float(manual_hour_map.get(hour_epoch) or 0.0)
                if abs(delta_kg) < 0.0005:
                    continue
                rec = existing.get(int(hour_epoch))
                if isinstance(rec, dict):
                    current_feed = rec.get("feed")
                    rec["feed"] = round((float(current_feed) if current_feed is not None else 0.0) + delta_kg, 3)
                    rec["manual_feed_adjustment_kg"] = round(float(rec.get("manual_feed_adjustment_kg") or 0.0) + delta_kg, 3)
                else:
                    try:
                        label = datetime.fromtimestamp(int(hour_epoch)).strftime("%d %b %H:%M")
                    except Exception:
                        label = str(hour_epoch)
                    rows.append({
                        "epoch": int(hour_epoch),
                        "label": label,
                        "water": None,
                        "feed": round(delta_kg, 3),
                        "crop_id": crop_id,
                        "out_of_crop": False,
                        "manual_feed_adjustment_kg": round(delta_kg, 3),
                    })
            rows.sort(key=lambda x: x["epoch"])
    if max_points and len(rows) > max_points:
        rows = rows[-max_points:]
    return rows


def aggregate_history_rows_by_hours(rows, bucket_hours=6):
    try:
        bucket_hours = max(1, int(bucket_hours))
    except Exception:
        bucket_hours = 6
    grouped = {}
    order = []

    i = 0
    while i < len(rows):
        rec = rows[i]
        try:
            epoch = int(rec.get("epoch"))
        except Exception:
            i += 1
            continue
        dt_obj = datetime.fromtimestamp(epoch)
        bucket_dt = dt_obj.replace(
            hour=(dt_obj.hour // bucket_hours) * bucket_hours,
            minute=0,
            second=0,
            microsecond=0,
        )
        bucket_epoch = int(bucket_dt.timestamp())
        bucket = grouped.get(bucket_epoch)
        if not isinstance(bucket, dict):
            try:
                bucket_label = datetime.fromtimestamp(bucket_epoch).strftime("%d %b %H:%M")
            except Exception:
                bucket_label = str(bucket_epoch)
            bucket = {
                "epoch": bucket_epoch,
                "label": bucket_label,
                "water": 0.0,
                "feed": 0.0,
                "crop_id": rec.get("crop_id"),
                "out_of_crop": bool(rec.get("out_of_crop", False)),
                "has_water": False,
                "has_feed": False,
            }
            grouped[bucket_epoch] = bucket
            order.append(bucket_epoch)

        try:
            if rec.get("water") is not None:
                bucket["water"] += float(rec.get("water") or 0.0)
                bucket["has_water"] = True
        except Exception:
            pass
        try:
            if rec.get("feed") is not None:
                bucket["feed"] += float(rec.get("feed") or 0.0)
                bucket["has_feed"] = True
        except Exception:
            pass
        i += 1

    out = []
    i = 0
    while i < len(order):
        bucket = dict(grouped[order[i]])
        bucket["water"] = round(bucket["water"], 3) if bucket.get("has_water") else None
        bucket["feed"] = round(bucket["feed"], 3) if bucket.get("has_feed") else None
        bucket.pop("has_water", None)
        bucket.pop("has_feed", None)
        out.append(bucket)
        i += 1
    return out


def shed_rows_for_period(shed_name, period, crop_id=None):
    if period == "hourly":
        rows = get_hourly_history_for_shed(shed_name, max_points=168 if crop_id in [None, ""] else 0, crop_id=crop_id, include_manual_feed=True)
        rows = aggregate_history_rows_by_hours(rows, bucket_hours=6)
        rows = add_running_totals(rows)
        return rows, "6 Hour", "6 Hour Block"

    rows = get_daily_history_for_shed(shed_name, max_days=40 if crop_id in [None, ""] else 0, crop_id=crop_id, include_manual_feed=True)
    rows = add_running_totals(rows)
    return rows, "Daily", "Day"


def get_daily_history_for_shed(shed_name, max_days=40, crop_id=None, include_manual_feed=False):
    hourly_rows = get_hourly_history_for_shed(shed_name, max_points=0, crop_id=crop_id, include_manual_feed=include_manual_feed)

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


def get_crop_events_for_shed(shed_name, crop_id):
    rows = read_all_json_lines("crop.ndjson")
    out = []

    i = 0
    while i < len(rows):
        rec = rows[i]
        if rec.get("shed") != shed_name:
            i += 1
            continue

        try:
            rec_crop_id = int(rec.get("crop_id"))
        except Exception:
            i += 1
            continue

        if rec_crop_id != int(crop_id):
            i += 1
            continue

        out.append(rec)
        i += 1

    out.sort(key=lambda x: int(x.get("ts", 0) or 0))
    return out


def _safe_int(value, default=None):
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def build_crop_summary_for_shed(shed_name, crop_id):
    events = get_crop_events_for_shed(shed_name, crop_id)
    hourly_rows = add_running_totals(get_hourly_history_for_shed(shed_name, max_points=0, crop_id=crop_id, include_manual_feed=True))
    daily_rows = add_running_totals(get_daily_history_for_shed(shed_name, max_days=0, crop_id=crop_id, include_manual_feed=True))
    mortality_rows = get_mortality_history_for_shed(shed_name, crop_id=crop_id)
    mortality_total = mortality_total_for_shed_crop(shed_name, crop_id)
    manual_feed_adjustment_kg = feed_stock_feed_adjustment_kg_for_shed_crop(shed_name, crop_id)

    start_event = None
    end_event = None
    max_active_birds = 0
    latest_event = events[-1] if events else None

    i = 0
    while i < len(events):
        rec = events[i]
        crop_active = 1 if _safe_int(rec.get("crop_active"), 0) == 1 else 0
        bird_count = _safe_int(rec.get("bird_count"), 0) or 0
        if crop_active == 1:
            if start_event is None:
                start_event = rec
            if bird_count > max_active_birds:
                max_active_birds = bird_count
        else:
            end_event = rec
        i += 1

    start_epoch = None
    if start_event is not None:
        start_epoch = _safe_int(start_event.get("placement_epoch"))
        if start_epoch is None:
            start_epoch = _safe_int(start_event.get("ts"))
    if start_epoch is None and hourly_rows:
        start_epoch = _safe_int(hourly_rows[0].get("epoch"))
    if start_epoch is None and latest_event is not None:
        start_epoch = _safe_int(latest_event.get("placement_epoch")) or _safe_int(latest_event.get("ts"))

    end_epoch = None
    if end_event is not None:
        end_epoch = _safe_int(end_event.get("ts"))
    if end_epoch is None and hourly_rows:
        end_epoch = _safe_int(hourly_rows[-1].get("epoch"))
    if end_epoch is None and latest_event is not None:
        end_epoch = _safe_int(latest_event.get("ts"))

    birds_remaining_end = None
    if end_event is not None:
        birds_remaining_end = _safe_int(end_event.get("bird_count"))
    if birds_remaining_end is None and latest_event is not None:
        birds_remaining_end = _safe_int(latest_event.get("bird_count"))
    if birds_remaining_end is None:
        birds_remaining_end = 0

    feed_bin_end_kg = None
    if end_event is not None:
        feed_bin_end_kg = _safe_float(end_event.get("feed_kg"))
    if feed_bin_end_kg is None and latest_event is not None and end_event is None:
        feed_bin_end_kg = _safe_float(latest_event.get("feed_kg"))

    birds_placed_candidates = []
    if max_active_birds > 0:
        birds_placed_candidates.append(max_active_birds)
    if birds_remaining_end is not None:
        birds_placed_candidates.append((birds_remaining_end or 0) + int(mortality_total or 0))
    birds_placed = max(birds_placed_candidates) if birds_placed_candidates else None

    total_feed = 0.0
    total_water = 0.0
    if hourly_rows:
        total_feed = float(hourly_rows[-1].get("running_feed") or 0.0)
        total_water = float(hourly_rows[-1].get("running_water") or 0.0)

    complete_day_count = len(daily_rows)
    avg_daily_feed = (total_feed / complete_day_count) if complete_day_count > 0 else None
    avg_daily_water = (total_water / complete_day_count) if complete_day_count > 0 else None

    feed_per_bird = None
    water_per_bird = None
    mortality_pct = None
    if birds_placed not in [None, 0]:
        feed_per_bird = total_feed / float(birds_placed)
        water_per_bird = total_water / float(birds_placed)
        if mortality_total:
            mortality_pct = (float(mortality_total) / float(birds_placed)) * 100.0

    peak_daily_feed = None
    peak_daily_water = None
    if daily_rows:
        peak_daily_feed = max((_safe_float(r.get("feed"), 0.0) or 0.0) for r in daily_rows)
        peak_daily_water = max((_safe_float(r.get("water"), 0.0) or 0.0) for r in daily_rows)

    crop_days = None
    if start_epoch is not None and end_epoch is not None:
        try:
            start_date = datetime.fromtimestamp(int(start_epoch)).date()
            end_date = datetime.fromtimestamp(int(end_epoch)).date()
            crop_days = max(1, (end_date - start_date).days + 1)
        except Exception:
            crop_days = None

    summary_status = "Ended" if end_event is not None else ("In progress" if events else "No crop data")

    return {
        "crop_id": int(crop_id),
        "crop_code": fmt_crop_code(crop_id, start_epoch),
        "status": summary_status,
        "start_epoch": start_epoch,
        "end_epoch": end_epoch,
        "start_label": datetime.fromtimestamp(start_epoch).strftime("%d %b %Y %H:%M") if start_epoch is not None else "--",
        "end_label": datetime.fromtimestamp(end_epoch).strftime("%d %b %Y %H:%M") if end_epoch is not None else "--",
        "crop_days": crop_days,
        "birds_placed": birds_placed,
        "birds_remaining_end": birds_remaining_end,
        "mortality_total": mortality_total,
        "mortality_pct": mortality_pct,
        "manual_feed_adjustment_kg": manual_feed_adjustment_kg,
        "total_feed": total_feed,
        "feed_bin_end_kg": feed_bin_end_kg,
        "total_water": total_water,
        "avg_daily_feed": avg_daily_feed,
        "avg_daily_water": avg_daily_water,
        "peak_daily_feed": peak_daily_feed,
        "peak_daily_water": peak_daily_water,
        "feed_per_bird": feed_per_bird,
        "water_per_bird": water_per_bird,
        "hourly_points": len(hourly_rows),
        "complete_days": complete_day_count,
        "mortality_events": len(mortality_rows),
        "daily_rows": daily_rows,
    }


def crop_summary_has_data(summary):
    if not isinstance(summary, dict):
        return False
    if summary.get("status") != "No crop data":
        return True
    numeric_keys = [
        "hourly_points",
        "complete_days",
        "mortality_events",
        "birds_placed",
        "birds_remaining_end",
        "mortality_total",
        "total_feed",
        "total_water",
    ]
    i = 0
    while i < len(numeric_keys):
        value = summary.get(numeric_keys[i])
        try:
            if float(value or 0) != 0.0:
                return True
        except Exception:
            pass
        i += 1
    return False


def farm_identity():
    cfg = load_office_config()
    farm_name = str(cfg.get("farm_name") or cfg.get("name") or "Farm").strip() or "Farm"
    farm_id = str(cfg.get("farm_id") or "").strip()
    return farm_name, farm_id


def build_farm_crop_summary(crop_id):
    farm_name, farm_id = farm_identity()
    shed_rows = []
    start_epochs = []
    end_epochs = []
    total_birds_placed = 0
    total_birds_remaining = 0
    total_mortality = 0
    total_manual_feed_adjustment_kg = 0.0
    total_feed = 0.0
    total_feed_bin_end_kg = 0.0
    total_water = 0.0
    total_complete_days = 0
    total_mortality_events = 0
    max_crop_days = 0
    has_feed_bin_end = False

    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        shed_name = shed_name_from_number(shed_no)
        summary = build_crop_summary_for_shed(shed_name, crop_id)
        if crop_summary_has_data(summary):
            shed_rows.append({
                "shed_no": shed_no,
                "shed_name": shed_name,
                "summary": summary,
            })
            if summary.get("start_epoch") is not None:
                start_epochs.append(int(summary["start_epoch"]))
            if summary.get("end_epoch") is not None:
                end_epochs.append(int(summary["end_epoch"]))
            total_birds_placed += int(summary.get("birds_placed") or 0)
            total_birds_remaining += int(summary.get("birds_remaining_end") or 0)
            total_mortality += int(summary.get("mortality_total") or 0)
            total_manual_feed_adjustment_kg += float(summary.get("manual_feed_adjustment_kg") or 0.0)
            total_feed += float(summary.get("total_feed") or 0.0)
            if summary.get("feed_bin_end_kg") is not None:
                total_feed_bin_end_kg += float(summary.get("feed_bin_end_kg") or 0.0)
                has_feed_bin_end = True
            total_water += float(summary.get("total_water") or 0.0)
            total_complete_days += int(summary.get("complete_days") or 0)
            total_mortality_events += int(summary.get("mortality_events") or 0)
            try:
                max_crop_days = max(max_crop_days, int(summary.get("crop_days") or 0))
            except Exception:
                pass
        i += 1

    overall_start_epoch = min(start_epochs) if start_epochs else None
    overall_end_epoch = max(end_epochs) if end_epochs else None
    crop_days = max_crop_days or None
    if overall_start_epoch is not None and overall_end_epoch is not None:
        try:
            start_date = datetime.fromtimestamp(int(overall_start_epoch)).date()
            end_date = datetime.fromtimestamp(int(overall_end_epoch)).date()
            crop_days = max(1, (end_date - start_date).days + 1)
        except Exception:
            pass

    mortality_pct = None
    feed_per_bird = None
    water_per_bird = None
    if total_birds_placed > 0:
        mortality_pct = (float(total_mortality) / float(total_birds_placed)) * 100.0
        feed_per_bird = float(total_feed) / float(total_birds_placed)
        water_per_bird = float(total_water) / float(total_birds_placed)

    avg_daily_feed = None
    avg_daily_water = None
    if crop_days not in [None, 0]:
        avg_daily_feed = float(total_feed) / float(crop_days)
        avg_daily_water = float(total_water) / float(crop_days)

    return {
        "farm_name": farm_name,
        "farm_id": farm_id,
        "crop_id": int(crop_id),
        "crop_code": fmt_crop_code(crop_id, overall_start_epoch),
        "start_epoch": overall_start_epoch,
        "end_epoch": overall_end_epoch,
        "start_label": datetime.fromtimestamp(overall_start_epoch).strftime("%d %b %Y %H:%M") if overall_start_epoch is not None else "--",
        "end_label": datetime.fromtimestamp(overall_end_epoch).strftime("%d %b %Y %H:%M") if overall_end_epoch is not None else "--",
        "crop_days": crop_days,
        "participating_sheds": len(shed_rows),
        "birds_placed": total_birds_placed if shed_rows else None,
        "birds_remaining_end": total_birds_remaining if shed_rows else None,
        "mortality_total": total_mortality if shed_rows else None,
        "mortality_pct": mortality_pct,
        "manual_feed_adjustment_kg": total_manual_feed_adjustment_kg if shed_rows else None,
        "total_feed": total_feed if shed_rows else None,
        "feed_bin_end_kg": total_feed_bin_end_kg if shed_rows and has_feed_bin_end else None,
        "total_water": total_water if shed_rows else None,
        "avg_daily_feed": avg_daily_feed,
        "avg_daily_water": avg_daily_water,
        "feed_per_bird": feed_per_bird,
        "water_per_bird": water_per_bird,
        "complete_days": total_complete_days,
        "mortality_events": total_mortality_events,
        "shed_rows": shed_rows,
    }


def _xlsx_col_name(index):
    out = ""
    value = int(index) + 1
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        out = chr(65 + remainder) + out
    return out


def _xlsx_cell_xml(row_idx, col_idx, value):
    ref = "%s%d" % (_xlsx_col_name(col_idx), row_idx)
    if value in [None, ""]:
        return '<c r="%s"/>' % ref
    if isinstance(value, bool):
        return '<c r="%s" t="b"><v>%d</v></c>' % (ref, 1 if value else 0)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return '<c r="%s"><v>%s</v></c>' % (ref, value)
    text = xml_escape(str(value), {'"': "&quot;", "'": "&apos;"})
    return '<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, text)


def _xlsx_col_widths(rows):
    max_cols = 0
    i = 0
    while i < len(rows):
        try:
            max_cols = max(max_cols, len(rows[i]))
        except Exception:
            pass
        i += 1

    widths = []
    col_idx = 0
    while col_idx < max_cols:
        max_len = 0
        row_idx = 0
        while row_idx < len(rows):
            value = rows[row_idx][col_idx] if col_idx < len(rows[row_idx]) else ""
            if value in [None, ""]:
                text = ""
            elif isinstance(value, float):
                text = ("%.4f" % value).rstrip("0").rstrip(".")
            else:
                text = str(value)
            line_len = 0
            for part in text.splitlines() or [""]:
                line_len = max(line_len, len(part))
            max_len = max(max_len, line_len)
            row_idx += 1

        if col_idx == 0:
            width = max(16, min(max_len + 3, 28))
        else:
            width = max(12, min(max_len + 3, 32))
        widths.append(width)
        col_idx += 1
    return widths


def _xlsx_sheet_xml(rows):
    col_widths = _xlsx_col_widths(rows)
    row_xml = []
    row_idx = 1
    while row_idx <= len(rows):
        values = rows[row_idx - 1]
        cell_xml = []
        col_idx = 0
        while col_idx < len(values):
            cell_xml.append(_xlsx_cell_xml(row_idx, col_idx, values[col_idx]))
            col_idx += 1
        row_xml.append('<row r="%d">%s</row>' % (row_idx, "".join(cell_xml)))
        row_idx += 1

    cols_xml = []
    col_idx = 0
    while col_idx < len(col_widths):
        width = col_widths[col_idx]
        cols_xml.append('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (col_idx + 1, col_idx + 1, width))
        col_idx += 1

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetFormatPr defaultRowHeight="15"/>'
        '%s'
        '<sheetData>%s</sheetData>'
        '</worksheet>'
    ) % (('<cols>%s</cols>' % "".join(cols_xml)) if cols_xml else "", "".join(row_xml))


def _xlsx_safe_sheet_name(name, used_names):
    cleaned = re.sub(r'[\[\]\:\*\?\/\\\\]', "-", str(name or "").strip()) or "Sheet"
    cleaned = cleaned[:31] or "Sheet"
    candidate = cleaned
    suffix = 2
    while candidate in used_names:
        tail = " %d" % suffix
        candidate = (cleaned[: max(0, 31 - len(tail))] + tail) or ("Sheet %d" % suffix)
        suffix += 1
    used_names.add(candidate)
    return candidate


def build_simple_xlsx_bytes(sheets):
    workbook_parts = []
    rel_parts = []
    content_override_parts = []
    sheet_files = []
    used_names = set()

    i = 0
    while i < len(sheets):
        sheet = sheets[i]
        sheet_name = _xlsx_safe_sheet_name(sheet.get("name"), used_names)
        sheet_xml = _xlsx_sheet_xml(sheet.get("rows") or [])
        sheet_path = "xl/worksheets/sheet%d.xml" % (i + 1)
        sheet_files.append((sheet_path, sheet_xml))
        workbook_parts.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (xml_escape(sheet_name, {'"': "&quot;", "'": "&apos;"}), i + 1, i + 1))
        rel_parts.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1))
        content_override_parts.append('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1))
        i += 1

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>%s</sheets>'
        '</workbook>'
    ) % "".join(workbook_parts)
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
    ) % "".join(rel_parts)
    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        '</Relationships>'
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '%s'
        '</Types>'
    ) % "".join(content_override_parts)
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>Crop Summary</dc:title>'
        '<dc:creator>Cherry Dene Dashboard</dc:creator>'
        '<cp:lastModifiedBy>Cherry Dene Dashboard</cp:lastModifiedBy>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
        '</cp:coreProperties>'
    ) % (now_iso, now_iso)
    app_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>Cherry Dene Dashboard</Application>'
        '</Properties>'
    )

    buffer = tempfile.SpooledTemporaryFile()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", root_rels_xml)
        zf.writestr("docProps/core.xml", core_xml)
        zf.writestr("docProps/app.xml", app_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        i = 0
        while i < len(sheet_files):
            path, payload = sheet_files[i]
            zf.writestr(path, payload)
            i += 1
    buffer.seek(0)
    payload = buffer.read()
    buffer.close()
    return payload


def crop_report_metric_rows(summary):
    rows = [
        ["Crop ID", summary.get("crop_code")],
        ["Status", summary.get("status", "Ended")],
        ["Start", summary.get("start_label")],
        ["End", summary.get("end_label")],
        ["Crop Days", summary.get("crop_days")],
        ["Birds Placed", summary.get("birds_placed")],
        ["Birds Remaining", summary.get("birds_remaining_end")],
        ["Mortality", summary.get("mortality_total")],
        ["Mortality %", round(summary.get("mortality_pct"), 2) if summary.get("mortality_pct") is not None else None],
        ["Manual Feed Recorded KG", round(summary.get("manual_feed_adjustment_kg"), 2) if summary.get("manual_feed_adjustment_kg") is not None else None],
        ["Total Feed KG", round(summary.get("total_feed"), 2) if summary.get("total_feed") is not None else None],
        ["Feed Left In Bin KG", round(summary.get("feed_bin_end_kg"), 2) if summary.get("feed_bin_end_kg") is not None else None],
        ["Total Water L", round(summary.get("total_water"), 2) if summary.get("total_water") is not None else None],
        ["Avg Daily Feed KG", round(summary.get("avg_daily_feed"), 2) if summary.get("avg_daily_feed") is not None else None],
        ["Avg Daily Water L", round(summary.get("avg_daily_water"), 2) if summary.get("avg_daily_water") is not None else None],
        ["Feed Per Bird KG", round(summary.get("feed_per_bird"), 4) if summary.get("feed_per_bird") is not None else None],
        ["Water Per Bird L", round(summary.get("water_per_bird"), 4) if summary.get("water_per_bird") is not None else None],
        ["Complete Days", summary.get("complete_days")],
        ["Mortality Events", summary.get("mortality_events")],
    ]
    return rows


def build_crop_report_workbook(crop_id):
    farm_summary = build_farm_crop_summary(crop_id)
    generated_ts = int(time.time())

    sheets = []
    farm_rows = [
        ["Farm", farm_summary.get("farm_name")],
        ["Farm ID", farm_summary.get("farm_id") or "--"],
        ["Crop", farm_summary.get("crop_code")],
        ["Generated", datetime.fromtimestamp(generated_ts).strftime("%d %b %Y %H:%M")],
    ]
    farm_rows.extend(crop_report_metric_rows(farm_summary))
    farm_rows.append([])
    farm_rows.append([
        "Shed",
        "Crop",
        "Start",
        "End",
        "Crop Days",
        "Birds Placed",
        "Birds Remaining",
        "Mortality",
        "Mortality %",
        "Manual Feed Recorded KG",
        "Feed KG",
        "Feed Left In Bin KG",
        "Water L",
        "Avg Feed/Day",
        "Avg Water/Day",
        "Feed/Bird",
        "Water/Bird",
        "Complete Days",
        "Mortality Events",
    ])

    i = 0
    shed_rows = farm_summary.get("shed_rows", [])
    while i < len(shed_rows):
        row = shed_rows[i]
        summary = row["summary"]
        farm_rows.append([
            row["shed_name"],
            summary.get("crop_code"),
            summary.get("start_label"),
            summary.get("end_label"),
            summary.get("crop_days"),
            summary.get("birds_placed"),
            summary.get("birds_remaining_end"),
            summary.get("mortality_total"),
            round(summary.get("mortality_pct"), 2) if summary.get("mortality_pct") is not None else None,
            round(summary.get("manual_feed_adjustment_kg"), 2) if summary.get("manual_feed_adjustment_kg") is not None else None,
            round(summary.get("total_feed"), 2) if summary.get("total_feed") is not None else None,
            round(summary.get("feed_bin_end_kg"), 2) if summary.get("feed_bin_end_kg") is not None else None,
            round(summary.get("total_water"), 2) if summary.get("total_water") is not None else None,
            round(summary.get("avg_daily_feed"), 2) if summary.get("avg_daily_feed") is not None else None,
            round(summary.get("avg_daily_water"), 2) if summary.get("avg_daily_water") is not None else None,
            round(summary.get("feed_per_bird"), 4) if summary.get("feed_per_bird") is not None else None,
            round(summary.get("water_per_bird"), 4) if summary.get("water_per_bird") is not None else None,
            summary.get("complete_days"),
            summary.get("mortality_events"),
        ])
        i += 1
    sheets.append({"name": "Farm Summary", "rows": farm_rows})

    i = 0
    while i < len(shed_rows):
        row = shed_rows[i]
        summary = row["summary"]
        rows = [
            ["Shed", row["shed_name"]],
            ["Crop", summary.get("crop_code")],
            [],
        ]
        rows.extend(crop_report_metric_rows(summary))
        rows.append([])
        rows.append(["Day", "Water L", "Feed KG", "Running Water L", "Running Feed KG"])
        daily_rows = summary.get("daily_rows", [])
        j = 0
        while j < len(daily_rows):
            daily = daily_rows[j]
            rows.append([
                daily.get("label"),
                round(float(daily.get("water") or 0.0), 2),
                round(float(daily.get("feed") or 0.0), 2),
                round(float(daily.get("running_water") or 0.0), 2),
                round(float(daily.get("running_feed") or 0.0), 2),
            ])
            j += 1
        sheets.append({"name": "Shed %d" % row["shed_no"], "rows": rows})
        i += 1

    workbook_bytes = build_simple_xlsx_bytes(sheets)
    return farm_summary, workbook_bytes


def _filename_slug(value):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip()).strip("-").lower()
    return slug or "farm"


def crop_report_output_path(farm_summary):
    farm_slug = _filename_slug(farm_summary.get("farm_name"))
    crop_slug = _filename_slug(farm_summary.get("crop_code") or ("crop-%s" % farm_summary.get("crop_id")))
    return os.path.join(crop_reports_root(), "%s-%s-summary.xlsx" % (farm_slug, crop_slug))


def crop_report_email_config():
    cfg = load_office_config()
    recipients = cfg.get("crop_report_email_to")
    if not recipients:
        recipients = cfg.get("report_email_to")
    if isinstance(recipients, str):
        recipients = [part.strip() for part in re.split(r"[,;\n]+", recipients) if part.strip()]
    elif isinstance(recipients, list):
        recipients = [str(item).strip() for item in recipients if str(item).strip()]
    else:
        recipients = []

    def first_value(*keys, default=""):
        i = 0
        while i < len(keys):
            value = cfg.get(keys[i])
            if value not in [None, ""]:
                return value
            i += 1
        return default

    return {
        "enabled": str(first_value("crop_report_email_enabled", "report_email_enabled", default="1")).strip().lower() not in ["0", "false", "no", "off"],
        "smtp_host": str(first_value("crop_report_smtp_host", "report_smtp_host", default="")).strip(),
        "smtp_port": int(first_value("crop_report_smtp_port", "report_smtp_port", default=587) or 587),
        "smtp_username": str(first_value("crop_report_smtp_username", "report_smtp_username", default="")).strip(),
        "smtp_password": str(first_value("crop_report_smtp_password", "report_smtp_password", default="")),
        "smtp_use_tls": str(first_value("crop_report_smtp_use_tls", "report_smtp_use_tls", default="1")).strip().lower() not in ["0", "false", "no", "off"],
        "smtp_use_ssl": str(first_value("crop_report_smtp_use_ssl", "report_smtp_use_ssl", default="0")).strip().lower() in ["1", "true", "yes", "on"],
        "email_from": str(first_value("crop_report_email_from", "report_email_from", default="")).strip(),
        "email_to": recipients,
    }


def send_crop_report_email(farm_summary, report_path):
    cfg = crop_report_email_config()
    if not cfg.get("enabled", True):
        return False, "Email sending disabled in office config"
    if not cfg.get("smtp_host"):
        return False, "No SMTP host configured"
    if not cfg.get("email_to"):
        return False, "No crop report recipients configured"

    with open(report_path, "rb") as f:
        payload = f.read()

    subject = "%s %s End of Crop Summary" % (farm_summary.get("farm_name") or "Farm", farm_summary.get("crop_code") or ("Crop %s" % farm_summary.get("crop_id")))
    body = "\n".join([
        "Attached is the end-of-crop summary workbook.",
        "",
        "Farm: %s" % (farm_summary.get("farm_name") or "--"),
        "Crop: %s" % (farm_summary.get("crop_code") or "--"),
        "Participating sheds: %s" % (farm_summary.get("participating_sheds") or 0),
        "Manual feed recorded (kg): %s" % (round(float(farm_summary.get("manual_feed_adjustment_kg") or 0.0), 2)),
        "Total feed (kg): %s" % (round(float(farm_summary.get("total_feed") or 0.0), 2)),
        "Feed left in bin (kg): %s" % (round(float(farm_summary.get("feed_bin_end_kg") or 0.0), 2)),
        "Total water (L): %s" % (round(float(farm_summary.get("total_water") or 0.0), 2)),
        "",
        "Generated by Cherry Dene Dashboard.",
    ])

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("email_from") or cfg.get("smtp_username") or "noreply@localhost"
    msg["To"] = ", ".join(cfg.get("email_to") or [])
    msg.set_content(body)
    msg.add_attachment(
        payload,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(report_path),
    )

    smtp_host = cfg.get("smtp_host")
    smtp_port = int(cfg.get("smtp_port") or 587)
    smtp_username = cfg.get("smtp_username")
    smtp_password = cfg.get("smtp_password")

    if cfg.get("smtp_use_ssl"):
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
            if smtp_username:
                server.login(smtp_username, smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.ehlo()
            if cfg.get("smtp_use_tls"):
                server.starttls()
                server.ehlo()
            if smtp_username:
                server.login(smtp_username, smtp_password)
            server.send_message(msg)
    return True, "Email sent"


def run_crop_end_report(crop_id):
    status = load_crop_report_status()
    key = str(crop_id)
    entry = status.get(key)
    if not isinstance(entry, dict):
        entry = {}
    entry["status"] = "processing"
    entry["processing_ts"] = int(time.time())
    status[key] = entry
    save_crop_report_status(status)

    try:
        farm_summary, workbook_bytes = build_crop_report_workbook(crop_id)
        report_path = crop_report_output_path(farm_summary)
        write_bytes_file_atomic(report_path, workbook_bytes)

        email_ok = False
        email_message = "Email not attempted"
        try:
            email_ok, email_message = send_crop_report_email(farm_summary, report_path)
        except Exception as exc:
            email_ok = False
            email_message = str(exc)

        status = load_crop_report_status()
        entry = status.get(key)
        if not isinstance(entry, dict):
            entry = {}
        entry.update({
            "status": "emailed" if email_ok else "generated",
            "generated_ts": int(time.time()),
            "report_path": report_path,
            "crop_code": farm_summary.get("crop_code"),
            "farm_name": farm_summary.get("farm_name"),
            "email_sent": bool(email_ok),
            "email_message": email_message,
        })
        status[key] = entry
        save_crop_report_status(status)
        log_event("office", "crop_report_ready", "Crop summary workbook generated", detail=report_path)
        if email_ok:
            log_event("office", "crop_report_emailed", "Crop summary workbook emailed", detail=farm_summary.get("crop_code"))
        else:
            log_event("office", "crop_report_email_skipped", "Crop summary workbook not emailed", detail=email_message)
    except Exception as exc:
        status = load_crop_report_status()
        entry = status.get(key)
        if not isinstance(entry, dict):
            entry = {}
        entry.update({
            "status": "failed",
            "failed_ts": int(time.time()),
            "error": str(exc),
        })
        status[key] = entry
        save_crop_report_status(status)
        log_event("office", "crop_report_failed", "Crop summary workbook failed", detail=str(exc))


def queue_crop_end_report(crop_id):
    try:
        crop_id = int(crop_id)
    except Exception:
        return False

    status = load_crop_report_status()
    key = str(crop_id)
    existing = status.get(key)
    if isinstance(existing, dict) and existing.get("status") in ["queued", "processing", "generated", "emailed"]:
        return False

    status[key] = {
        "status": "queued",
        "queued_ts": int(time.time()),
    }
    save_crop_report_status(status)

    threading.Thread(target=run_crop_end_report, args=(crop_id,), daemon=True).start()
    return True


def crop_report_status_ts(rec):
    if not isinstance(rec, dict):
        return 0
    keys = ["generated_ts", "processing_ts", "queued_ts", "failed_ts", "last_resent_ts"]
    i = 0
    while i < len(keys):
        try:
            value = int(rec.get(keys[i]) or 0)
        except Exception:
            value = 0
        if value > 0:
            return value
        i += 1
    return 0


def list_crop_report_rows():
    status = load_crop_report_status()
    rows = []
    for key, rec in status.items():
        if not isinstance(rec, dict):
            continue
        try:
            crop_id = int(key)
        except Exception:
            continue
        report_path = str(rec.get("report_path") or "").strip()
        path_exists = bool(report_path) and os.path.isfile(report_path)
        ts = crop_report_status_ts(rec)
        rows.append({
            "crop_id": crop_id,
            "crop_code": str(rec.get("crop_code") or ("Crop %s" % crop_id)),
            "farm_name": str(rec.get("farm_name") or farm_identity()[0]),
            "status": str(rec.get("status") or "--"),
            "generated_label": datetime.fromtimestamp(ts).strftime("%d %b %Y %H:%M:%S") if ts else "--",
            "email_sent": bool(rec.get("email_sent", False)),
            "email_message": str(rec.get("email_message") or "--"),
            "report_path": report_path,
            "report_name": os.path.basename(report_path) if report_path else "--",
            "file_exists": path_exists,
            "sort_ts": ts,
        })
    rows.sort(key=lambda row: (row.get("sort_ts") or 0, row.get("crop_id") or 0), reverse=True)
    return rows


def crop_report_record(crop_id):
    status = load_crop_report_status()
    rec = status.get(str(int(crop_id)))
    return rec if isinstance(rec, dict) else {}


def ensure_crop_report_file(crop_id, force_rebuild=False):
    rec = crop_report_record(crop_id)
    report_path = str(rec.get("report_path") or "").strip()
    if not force_rebuild and report_path and os.path.isfile(report_path):
        return report_path

    farm_summary, workbook_bytes = build_crop_report_workbook(crop_id)
    report_path = crop_report_output_path(farm_summary)
    write_bytes_file_atomic(report_path, workbook_bytes)

    status = load_crop_report_status()
    entry = status.get(str(int(crop_id)))
    if not isinstance(entry, dict):
        entry = {}
    entry.update({
        "status": entry.get("status") or "generated",
        "generated_ts": int(time.time()),
        "report_path": report_path,
        "crop_code": farm_summary.get("crop_code"),
        "farm_name": farm_summary.get("farm_name"),
    })
    status[str(int(crop_id))] = entry
    save_crop_report_status(status)
    return report_path


def resend_crop_report(crop_id):
    crop_id = int(crop_id)
    farm_summary = build_farm_crop_summary(crop_id)
    report_path = ensure_crop_report_file(crop_id, force_rebuild=True)
    email_ok, email_message = send_crop_report_email(farm_summary, report_path)

    status = load_crop_report_status()
    entry = status.get(str(crop_id))
    if not isinstance(entry, dict):
        entry = {}
    entry.update({
        "status": "emailed" if email_ok else entry.get("status") or "generated",
        "last_resent_ts": int(time.time()),
        "email_sent": bool(email_ok),
        "email_message": email_message,
        "report_path": report_path,
        "crop_code": farm_summary.get("crop_code"),
        "farm_name": farm_summary.get("farm_name"),
    })
    status[str(crop_id)] = entry
    save_crop_report_status(status)
    return email_ok, email_message, report_path


def get_active_crop_id_for_shed(shed_name):
    crop = active_crop_record_for_shed(shed_name)
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

        ended_entries = shed_rec.get("ended_entries", {})
        if not isinstance(ended_entries, dict):
            ended_entries = {}
        clean_ended_entries = {}
        for key, value in ended_entries.items():
            try:
                dest_shed = int(key)
                ended_ts = int(value or 0)
            except Exception:
                continue
            if ended_ts > 0:
                clean_ended_entries[str(dest_shed)] = ended_ts

        result[shed_name] = {"entries": clean_entries, "ended_entries": clean_ended_entries}

    return result


def save_shed_entries_state(state):
    path = os.path.join(DATA_DIR, "shed_entries.json")
    write_json_file_atomic(path, state)


def ensure_shed_entry_bucket(state, shed_name):
    if shed_name not in state or not isinstance(state.get(shed_name), dict):
        state[shed_name] = {"entries": {}, "ended_entries": {}}
    if "entries" not in state[shed_name] or not isinstance(state[shed_name].get("entries"), dict):
        state[shed_name]["entries"] = {}
    if "ended_entries" not in state[shed_name] or not isinstance(state[shed_name].get("ended_entries"), dict):
        state[shed_name]["ended_entries"] = {}
    return state[shed_name]["entries"]


def active_entry_location_for_dest(state, dest_shed, exclude_shed_name=None):
    i = 0
    while i < len(SHED_NUMBERS):
        shed_name = shed_name_from_number(SHED_NUMBERS[i])
        if exclude_shed_name is not None and str(shed_name) == str(exclude_shed_name):
            i += 1
            continue
        entries = ensure_shed_entry_bucket(state, shed_name)
        rec = clean_entry_record(entries.get(str(dest_shed), {}))
        if rec["bird_count"] > 0 and rec["crop_active"] == 1:
            return shed_name
        i += 1
    return None


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
        placement_input_epoch = placement_epoch if (crop_active == 1 and bird_count > 0) else None
        rows.append({
            "dest_shed": dest_shed,
            "bird_count": bird_count,
            "crop_active": crop_active,
            "placement_epoch": placement_epoch,
            "placement_str": placement_str,
            "placement_input_value": fmt_datetime_local_value(placement_input_epoch),
            "crop_id": rec.get("crop_id"),
            "crop_code": fmt_crop_code(rec.get("crop_id"), placement_epoch),
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

    if updated_ts:
        try:
            tt = datetime.fromtimestamp(int(updated_ts))
            updated_str = tt.strftime("%d %b %H:%M:%S")
        except Exception:
            updated_str = "--"
    else:
        updated_str = "--"

    sync_age = controller_sync_age(meta)
    if sync_age is None:
        sync_pill_class = "sync-missing"
        sync_pill_text = "SHED SYNC --"
    elif sync_age <= 30:
        sync_pill_class = "sync-ok"
        sync_pill_text = "SHED SYNC OK • %ss" % sync_age
    else:
        sync_pill_class = "sync-stale"
        sync_pill_text = "SHED SYNC STALE • %ss" % sync_age

    is_online = controller_online(meta)
    tile_state = "online" if is_online and bool(live) else "offline"

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
    total_mortality = 0
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
            shed_mortality = mortality_total_for_shed_crop(shed_name, current_crop_id)
            total_mortality += shed_mortality
            total_birds_placed += shed_mortality

        crop = active_crop_record_for_shed(shed_name)
        try:
            active_crop_id = int(crop.get("crop_id"))
        except Exception:
            active_crop_id = None

        hourly_rows = get_hourly_history_for_shed(shed_name, max_points=0, crop_id=active_crop_id, include_manual_feed=True)

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
    mortality_pct = None
    try:
        if total_birds_placed > 0 and total_mortality > 0:
            mortality_pct = (float(total_mortality) / float(total_birds_placed)) * 100.0
    except Exception:
        mortality_pct = None

    return {
        "tile_state": tile_state,
        "birds_placed": fmt_value(total_birds_placed if total_birds_placed > 0 else None, "i"),
        "birds_remaining": fmt_value(total_birds_remaining if total_birds_remaining > 0 else None, "i"),
        "mortality_total": fmt_value(total_mortality if total_mortality > 0 else None, "i"),
        "mortality_pct": fmt_value(mortality_pct, "f1"),
        "mortality_display": (
            "%s (%s%%)" % (fmt_value(total_mortality, "i"), fmt_value(mortality_pct, "f1"))
            if total_mortality > 0 and mortality_pct is not None
            else fmt_value(total_mortality if total_mortality > 0 else None, "i")
        ),
        "water": fmt_value(total_water if total_water > 0 else None, "f0"),
        "feed": fmt_value(total_feed if total_feed > 0 else None, "f1"),
        "farm_crop_id": fmt_crop_code(farm_crop.get("current_crop_id"), current_crop_epoch),
    }


def build_rows():
    ensure_data_dir()
    now_ts = int(time.time())

    live_map = latest_live_by_shed()
    alarms_map = active_alarms_by_shed()
    controller_meta_map = load_controller_meta()
    office_env_limits_map = office_environment_limits_map()
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
        is_online = controller_online(controller_meta)
        operational_display_active = is_online and has_active_entry

        try:
            active_crop_id = int(crop.get("crop_id"))
        except Exception:
            active_crop_id = None

        days = get_daily_history_for_shed(shed, max_days=40, crop_id=active_crop_id, include_manual_feed=True)
        sensor_days = get_daily_history_for_shed(shed, max_days=40, crop_id=active_crop_id, include_manual_feed=False)
        all_crop_hourly = get_hourly_history_for_shed(shed, max_points=0, crop_id=active_crop_id, include_manual_feed=True)

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
        mortality_total = mortality_total_for_shed_crop(shed, active_crop_id) if active_crop_id is not None else None
        try:
            mortality_total_i = int(mortality_total or 0)
        except Exception:
            mortality_total_i = 0
        birds_placed = birds + mortality_total_i if (birds > 0 or mortality_total_i > 0) else None
        mortality_pct = None
        try:
            if birds_placed not in [None, 0] and mortality_total_i > 0:
                mortality_pct = (float(mortality_total_i) / float(birds_placed)) * 100.0
        except Exception:
            mortality_pct = None
        allocation_text = entry_summary_text(shed_no, active_entries)

        crop_id = crop.get("crop_id")
        placement_epoch = crop.get("placement_epoch")
        crop_active = crop.get("crop_active")

        bird_age = None
        try:
            if placement_epoch is not None and int(crop_active) == 1:
                bird_age = crop_age_days(placement_epoch)
        except Exception:
            bird_age = None

        yesterday_water = None
        yesterday_feed = None
        if len(days) >= 1:
            yesterday_water = days[-1].get("water")
            yesterday_feed = days[-1].get("feed")

        recent_feed_days = []
        d = 0
        while d < len(sensor_days):
            val = sensor_days[d].get("feed")
            if val is not None:
                recent_feed_days.append(val)
            d += 1

        avg_feed_day_kg = average_last_n(recent_feed_days, 3)

        l_per_bird_yday = None
        kg_per_bird_yday = None

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

        temp_c = live.get("temp_c")
        rh_pct = live.get("rh_pct")
        feed_kg = live.get("feed_kg")
        updated_ts = live.get("ts")
        water_lpm = live.get("water_lpm")
        if not operational_display_active:
            temp_c = None
            rh_pct = None

        env_limits = environment_limits_for_shed(shed_no, office_env_limits_map, controller_meta)
        temp_glow = range_glow_class(
            temp_c,
            env_limits["temp_low_c"],
            env_limits["temp_high_c"],
            env_limits["temp_amber_margin_c"],
            prefix="env",
        )
        rh_glow = range_glow_class(
            rh_pct,
            env_limits["rh_low_pct"],
            env_limits["rh_high_pct"],
            env_limits["rh_amber_margin_pct"],
            prefix="env",
        )

        alarm_active = len(alarms) > 0
        alarm_key = alarms[0].get("alarm_key", "") if alarm_active else ""
        alarm_msg = alarms[0].get("message", "") if alarm_active else ""

        try:
            water_lpm_f = float(water_lpm) if water_lpm is not None else None
        except Exception:
            water_lpm_f = None

        water_glow = low_threshold_glow_class(
            water_lpm_f,
            env_limits["water_low_lpm"],
            env_limits["water_amber_buffer_lpm"],
            "flow",
        )

        try:
            feed_val = float(feed_kg) if feed_kg is not None else None
        except Exception:
            feed_val = None

        feed_glow = low_threshold_glow_class(
            feed_val,
            env_limits["feed_low_kg"],
            env_limits["feed_amber_buffer_kg"],
            "feed",
        )

        if updated_ts:
            try:
                tt = datetime.fromtimestamp(int(updated_ts))
                updated_str = tt.strftime("%d %b %H:%M:%S")
            except Exception:
                updated_str = "--"
        else:
            updated_str = "--"

        runout_est = estimate_runout_from_average(feed_kg, avg_feed_day_kg)
        sync_age = controller_sync_age(controller_meta)
        if sync_age is None:
            sync_pill_class = "sync-missing"
            sync_pill_text = "SHED SYNC --"
        elif sync_age <= 30:
            sync_pill_class = "sync-ok"
            sync_pill_text = "SHED SYNC OK • %ss" % sync_age
        else:
            sync_pill_class = "sync-stale"
            sync_pill_text = "SHED SYNC STALE • %ss" % sync_age

        tile_state = "online" if is_online and bool(live) else "offline"
        card_state = "online" if is_online and has_active_entry else "offline"
        auger_tiles = dashboard_auger_tiles(
            controller_meta,
            now_ts=now_ts,
            force_red=not operational_display_active,
        )
        lighting_visible = True
        lighting_on = bool(controller_meta.get("lighting_on", False))

        rows.append({
            "shed": shed,
            "shed_no": shed_no,
            "has_data": bool(live) or bool(days) or bool(crop) or bool(active_entries),
            "has_active_entry": has_active_entry,
            "tile_state": tile_state,
            "card_state": card_state,
            "temp_c": fmt_value(temp_c, "f1"),
            "temp_glow": temp_glow,
            "rh_pct": fmt_value(rh_pct, "f0"),
            "rh_glow": rh_glow,
            "feed_kg": fmt_value(feed_kg, "f0"),
            "feed_glow": feed_glow,
            "water_lpm": fmt_value(water_lpm, "f2"),
            "water_glow": water_glow,
            "auger_tiles": auger_tiles,
            "auger_count": len(auger_tiles),
            "lighting_visible": lighting_visible,
            "lighting_on": lighting_on,
            "lighting_tile_class": "lighting-on" if lighting_on else "lighting-off",
            "lighting_status_text": "ON" if lighting_on else "OFF",
            "crop_id": fmt_crop_code(crop_id, placement_epoch),
            "farm_crop_id": fmt_crop_code(current_farm_crop_id, current_farm_crop_epoch),
            "bird_count": fmt_value(birds if birds > 0 else None, "i"),
            "birds_remaining": fmt_value(birds if birds > 0 else None, "i"),
            "birds_placed": fmt_value(birds_placed, "i"),
            "bird_age": fmt_value(bird_age, "i"),
            "water_7to7": fmt_value(yesterday_water, "f0"),
            "feed_7to7": fmt_value(yesterday_feed, "f1"),
            "l_per_bird": fmt_value(l_per_bird_yday, "f3"),
            "kg_per_bird": fmt_value(kg_per_bird_yday, "f3"),
            "runout_est": runout_est,
            "updated": updated_str,
            "alarm_active": alarm_active,
            "alarm_key": alarm_key,
            "alarm_msg": alarm_msg,
            "total_water_to_date": fmt_value(total_water_to_date, "f0"),
            "total_feed_to_date": fmt_value(total_feed_to_date, "f1"),
            "allocation_text": allocation_text,
            "mortality_total": fmt_value(mortality_total, "i"),
            "mortality_pct": fmt_value(mortality_pct, "f1"),
            "mortality_display": (
                "%s (%s%%)" % (fmt_value(mortality_total, "i"), fmt_value(mortality_pct, "f1"))
                if mortality_total_i > 0 and mortality_pct is not None
                else fmt_value(mortality_total, "i")
            ),
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
        "host_ips": host_ipv4_display(),
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
        .topbar-actions {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            min-width: 0;
        }
        .topbar-right {
            justify-self: end;
        }
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
            min-width: 0;
            max-width: 100%;
            box-sizing: border-box;
            overflow-wrap: anywhere;
            word-break: break-word;
            white-space: normal;
        }
        .settings-link.notify-on {
            border-color: #35d07f;
            color: #d9ffe8;
            box-shadow:
                0 0 8px rgba(53,208,127,0.65),
                0 0 16px rgba(53,208,127,0.30);
        }
        .settings-link.notify-blocked {
            border-color: #ff7a7a;
            color: #ffd8d8;
            box-shadow:
                0 0 8px rgba(255,122,122,0.65),
                0 0 16px rgba(255,122,122,0.30);
        }
        .settings-link.notify-off {
            border-color: #ffd06a;
            color: #fff0c7;
        }
        .notify-status {
            margin-bottom: 12px;
            text-align: center;
            font-size: 13px;
            color: #d7d7d7;
            min-height: 18px;
        }
        .notify-status.state-on {
            color: #d9ffe8;
            text-shadow:
                0 0 8px rgba(53,208,127,0.45);
        }
        .notify-status.state-blocked {
            color: #ffd8d8;
            text-shadow:
                0 0 8px rgba(255,122,122,0.45);
        }
        .notify-status.state-off {
            color: #fff0c7;
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
        .access-ip {
            margin-top: 6px;
            font-size: 13px;
            color: #d2d2d2;
            text-align: right;
            word-break: break-word;
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
            min-width: 0;
            overflow: hidden;
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
            gap: 8px;
            min-width: 0;
        }
        .head-left {
            display: flex;
            flex-direction: column;
            gap: 2px;
            align-items: flex-start;
            min-width: 0;
            flex: 1 1 auto;
        }
        .shed {
            font-size: 22px;
            font-weight: bold;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .birds-top {
            font-size: 14px;
            color: #d9d9d9;
            line-height: 1.3;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .alloc-top {
            font-size: 13px;
            color: #d6d6d6;
            line-height: 1.25;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .badge-wrap {
            display: flex;
            flex-direction: column;
            gap: 4px;
            align-items: flex-end;
            min-width: 0;
            flex: 0 1 auto;
        }
        .badge {
            font-size: 11px;
            padding: 3px 7px;
            border-radius: 8px;
            border: 1px solid #8d8d8d;
            color: #f0f0f0;
            background: transparent;
            overflow-wrap: anywhere;
            word-break: break-word;
            text-align: center;
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
            min-width: 0;
        }
        .mini-label {
            font-size: 11px;
            color: #d0d0d0;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .mini-val {
            font-size: 20px;
            font-weight: bold;
            line-height: 1.1;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .big-pair {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 8px;
        }
        .big-triple {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
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
        .compact-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 8px;
        }
        .footer-strip {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
            margin-top: auto;
        }
        .footer-stat {
            background: #686868;
            border: 1px solid #858585;
            border-radius: 8px;
            padding: 7px 8px;
            min-width: 0;
        }
        .footer-stat-label {
            font-size: 10px;
            color: #d2d2d2;
        }
        .footer-stat-value {
            font-size: 14px;
            font-weight: bold;
            margin-top: 2px;
            line-height: 1.2;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .metric-grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 6px 8px;
        }
        .metric-columns {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 6px;
        }
        .metric-water { order: 0; }
        .metric-feed { order: 0; }
        .metric-neutral { order: 0; }
        .metric-runout { order: 0; }
        .metric-mortality { order: 0; }
        .metric-water-daily { order: 0; }
        .metric-feed-daily { order: 0; }
        .metric-water-bird { order: 0; }
        .metric-feed-bird { order: 0; }
        .metric-water-total { order: 0; }
        .metric-feed-total { order: 0; }
        .metric-lighting {
            text-align: left;
        }
        .metric-lighting-top .metric-val {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            margin-top: 0;
            padding-top: 9px;
        }
        .metric-lighting-top .metric-val .lighting-top-text {
            font-size: 12px;
            font-weight: 700;
            line-height: 1;
        }
        .lighting-top-icon {
            font-size: 20px;
            line-height: 1;
            transition: opacity 120ms ease, filter 120ms ease;
        }
        .lighting-top-icon.is-on {
            opacity: 1;
            filter: drop-shadow(0 0 8px rgba(255, 214, 106, 0.75));
        }
        .lighting-top-icon.is-off {
            opacity: 0.65;
            filter: grayscale(1) brightness(0.75);
        }
        .metric-lighting.lighting-on {
            border: 2px solid #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .metric-lighting.lighting-off {
            border: 2px solid #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
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
            min-width: 0;
        }
        .metric-label {
            font-size: 10px;
            color: #d2d2d2;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .metric-val {
            font-size: 16px;
            font-weight: bold;
            line-height: 1.1;
            margin-top: 2px;
            overflow-wrap: anywhere;
            word-break: break-word;
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
        .flow-warn {
            border: 2px solid #ffd06a;
            box-shadow:
                0 0 10px rgba(255,208,106,0.95),
                0 0 20px rgba(255,208,106,0.55),
                0 0 34px rgba(255,208,106,0.25);
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
        .feed-warn {
            border: 2px solid #ffd06a;
            box-shadow:
                0 0 10px rgba(255,208,106,0.95),
                0 0 20px rgba(255,208,106,0.55),
                0 0 34px rgba(255,208,106,0.25);
        }
        .feed-red {
            border: 2px solid #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
        }
        .env-green {
            border: 2px solid #35d07f;
            box-shadow:
                0 0 10px rgba(53,208,127,0.95),
                0 0 20px rgba(53,208,127,0.65),
                0 0 34px rgba(53,208,127,0.35);
        }
        .env-warn {
            border: 2px solid #ffd06a;
            box-shadow:
                0 0 10px rgba(255,208,106,0.95),
                0 0 20px rgba(255,208,106,0.65),
                0 0 34px rgba(255,208,106,0.35);
        }
        .env-red {
            border: 2px solid #ff5b5b;
            box-shadow:
                0 0 10px rgba(255,91,91,0.95),
                0 0 20px rgba(255,91,91,0.65),
                0 0 34px rgba(255,91,91,0.35);
        }
        .row {
            margin: 4px 0;
            font-size: 13px;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 10px;
            min-width: 0;
        }
        .label {
            display: inline-block;
            min-width: 92px;
            color: #d0d0d0;
            flex: 0 0 auto;
        }
        .row span:last-child {
            min-width: 0;
            overflow-wrap: anywhere;
            word-break: break-word;
            text-align: right;
        }
        .meta-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .meta-grid .row {
            margin: 0;
            justify-content: flex-start;
            align-items: center;
            gap: 6px;
        }
        .meta-grid .label,
        .meta-grid .row span:last-child {
            white-space: nowrap;
        }
        .meta-grid .label {
            min-width: 0;
            flex: 0 0 auto;
        }
        .meta-grid .row span:last-child {
            text-align: left;
        }
        .alarmbox {
            margin-top: 8px;
            padding: 8px;
            border-radius: 8px;
            border: 1px solid #6d2b2b;
            background: #30191c;
            font-size: 12px;
            overflow-wrap: anywhere;
            word-break: break-word;
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
            margin-top: 16px;
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
        .auger-mini-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 6px;
            margin-top: 6px;
        }
        .auger-mini-grid.count-1 {
            grid-template-columns: minmax(0, 1fr);
        }
        .auger-mini-grid.count-2 {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .auger-mini {
            min-width: 0;
            padding: 8px 8px 10px;
            border-radius: 10px;
            border: 2px solid #888;
            background: #686868;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .auger-mini.state-green {
            border-color: #42d685;
            box-shadow: 0 0 8px rgba(66, 214, 133, 0.45);
        }
        .auger-mini.state-warn {
            border-color: #ffd06a;
            box-shadow: 0 0 8px rgba(255, 208, 106, 0.32);
        }
        .auger-mini.state-red {
            border-color: #ff5b5b;
            box-shadow: 0 0 8px rgba(255, 91, 91, 0.4);
        }
        .auger-mini-label {
            font-size: 10px;
            color: #d2d2d2;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .auger-mini-status {
            font-size: 16px;
            font-weight: 700;
            line-height: 1.1;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .auger-mini-runtime {
            font-size: 12px;
            color: #d7d7d7;
            line-height: 1.1;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .summary-grid {
            display: grid;
            grid-template-columns: minmax(0, 1.35fr) repeat(5, minmax(0, 0.93fr));
            gap: 10px;
        }
        .summary-box {
            background: #686868;
            border: 1px solid #858585;
            border-radius: 10px;
            padding: 10px 12px;
            min-width: 0;
        }
        .summary-box-primary {
            padding: 10px 12px;
        }
        .summary-box-compact {
            padding: 10px 10px;
        }
        .summary-label {
            font-size: 12px;
            color: #d2d2d2;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .summary-box-compact .summary-label {
            font-size: 11px;
        }
        .summary-val {
            font-size: 30px;
            font-weight: bold;
            margin-top: 4px;
            line-height: 1.1;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .summary-box-compact .summary-val {
            font-size: 28px;
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
            .summary-grid { grid-template-columns: minmax(0, 1.25fr) repeat(5, minmax(0, 0.95fr)); }
        }
        @media (max-width: 700px) {
            body { overflow-x: hidden; }
            .wrap { padding: 8px; }
            .grid { grid-template-columns: 1fr; }
            .datetime { font-size: 16px; }
            .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
            .topbar { grid-template-columns: 1fr; }
            .topbar-left, .topbar-center, .topbar-right { justify-self: center; width: 100%; }
            .topbar-left {
                order: 1;
                justify-content: center;
                align-items: center;
                text-align: center;
            }
            .topbar-right {
                order: 2;
                display: flex;
                flex-direction: column;
                align-items: center;
                text-align: center;
                gap: 6px;
            }
            .topbar-center { order: 3; }
            h1 { text-align: center; width: 100%; }
            .topbar-actions {
                display: grid;
                grid-template-columns: 1fr 1fr;
                width: 100%;
                gap: 8px;
            }
            .access-ip { text-align: center; margin-top: 0; }
            .settings-link {
                width: 100%;
                justify-content: center;
                text-align: center;
                font-size: 12px;
                padding: 7px 8px;
            }
            .card { min-height: 0; padding: 8px; }
            .head { flex-direction: row; align-items: flex-start; }
            .head-left { min-width: 0; flex: 1 1 auto; }
            .badge-wrap {
                align-items: flex-end;
                flex-direction: column;
                flex-wrap: nowrap;
                justify-content: flex-start;
                align-self: flex-start;
                margin-left: auto;
            }
            .shed { font-size: 20px; }
            .birds-top, .alloc-top { font-size: 12px; }
            .topline { gap: 8px; }
            .mini-val { font-size: 18px; }
            .big-pair { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 6px; }
            .big-triple { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
            .metric-grid { grid-template-columns: 1fr 1fr; }
            .metric-columns { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
            .metric-grid-2 { grid-template-columns: 1fr; }
            .metric-big .metric-label { font-size: 11px; }
            .metric-big .metric-val { font-size: 26px; }
            .metric-val { font-size: 15px; }
            .row { flex-direction: column; gap: 2px; }
            .label { min-width: 0; }
            .row span:last-child { text-align: left; }
            .meta-grid { grid-template-columns: 1fr 1fr; gap: 8px; }
            .meta-grid .row {
                flex-direction: row;
                align-items: center;
                justify-content: flex-start;
                gap: 6px;
                font-size: 12px;
            }
            .meta-grid .row span:last-child {
                text-align: left;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .summary-title { font-size: 20px; }
            .summary-box { padding: 8px 10px; }
            .summary-label { font-size: 10px; }
            .summary-val { font-size: 22px; }
            .summary-box-compact .summary-val { font-size: 20px; }
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
                <div class="topbar-actions">
                    <a class="settings-link" href="{{ url_for('office_feed_stock_view') }}">Manual Feed Entry</a>
                    <a class="settings-link" href="{{ url_for('office_farm_health_view') }}">⚕ Farm Health</a>
                    <a class="settings-link" href="{{ url_for('office_settings_view') }}">⚙ Settings</a>
                </div>
            </div>
            <div class="topbar-right">
                <div id="topDateTime" class="datetime {{ header_class }}">--</div>
                <div class="access-ip">This device: {{ host_ips }}</div>
            </div>
        </div>

        <div class="grid">
            {% for s in sheds %}
            <div class="card-link" onclick="window.location.href='{{ url_for('shed_detail', shed_no=s.shed_no) }}'">
                <div id="shed-card-{{ s.shed_no }}" class="card {% if s.alarm_active %}alarm{% elif s.card_state == 'online' %}online{% else %}offline{% endif %} {% if not s.has_data %}nodata{% endif %}">
                    <div class="head">
                        <div class="head-left">
                            <div class="shed">{{ s.shed }}</div>
                            <div class="birds-top">Birds: <span id="shed-birds-remaining-{{ s.shed_no }}">{{ s.birds_remaining }}</span> (<span id="shed-birds-placed-{{ s.shed_no }}">{{ s.birds_placed }}</span>) • Age: <span id="shed-age-{{ s.shed_no }}">{{ s.bird_age }}</span></div>
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

                    <div class="big-triple">
                        <div id="shed-temp-tile-{{ s.shed_no }}" class="metric metric-big {% if s.temp_glow %}{{ s.temp_glow }}{% endif %}">
                            <div class="metric-label">Temp C</div>
                            <div id="shed-temp-{{ s.shed_no }}" class="metric-val">{{ s.temp_c }}</div>
                        </div>
                        <div id="shed-rh-tile-{{ s.shed_no }}" class="metric metric-big {% if s.rh_glow %}{{ s.rh_glow }}{% endif %}">
                            <div class="metric-label">RH %</div>
                            <div id="shed-rh-{{ s.shed_no }}" class="metric-val">{{ s.rh_pct }}</div>
                        </div>
                        <div id="shed-lighting-tile-{{ s.shed_no }}" class="metric metric-big metric-neutral metric-lighting metric-lighting-top {{ s.lighting_tile_class }}">
                            <div class="metric-label">Lighting</div>
                            <div class="metric-val"><span id="shed-lighting-icon-{{ s.shed_no }}" class="lighting-top-icon {% if s.lighting_on %}is-on{% else %}is-off{% endif %}">💡</span><span id="shed-lighting-status-{{ s.shed_no }}" class="lighting-top-text">{{ s.lighting_status_text }}</span></div>
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
                    {% if s.auger_tiles %}
                    <div class="auger-mini-grid count-{{ s.auger_count }}">
                        {% for a in s.auger_tiles %}
                        <div id="shed-auger-tile-{{ s.shed_no }}-{{ a.key }}" class="auger-mini {{ a.glow }}">
                            <div class="auger-mini-label">{{ a.label }}</div>
                            <div id="shed-auger-status-{{ s.shed_no }}-{{ a.key }}" class="auger-mini-status">{{ a.timestamp }}</div>
                            <div id="shed-auger-runtime-{{ s.shed_no }}-{{ a.key }}" class="auger-mini-runtime">{{ a.runtime }}</div>
                        </div>
                        {% endfor %}
                    </div>
                    {% endif %}

                    <div class="section">
                        <div class="metric-columns">
                            <div class="metric metric-water metric-water-daily">
                                <div class="metric-label">Water L 6am-6am</div>
                                <div id="shed-water7-{{ s.shed_no }}" class="metric-val">{{ s.water_7to7 }}</div>
                            </div>
                            <div class="metric metric-feed metric-feed-daily">
                                <div class="metric-label">Feed KG 6am-6am</div>
                                <div id="shed-feed7-{{ s.shed_no }}" class="metric-val">{{ s.feed_7to7 }}</div>
                            </div>
                            <div class="metric metric-neutral metric-runout">
                                <div class="metric-label">Estimated Run Out</div>
                                <div class="metric-val">{{ s.runout_est }}</div>
                            </div>
                            <div class="metric metric-water metric-water-bird">
                                <div class="metric-label">L/bird yesterday</div>
                                <div class="metric-val">{{ s.l_per_bird }}</div>
                            </div>
                            <div class="metric metric-feed metric-feed-bird">
                                <div class="metric-label">KG/bird yesterday</div>
                                <div class="metric-val">{{ s.kg_per_bird }}</div>
                            </div>
                            <div class="metric metric-neutral metric-mortality">
                                <div class="metric-label">Mortality</div>
                                <div id="shed-mortality-{{ s.shed_no }}" class="metric-val">{{ s.mortality_display }}</div>
                            </div>
                            <div class="metric metric-water metric-water-total">
                                <div class="metric-label">Water Total L</div>
                                <div class="metric-val">{{ s.total_water_to_date }}</div>
                            </div>
                            <div class="metric metric-feed metric-feed-total">
                                <div class="metric-label">Feed Total KG</div>
                                <div class="metric-val">{{ s.total_feed_to_date }}</div>
                            </div>
                        </div>
                    </div>

                    <div class="section">
                        <div class="meta-grid">
                            <div class="row"><span class="label">Crop:</span><span id="shed-crop-{{ s.shed_no }}">{{ s.crop_id }}</span></div>
                            <div class="row"><span class="label">Updated:</span><span id="shed-updated-{{ s.shed_no }}">{{ s.updated }}</span></div>
                        </div>
                    </div>

                    <div id="shed-alarm-{{ s.shed_no }}" class="alarmbox" {% if not s.alarm_active %}style="display:none"{% endif %}>
                        <div><strong id="shed-alarm-key-{{ s.shed_no }}">{{ s.alarm_key }}</strong></div>
                        <div id="shed-alarm-msg-{{ s.shed_no }}">{{ s.alarm_msg }}</div>
                    </div>
                </div>
            </div>
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
                                <div class="metric-label">Water L 6am-6am</div>
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
                <div class="summary-box summary-box-primary">
                    <div class="summary-label">Farm Crop ID</div>
                    <div id="overall-crop" class="summary-val">{{ overall.farm_crop_id }}</div>
                </div>
                <div class="summary-box summary-box-compact">
                    <div class="summary-label">Birds Placed</div>
                    <div id="overall-birds-placed" class="summary-val">{{ overall.birds_placed }}</div>
                </div>
                <div class="summary-box summary-box-compact">
                    <div class="summary-label">Birds Remaining</div>
                    <div id="overall-birds-remaining" class="summary-val">{{ overall.birds_remaining }}</div>
                </div>
                <div class="summary-box summary-box-compact">
                    <div class="summary-label">Total Mortality</div>
                    <div id="overall-mortality" class="summary-val">{{ overall.mortality_display }}</div>
                </div>
                <div class="summary-box summary-box-compact">
                    <div class="summary-label">Total Water L</div>
                    <div id="overall-water" class="summary-val">{{ overall.water }}</div>
                </div>
                <div class="summary-box summary-box-compact">
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

const NOTIFY_PREF_KEY = 'cdf-notifications-enabled';
const NOTIFY_LAST_TS_KEY = 'cdf-notifications-last-ts';
const NOTIFY_ACTIVE_KEY = 'cdf-notifications-active-alarms';
let swRegistration = null;

function notificationsEnabled() {
    return localStorage.getItem(NOTIFY_PREF_KEY) === '1';
}

function setNotificationsEnabled(enabled) {
    localStorage.setItem(NOTIFY_PREF_KEY, enabled ? '1' : '0');
}

function getKnownActiveAlarmIds() {
    try {
        const raw = localStorage.getItem(NOTIFY_ACTIVE_KEY);
        const parsed = JSON.parse(raw || '[]');
        return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
        return [];
    }
}

function setKnownActiveAlarmIds(ids) {
    localStorage.setItem(NOTIFY_ACTIVE_KEY, JSON.stringify(Array.isArray(ids) ? ids : []));
}

function getNotificationLastTs() {
    const raw = localStorage.getItem(NOTIFY_LAST_TS_KEY);
    const parsed = parseInt(raw || '0', 10);
    return Number.isFinite(parsed) ? parsed : 0;
}

function setNotificationLastTs(ts) {
    localStorage.setItem(NOTIFY_LAST_TS_KEY, String(ts || 0));
}

async function registerDashboardServiceWorker() {
    if (!('serviceWorker' in navigator)) return null;
    try {
        swRegistration = await navigator.serviceWorker.register('/service-worker.js');
        return swRegistration;
    } catch (err) {
        return null;
    }
}

async function showDashboardNotification(title, body, url, tag) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const options = {
        body: body || '',
        icon: '/apple-touch-icon.png',
        badge: '/apple-touch-icon.png',
        data: { url: url || '/' },
        tag: tag || undefined,
    };
    try {
        const reg = swRegistration || await registerDashboardServiceWorker();
        if (reg && reg.showNotification) {
            await reg.showNotification(title || 'Cherry Dene Dashboard', options);
            return;
        }
    } catch (err) {
    }
    try {
        const n = new Notification(title || 'Cherry Dene Dashboard', options);
        n.onclick = () => {
            window.focus();
            window.location.href = url || '/';
        };
    } catch (err) {
    }
}

async function baselineNotifications() {
    try {
        const resp = await fetch('/api/notifications?since=0', { cache: 'no-store' });
        if (!resp.ok) return;
        const payload = await resp.json();
        const activeIds = (payload.active_alarms || []).map((row) => row.id);
        setKnownActiveAlarmIds(activeIds);
        setNotificationLastTs(payload.latest_ts || Math.floor(Date.now() / 1000));
    } catch (err) {
        setNotificationLastTs(Math.floor(Date.now() / 1000));
    }
}

async function enableNotificationsFromUserAction() {
    if (!('Notification' in window)) return;
    await registerDashboardServiceWorker();
    if (Notification.permission === 'denied') {
        setNotificationsEnabled(false);
        return;
    }
    if (Notification.permission !== 'granted') {
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            setNotificationsEnabled(false);
            return;
        }
    }
    setNotificationsEnabled(true);
    await baselineNotifications();
    await showDashboardNotification('Cherry Dene Dashboard', 'Notifications enabled for this dashboard.', '/', 'cdf-notify-enabled');
}

async function pollNotifications() {
    if (!notificationsEnabled()) return;
    if (!('Notification' in window) || Notification.permission !== 'granted') {
        return;
    }
    try {
        const lastTs = getNotificationLastTs();
        const resp = await fetch(`/api/notifications?since=${lastTs}`, { cache: 'no-store' });
        if (!resp.ok) return;
        const payload = await resp.json();

        const knownActive = new Set(getKnownActiveAlarmIds());
        const nextActive = [];

        (payload.active_alarms || []).forEach((alarm) => {
            nextActive.push(alarm.id);
            if (!knownActive.has(alarm.id)) {
                showDashboardNotification(alarm.title, alarm.body, alarm.url, alarm.id);
            }
        });
        setKnownActiveAlarmIds(nextActive);

        (payload.events || []).forEach((event) => {
            showDashboardNotification(event.title, event.body, event.url, event.id);
        });

        setNotificationLastTs(payload.latest_ts || lastTs);
    } catch (err) {
    }
}

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
    setDashText(`shed-birds-placed-${s.shed_no}`, s.birds_placed);
    setDashText(`shed-birds-remaining-${s.shed_no}`, s.birds_remaining);
    setDashText(`shed-age-${s.shed_no}`, s.bird_age);
    setDashText(`shed-crop-${s.shed_no}`, s.crop_id);
    setDashText(`shed-farm-crop-${s.shed_no}`, s.farm_crop_id);
    setDashText(`shed-temp-${s.shed_no}`, s.temp_c);
    setDashText(`shed-rh-${s.shed_no}`, s.rh_pct);
    setDashText(`shed-water-${s.shed_no}`, s.water_lpm);
    setDashText(`shed-feed-${s.shed_no}`, s.feed_kg);
    setDashText(`shed-water7-${s.shed_no}`, s.water_7to7);
    setDashText(`shed-feed7-${s.shed_no}`, s.feed_7to7);
    setDashText(`shed-mortality-${s.shed_no}`, s.mortality_display || s.mortality_total);
    setDashText(`shed-updated-${s.shed_no}`, s.updated);
    setDashClass(`shed-card-${s.shed_no}`, [s.alarm_active ? 'alarm' : s.card_state, s.has_data ? '' : 'nodata'], ['alarm', 'online', 'offline', 'nodata']);
    setDashClass(`shed-temp-tile-${s.shed_no}`, [s.temp_glow], ['env-green', 'env-warn', 'env-red']);
    setDashClass(`shed-rh-tile-${s.shed_no}`, [s.rh_glow], ['env-green', 'env-warn', 'env-red']);
    setDashClass(`shed-water-tile-${s.shed_no}`, [s.water_glow], ['flow-green', 'flow-warn', 'flow-red']);
    setDashClass(`shed-feed-tile-${s.shed_no}`, [s.feed_glow], ['feed-green', 'feed-warn', 'feed-red']);
    setDashText(`shed-sync-badge-${s.shed_no}`, s.sync_pill_text);
    setDashClass(`shed-sync-badge-${s.shed_no}`, ['badge', s.sync_pill_class], ['sync-ok', 'sync-stale', 'sync-missing']);
    setDashText(`shed-lighting-status-${s.shed_no}`, s.lighting_status_text || 'Off');
    setDashClass(`shed-lighting-tile-${s.shed_no}`, ['metric', 'metric-neutral', 'metric-lighting', s.lighting_tile_class], ['lighting-on', 'lighting-off']);
    setDashClass(`shed-lighting-icon-${s.shed_no}`, ['lighting-top-icon', s.lighting_on ? 'is-on' : 'is-off'], ['is-on', 'is-off']);
    (s.auger_tiles || []).forEach((a) => {
        setDashText(`shed-auger-status-${s.shed_no}-${a.key}`, a.timestamp);
        setDashText(`shed-auger-runtime-${s.shed_no}-${a.key}`, a.runtime);
        setDashClass(`shed-auger-tile-${s.shed_no}-${a.key}`, ['auger-mini', a.glow], ['state-green', 'state-warn', 'state-red']);
    });

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
    setDashText('overall-mortality', o.mortality_display || o.mortality_total);
    setDashText('overall-water', o.water);
    setDashText('overall-feed', o.feed);
    setHeaderClass(o.farm_crop_id && o.farm_crop_id !== '--');
}

async function pollDashboard() {
    if (document.visibilityState === 'hidden') return;
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
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        pollDashboard();
    }
});

if (window.EventSource) {
    const waterSource = new EventSource('/api/water-stream');
    waterSource.onmessage = (event) => {
        try {
            const payload = JSON.parse(event.data);
            (payload.sheds || []).forEach((s) => {
                setDashText(`shed-water-${s.shed_no}`, s.water_lpm);
                setDashClass(`shed-water-tile-${s.shed_no}`, [s.water_glow], ['flow-green', 'flow-warn', 'flow-red']);
            });
            if (payload.borehole) {
                setDashText('borehole-water', payload.borehole.water_lpm);
                setDashClass('borehole-water-tile', [payload.borehole.water_glow], ['flow-green', 'flow-red']);
            }
        } catch (err) {
        }
    };
}

registerDashboardServiceWorker().then(() => {
    if (('Notification' in window) && notificationsEnabled() && Notification.permission === 'granted') {
        pollNotifications();
    }
});
setInterval(pollNotifications, 8000);
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
        * { box-sizing:border-box; }
        body { margin:0; font-family:Arial, sans-serif; background:#5b5b5b; color:#ececec; overflow-x:hidden; }
        .wrap { max-width:1400px; margin:0 auto; padding:16px; }
        a { color:#f0f0f0; text-decoration:none; }
        .topbar { margin-bottom:16px; }
        .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:16px; min-width:0; }
        h1 { margin:0 0 8px 0; }
        .sub { color:#d2d2d2; margin-bottom:14px; }
        .collapse { margin-top:14px; }
        .collapse summary { cursor:pointer; list-style:none; padding:12px 14px; border:1px solid #8a8a8a; border-radius:10px; background:#686868; font-weight:700; }
        .collapse summary::-webkit-details-marker { display:none; }
        .collapse[open] summary { margin-bottom:12px; }
        .table-wrap { overflow:auto; -webkit-overflow-scrolling:touch; border:1px solid #818181; border-radius:10px; background:#686868; }
        table { width:100%; border-collapse:collapse; font-size:14px; table-layout:fixed; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; vertical-align:top; overflow-wrap:anywhere; word-break:break-word; }
        th { color:#f0f0f0; }
        .compact-input {
            width:100%;
            min-width:64px;
            padding:8px 10px;
            border-radius:8px;
            border:1px solid #8a8a8a;
            background:#686868;
            color:#ececec;
        }
        .shed-threshold-grid {
            display:grid;
            grid-template-columns:repeat(3, minmax(0, 1fr));
            gap:12px;
        }
        .shed-threshold-card {
            background:#686868;
            border:1px solid #8a8a8a;
            border-radius:12px;
            padding:12px;
            min-width:0;
        }
        .shed-threshold-card h3 {
            margin:0 0 10px 0;
            font-size:18px;
        }
        .shed-threshold-fields {
            display:grid;
            grid-template-columns:1fr 1fr;
            gap:10px;
        }
        .shed-threshold-fields .field {
            gap:4px;
        }
        .mono { font-family:ui-monospace, SFMono-Regular, Menlo, monospace; }
        @media (max-width: 700px) {
            .wrap { padding:12px; }
            h1 { font-size:24px; }
            .panel { padding:12px; }
            table { font-size:13px; }
            th, td { padding:9px 7px; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>
        <div class="panel">
            <h1>Office Event Log</h1>
            <div class="sub">Recent office, controller, crop, sync, and mortality events.</div>
            <details class="collapse" open>
                <summary>Open event log table</summary>
                <div class="table-wrap">
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
            </details>
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
        * { box-sizing:border-box; }
        body { margin:0; font-family:Arial, sans-serif; background:#5b5b5b; color:#ececec; overflow-x:hidden; }
        .wrap { max-width:1400px; margin:0 auto; padding:16px; }
        a { color:#f0f0f0; text-decoration:none; }
        .topbar { margin-bottom:16px; }
        .status { margin-bottom:14px; padding:10px 12px; border-radius:10px; background:#737373; border:1px solid #8a8a8a; }
        .status.ok { border-color:#35d07f; color:#e4ffed; }
        .status.err { border-color:#c65460; color:#ffdbe1; }
        .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
        .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:16px; min-width:0; }
        h1 { margin:0 0 8px 0; }
        h2 { margin:0 0 10px 0; }
        .sub { color:#d2d2d2; margin-bottom:14px; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #818181; }
        .detail:last-child { border-bottom:0; }
        .label { color:#d2d2d2; }
        select { width:100%; box-sizing:border-box; padding:10px 12px; border-radius:8px; border:1px solid #8a8a8a; background:#686868; color:#ececec; margin-bottom:12px; }
        button { background:#727272; color:#ececec; border:1px solid #8a8a8a; border-radius:8px; padding:10px 14px; cursor:pointer; width:100%; }
        button.danger { border-color:#8e3e3e; }
        .collapse { margin-top:14px; }
        .collapse summary { cursor:pointer; list-style:none; padding:12px 14px; border:1px solid #8a8a8a; border-radius:10px; background:#686868; font-weight:700; }
        .collapse summary::-webkit-details-marker { display:none; }
        .collapse[open] summary { margin-bottom:12px; }
        .table-wrap { overflow:auto; -webkit-overflow-scrolling:touch; border:1px solid #818181; border-radius:10px; background:#686868; }
        table { width:100%; border-collapse:collapse; font-size:14px; table-layout:fixed; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; overflow-wrap:anywhere; word-break:break-word; }
        th { color:#f0f0f0; }
        @media (max-width: 900px) { .grid { grid-template-columns:1fr; } }
        @media (max-width: 700px) {
            .wrap { padding:12px; }
            h1 { font-size:24px; }
            .panel { padding:12px; }
            .detail { flex-direction:column; align-items:flex-start; }
            table { font-size:13px; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>
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
            <details class="collapse" open>
                <summary>Open controller copy restore list</summary>
                <div class="table-wrap">
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
            </details>
        </div>
        <div class="panel" style="margin-top:16px;">
            <h2>Available Backups</h2>
            <details class="collapse" open>
                <summary>Open available backups</summary>
                <div class="table-wrap">
                    <table>
                        <thead><tr><th>Name</th><th>Modified</th></tr></thead>
                        <tbody>
                            {% for b in backups %}
                            <tr><td>{{ b.name }}</td><td>{{ b.mtime }}</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </details>
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


MANUAL_FEED_ENTRY_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Manual Feed Entry</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; font-family: Arial, sans-serif; background: #5b5b5b; color: #ececec; overflow-x:hidden; }
        .wrap { max-width: 1100px; margin: 0 auto; padding: 16px; }
        a { color: #f0f0f0; text-decoration: none; }
        h1 { margin: 0 0 6px 0; font-size: 30px; }
        h2 { margin: 0 0 8px 0; font-size: 22px; }
        .sub { color: #d2d2d2; margin-bottom: 16px; font-size: 14px; line-height: 1.45; }
        .topbar { margin-bottom: 14px; }
        .status { margin:0 0 14px 0; padding:10px 12px; border-radius:8px; background:#686868; border:1px solid #8a8a8a; }
        .status.ok { border-color:#35d07f; color:#e4ffed; }
        .status.err { border-color:#c65460; color:#ffdbe1; }
        .panel { background:#737373; border:1px solid #8a8a8a; border-radius:8px; padding:14px; margin-bottom:16px; min-width:0; }
        .form-grid { display:grid; grid-template-columns:1fr 0.55fr 1fr auto; gap:10px; align-items:end; }
        .field { display:flex; flex-direction:column; gap:6px; min-width:0; }
        .field label { color:#f0f0f0; font-size:14px; }
        input, select {
            width:100%;
            min-height:42px;
            padding:10px 12px;
            border-radius:6px;
            border:1px solid #8a8a8a;
            background:#686868;
            color:#ececec;
            font-family: inherit;
        }
        button {
            min-height:42px;
            padding:10px 14px;
            border-radius:6px;
            border:1px solid #5e8e70;
            background:#476a53;
            color:#ececec;
            cursor:pointer;
        }
        .table-wrap { overflow:auto; -webkit-overflow-scrolling:touch; border:1px solid #818181; border-radius:6px; background:#686868; }
        table { width:100%; border-collapse:collapse; font-size:14px; table-layout:fixed; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; vertical-align:top; overflow-wrap:anywhere; word-break:break-word; }
        th { color:#f0f0f0; }
        .empty { color:#d2d2d2; font-size:14px; }
        @media (max-width: 760px) { .wrap { padding:12px; } h1 { font-size:24px; } .form-grid { grid-template-columns:1fr; } button { width:100%; } table { font-size:13px; } }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>
        <h1>Manual Feed Entry</h1>
        <div class="sub">Normal silo feeding is recorded automatically from the weigh cells. Use this only for extra feed that the weigh cells will not see, such as floor-fed feed or feed moved between sheds.</div>
        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}

        <div class="panel">
            <h2>Record Shed Feed</h2>
            <form class="form-grid" method="post" action="{{ url_for('office_feed_stock_allocate_view') }}">
                <div class="field">
                    <label for="manual_feed_shed_no">Shed</label>
                    <select id="manual_feed_shed_no" name="shed_no">
                        <option value="">Select active shed</option>
                        {% for target in active_targets %}
                        <option value="{{ target.shed_no }}" {% if preselected_shed_no == target.shed_no %}selected{% endif %}>{{ target.shed_name }} - {{ target.crop_code }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="field">
                    <label for="manual_feed_kg">Feed KG</label>
                    <input id="manual_feed_kg" type="number" step="0.1" min="0" name="kg" value="">
                </div>
                <div class="field">
                    <label for="manual_feed_note">Note</label>
                    <input id="manual_feed_note" type="text" name="note" value="" placeholder="Floor fed / moved from Shed 2">
                </div>
                <button type="submit">Record Feed</button>
            </form>
        </div>

        <div class="panel">
            <h2>Manual Feed History</h2>
            {% if transaction_rows %}
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Time</th><th>Shed</th><th>Crop</th><th>Feed KG</th><th>Note</th></tr></thead>
                    <tbody>
                        {% for row in transaction_rows %}
                        {% if row.kind == "shed_allocation" %}
                        <tr>
                            <td>{{ row.ts_label }}</td>
                            <td>{{ row.shed_label }}</td>
                            <td>{{ row.crop_label }}</td>
                            <td>{{ row.feed_kg_label }}</td>
                            <td>{{ row.note if row.note else "--" }}</td>
                        </tr>
                        {% endif %}
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="empty">No manual feed entries recorded yet.</div>
            {% endif %}
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
        * { box-sizing:border-box; }
        body { margin:0; font-family:Arial, sans-serif; background:#5b5b5b; color:#ececec; overflow-x:hidden; }
        .wrap { max-width:1400px; margin:0 auto; padding:16px; }
        a { color:#f0f0f0; text-decoration:none; }
        .topbar { margin-bottom:16px; }
        h1 { margin:0 0 8px 0; }
        .sub { color:#d2d2d2; margin-bottom:14px; }
        .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
        .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:16px; min-width:0; }
        .health-grid { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:12px; margin-top:12px; }
        .health-card { background:#686868; border:1px solid #8a8a8a; border-radius:12px; padding:12px; min-width:0; overflow-wrap:anywhere; word-break:break-word; }
        .health-label { color:#d2d2d2; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; }
        .health-value { margin-top:6px; font-size:24px; font-weight:700; }
        .health-note { margin-top:6px; color:#dcdcdc; font-size:12px; line-height:1.35; }
        .action-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
        .form-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
        .field { display:flex; flex-direction:column; gap:6px; min-width:0; }
        .field label { color:#f0f0f0; font-size:13px; }
        .field input {
            width:100%;
            padding:10px 12px;
            border-radius:8px;
            border:1px solid #8a8a8a;
            background:#686868;
            color:#ececec;
        }
        .field textarea {
            width:100%;
            min-height:84px;
            padding:10px 12px;
            border-radius:8px;
            border:1px solid #8a8a8a;
            background:#686868;
            color:#ececec;
            resize:vertical;
            font-family:inherit;
        }
        .field-full { grid-column:1 / -1; }
        .checkbox-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:8px 0 14px 0; }
        .check { display:flex; align-items:center; gap:8px; padding:10px 12px; border:1px solid #8a8a8a; border-radius:10px; background:#686868; }
        .check input { width:auto; margin:0; }
        .recipient-list { display:grid; gap:10px; margin-top:14px; }
        .recipient-row {
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:10px;
            padding:10px 12px;
            border:1px solid #8a8a8a;
            border-radius:10px;
            background:#686868;
        }
        .recipient-email { overflow-wrap:anywhere; word-break:break-word; }
        .inline-form { display:flex; gap:10px; align-items:flex-end; }
        .inline-form .field { flex:1 1 auto; }
        .inline-form button { width:auto; min-width:130px; }
        .notify-btn.notify-on {
            border-color:#35d07f;
            color:#d9ffe8;
            box-shadow:
                0 0 8px rgba(53,208,127,0.65),
                0 0 16px rgba(53,208,127,0.30);
        }
        .notify-btn.notify-blocked {
            border-color:#ff7a7a;
            color:#ffd8d8;
            box-shadow:
                0 0 8px rgba(255,122,122,0.65),
                0 0 16px rgba(255,122,122,0.30);
        }
        .notify-btn.notify-off {
            border-color:#ffd06a;
            color:#fff0c7;
        }
        .notify-status {
            margin-top:12px;
            font-size:13px;
            color:#d7d7d7;
            min-height:18px;
        }
        .notify-status.state-on {
            color:#d9ffe8;
            text-shadow: 0 0 8px rgba(53,208,127,0.45);
        }
        .notify-status.state-blocked {
            color:#ffd8d8;
            text-shadow: 0 0 8px rgba(255,122,122,0.45);
        }
        .notify-status.state-off {
            color:#fff0c7;
        }
        .note { color:#d2d2d2; font-size:12px; line-height:1.4; margin-top:10px; }
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
        .collapse { margin-top:14px; }
        .collapse summary { cursor:pointer; list-style:none; padding:12px 14px; border:1px solid #8a8a8a; border-radius:10px; background:#686868; font-weight:700; }
        .collapse summary::-webkit-details-marker { display:none; }
        .collapse[open] summary { margin-bottom:12px; }
        .table-wrap { overflow:auto; -webkit-overflow-scrolling:touch; border:1px solid #818181; border-radius:10px; background:#686868; }
        table { width:100%; border-collapse:collapse; font-size:14px; table-layout:fixed; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; vertical-align:top; overflow-wrap:anywhere; word-break:break-word; }
        th { color:#f0f0f0; }
        @media (max-width: 900px) { .grid, .action-grid, .health-grid, .form-grid, .checkbox-grid, .shed-threshold-grid, .shed-threshold-fields { grid-template-columns:1fr; } }
        @media (max-width: 700px) {
            .wrap { padding:12px; }
            h1 { font-size:24px; }
            .panel { padding:12px; }
            .detail { flex-direction:column; align-items:flex-start; }
            .action-link, button { min-height:42px; padding:10px 12px; }
            .inline-form { flex-direction:column; align-items:stretch; }
            .inline-form button { width:100%; min-width:0; }
            .recipient-row { flex-direction:column; align-items:stretch; }
            table { font-size:13px; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>
        <h1>Office Settings</h1>
        <div class="sub">Core office tools, notifications, email, backups, and update control.</div>
        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}
        <div class="grid">
            <div class="panel">
                <h2>Office Tools</h2>
                <div class="sub">Daily operational tools and backup actions.</div>
                <div class="detail"><span class="label">Auto Backup</span><span>Hourly, keep newest {{ backup_keep_count }}</span></div>
                <div class="detail"><span class="label">Latest Backup</span><span>{{ latest_backup_name }}</span></div>
                <div class="detail"><span class="label">Manual Feed</span><span>Record feed allocated to a shed</span></div>
                <div class="action-grid">
                    <a class="action-link" href="{{ url_for('office_versions_view') }}">Versions</a>
                    <a class="action-link" href="{{ url_for('office_feed_stock_view') }}">Manual Feed Entry</a>
                    <a class="action-link" href="{{ url_for('restore_office_backup_view') }}">Restore Backup</a>
                    <a class="action-link" href="{{ url_for('create_office_backup_view') }}">Create Backup</a>
                    <a class="action-link" href="{{ url_for('download_latest_office_backup_view') }}">Download Backup</a>
                    <a class="action-link" href="{{ url_for('collect_controller_backups_now_view') }}">Collect Controller Backups</a>
                </div>
                <details class="collapse">
                    <summary>Show Backup Location</summary>
                    <div class="detail"><span class="label">Backup Path</span><span class="mono">{{ backup_dir }}</span></div>
                </details>
            </div>
            <div class="panel">
                <h2>Software Update</h2>
                <div class="sub">Check for a newer office version and apply it when you are ready.</div>
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
                <details class="collapse">
                    <summary>Show Version Details</summary>
                    <div class="detail"><span class="label">Branch</span><span class="mono">{{ update_status.branch }}</span></div>
                    <div class="detail"><span class="label">Current Commit</span><span class="mono">{{ update_status.local_commit }}</span></div>
                    <div class="detail"><span class="label">Latest Commit</span><span class="mono">{{ update_status.remote_commit }}</span></div>
                </details>
            </div>
        </div>
        <div class="panel" style="margin-top:16px;">
            <h2>Notifications</h2>
            <div class="sub">Turn alarm notifications on or off for this device.</div>
            <button id="settingsNotifyToggle" class="notify-btn" type="button">🔔 Enable Notifications</button>
            <div id="settingsNotifyStatus" class="notify-status"></div>
        </div>
        <div class="panel" style="margin-top:16px;">
            <h2>Email Settings</h2>
            <div class="sub">Shared SMTP settings and the saved recipient list for report emails.</div>
            <form method="post" action="{{ url_for('office_save_email_settings_view') }}">
                <div class="checkbox-grid">
                    <label class="check"><input type="checkbox" name="report_email_enabled" value="1" {% if email_settings.report_email_enabled %}checked{% endif %}> Enable shared app email sending</label>
                    <label class="check"><input type="checkbox" name="report_smtp_use_tls" value="1" {% if email_settings.report_smtp_use_tls %}checked{% endif %}> Use TLS</label>
                    <label class="check"><input type="checkbox" name="report_smtp_use_ssl" value="1" {% if email_settings.report_smtp_use_ssl %}checked{% endif %}> Use SSL</label>
                </div>

                <div class="form-grid">
                    <div class="field">
                        <label for="report_email_from">From Address</label>
                        <input id="report_email_from" type="text" name="report_email_from" value="{{ email_settings.report_email_from }}">
                    </div>
                    <div class="field">
                        <label for="report_smtp_host">SMTP Host</label>
                        <input id="report_smtp_host" type="text" name="report_smtp_host" value="{{ email_settings.report_smtp_host }}">
                    </div>
                    <div class="field">
                        <label for="report_smtp_port">SMTP Port</label>
                        <input id="report_smtp_port" type="text" name="report_smtp_port" value="{{ email_settings.report_smtp_port }}">
                    </div>
                    <div class="field">
                        <label for="report_smtp_username">SMTP Username</label>
                        <input id="report_smtp_username" type="text" name="report_smtp_username" value="{{ email_settings.report_smtp_username }}">
                    </div>
                    <div class="field field-full">
                        <label for="report_smtp_password">SMTP Password</label>
                        <input id="report_smtp_password" type="password" name="report_smtp_password" value="{{ email_settings.report_smtp_password }}">
                    </div>
                </div>
                <div class="note">These shared settings are also used for crop report emails.</div>
                <div class="update-actions">
                    <button class="wide" type="submit">Save Email Settings</button>
                </div>
            </form>

            <details class="collapse" style="margin-top:14px;" open>
                <summary>Recipients</summary>
                <form class="inline-form" method="post" action="{{ url_for('office_add_email_recipient_view') }}">
                    <div class="field">
                        <label for="new_recipient_email">Add Recipient Email</label>
                        <input id="new_recipient_email" type="email" name="recipient_email" value="">
                    </div>
                    <button type="submit">Add Recipient</button>
                </form>

                {% if email_settings.report_recipients %}
                <div class="recipient-list">
                    {% for recipient in email_settings.report_recipients %}
                    <div class="recipient-row">
                        <div class="recipient-email">{{ recipient }}</div>
                        <form method="post" action="{{ url_for('office_remove_email_recipient_view') }}">
                            <input type="hidden" name="recipient_email" value="{{ recipient }}">
                            <button type="submit">Remove</button>
                        </form>
                    </div>
                    {% endfor %}
                </div>
                {% else %}
                <div class="note">No recipients saved yet.</div>
                {% endif %}
            </details>
        </div>
        <div class="panel" style="margin-top:16px;">
            <h2>Shed Controller Backups</h2>
            <div class="sub">Controller backup health and the latest office-collected ZIP copy.</div>
            <details class="collapse">
                <summary>Open Shed Controller Backup Table</summary>
                <div class="table-wrap">
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
            </details>
        </div>
    </div>
<script>
setTimeout(() => {
    document.querySelectorAll('.auto-dismiss').forEach((el) => {
        el.style.display = 'none';
    });
}, 10000);

const NOTIFY_PREF_KEY = 'cdf-notifications-enabled';
const NOTIFY_LAST_TS_KEY = 'cdf-notifications-last-ts';
const NOTIFY_ACTIVE_KEY = 'cdf-notifications-active-alarms';
let settingsNotifyToggleBtn = null;
let settingsNotifyStatusEl = null;
let settingsSwRegistration = null;

function settingsNotificationsEnabled() {
    return localStorage.getItem(NOTIFY_PREF_KEY) === '1';
}

function setSettingsNotificationsEnabled(enabled) {
    localStorage.setItem(NOTIFY_PREF_KEY, enabled ? '1' : '0');
    updateSettingsNotifyButton();
}

function getSettingsKnownActiveAlarmIds() {
    try {
        const raw = localStorage.getItem(NOTIFY_ACTIVE_KEY);
        const parsed = JSON.parse(raw || '[]');
        return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
        return [];
    }
}

function setSettingsKnownActiveAlarmIds(ids) {
    localStorage.setItem(NOTIFY_ACTIVE_KEY, JSON.stringify(Array.isArray(ids) ? ids : []));
}

function getSettingsNotificationLastTs() {
    const raw = localStorage.getItem(NOTIFY_LAST_TS_KEY);
    const parsed = parseInt(raw || '0', 10);
    return Number.isFinite(parsed) ? parsed : 0;
}

function setSettingsNotificationLastTs(ts) {
    localStorage.setItem(NOTIFY_LAST_TS_KEY, String(ts || 0));
}

function updateSettingsNotifyButton() {
    if (!settingsNotifyToggleBtn) return;
    if (settingsNotifyStatusEl) {
        settingsNotifyStatusEl.classList.remove('state-on', 'state-blocked', 'state-off');
    }
    if (!('Notification' in window)) {
        settingsNotifyToggleBtn.textContent = '🔕 Notifications Unsupported';
        settingsNotifyToggleBtn.disabled = true;
        settingsNotifyToggleBtn.classList.remove('notify-on', 'notify-off', 'notify-blocked');
        if (settingsNotifyStatusEl) settingsNotifyStatusEl.textContent = 'This browser does not support notifications.';
        return;
    }
    const permission = Notification.permission;
    if (!settingsNotificationsEnabled()) {
        settingsNotifyToggleBtn.textContent = permission === 'granted' ? '🔔 Notifications Off' : '🔔 Enable Notifications';
        settingsNotifyToggleBtn.classList.remove('notify-on', 'notify-blocked');
        settingsNotifyToggleBtn.classList.add('notify-off');
        if (settingsNotifyStatusEl) {
            settingsNotifyStatusEl.textContent = permission === 'granted'
                ? 'Notifications are currently turned off for this dashboard.'
                : 'Notifications are not enabled yet.';
            settingsNotifyStatusEl.classList.add('state-off');
        }
        return;
    }
    if (permission === 'granted') {
        settingsNotifyToggleBtn.textContent = '🔔 Notifications On';
        settingsNotifyToggleBtn.classList.remove('notify-off', 'notify-blocked');
        settingsNotifyToggleBtn.classList.add('notify-on');
        if (settingsNotifyStatusEl) {
            settingsNotifyStatusEl.textContent = 'Notifications are enabled for this dashboard.';
            settingsNotifyStatusEl.classList.add('state-on');
        }
    } else if (permission === 'denied') {
        settingsNotifyToggleBtn.textContent = '🔕 Notifications Blocked';
        settingsNotifyToggleBtn.classList.remove('notify-off', 'notify-on');
        settingsNotifyToggleBtn.classList.add('notify-blocked');
        if (settingsNotifyStatusEl) {
            settingsNotifyStatusEl.textContent = 'Notifications are blocked in this browser for the dashboard.';
            settingsNotifyStatusEl.classList.add('state-blocked');
        }
    } else {
        settingsNotifyToggleBtn.textContent = '🔔 Enable Notifications';
        settingsNotifyToggleBtn.classList.remove('notify-on', 'notify-blocked');
        settingsNotifyToggleBtn.classList.add('notify-off');
        if (settingsNotifyStatusEl) {
            settingsNotifyStatusEl.textContent = 'Click Enable Notifications to allow alarm alerts.';
            settingsNotifyStatusEl.classList.add('state-off');
        }
    }
}

async function registerSettingsDashboardServiceWorker() {
    if (!('serviceWorker' in navigator)) return null;
    try {
        settingsSwRegistration = await navigator.serviceWorker.register('/service-worker.js');
        return settingsSwRegistration;
    } catch (err) {
        return null;
    }
}

async function showSettingsDashboardNotification(title, body, url, tag) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const options = {
        body: body || '',
        icon: '/apple-touch-icon.png',
        badge: '/apple-touch-icon.png',
        data: { url: url || '/' },
        tag: tag || undefined,
    };
    try {
        const reg = settingsSwRegistration || await registerSettingsDashboardServiceWorker();
        if (reg && reg.showNotification) {
            await reg.showNotification(title || 'Cherry Dene Dashboard', options);
            return;
        }
    } catch (err) {
    }
    try {
        const n = new Notification(title || 'Cherry Dene Dashboard', options);
        n.onclick = () => {
            window.focus();
            window.location.href = url || '/';
        };
    } catch (err) {
    }
}

async function baselineSettingsNotifications() {
    try {
        const resp = await fetch('/api/notifications?since=0', { cache: 'no-store' });
        if (!resp.ok) return;
        const payload = await resp.json();
        const activeIds = (payload.active_alarms || []).map((row) => row.id);
        setSettingsKnownActiveAlarmIds(activeIds);
        setSettingsNotificationLastTs(payload.latest_ts || Math.floor(Date.now() / 1000));
    } catch (err) {
        setSettingsNotificationLastTs(Math.floor(Date.now() / 1000));
    }
}

async function enableSettingsNotificationsFromUserAction() {
    if (!('Notification' in window)) return;
    await registerSettingsDashboardServiceWorker();
    if (Notification.permission === 'denied') {
        setSettingsNotificationsEnabled(false);
        updateSettingsNotifyButton();
        return;
    }
    if (Notification.permission !== 'granted') {
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            setSettingsNotificationsEnabled(false);
            updateSettingsNotifyButton();
            return;
        }
    }
    setSettingsNotificationsEnabled(true);
    await baselineSettingsNotifications();
    await showSettingsDashboardNotification('Cherry Dene Dashboard', 'Notifications enabled for this dashboard.', '/', 'cdf-notify-enabled');
    if (settingsNotifyStatusEl) {
        settingsNotifyStatusEl.textContent = 'Notifications enabled successfully.';
        settingsNotifyStatusEl.classList.remove('state-blocked', 'state-off');
        settingsNotifyStatusEl.classList.add('state-on');
    }
}

async function pollSettingsNotifications() {
    if (!settingsNotificationsEnabled()) return;
    if (!('Notification' in window) || Notification.permission !== 'granted') {
        updateSettingsNotifyButton();
        return;
    }
    try {
        const lastTs = getSettingsNotificationLastTs();
        const resp = await fetch(`/api/notifications?since=${lastTs}`, { cache: 'no-store' });
        if (!resp.ok) return;
        const payload = await resp.json();

        const knownActive = new Set(getSettingsKnownActiveAlarmIds());
        const nextActive = [];

        (payload.active_alarms || []).forEach((alarm) => {
            nextActive.push(alarm.id);
            if (!knownActive.has(alarm.id)) {
                showSettingsDashboardNotification(alarm.title, alarm.body, alarm.url, alarm.id);
            }
        });
        setSettingsKnownActiveAlarmIds(nextActive);

        (payload.events || []).forEach((event) => {
            showSettingsDashboardNotification(event.title, event.body, event.url, event.id);
        });

        setSettingsNotificationLastTs(payload.latest_ts || lastTs);
    } catch (err) {
    }
}

settingsNotifyToggleBtn = document.getElementById('settingsNotifyToggle');
settingsNotifyStatusEl = document.getElementById('settingsNotifyStatus');
if (settingsNotifyToggleBtn) {
    settingsNotifyToggleBtn.addEventListener('click', async () => {
        if (settingsNotificationsEnabled() && ('Notification' in window) && Notification.permission === 'granted') {
            setSettingsNotificationsEnabled(false);
            if (settingsNotifyStatusEl) {
                settingsNotifyStatusEl.textContent = 'Notifications turned off for this dashboard.';
                settingsNotifyStatusEl.classList.remove('state-on', 'state-blocked');
                settingsNotifyStatusEl.classList.add('state-off');
            }
            return;
        }
        await enableSettingsNotificationsFromUserAction();
    });
}
updateSettingsNotifyButton();
registerSettingsDashboardServiceWorker();
if (settingsNotificationsEnabled() && ('Notification' in window) && Notification.permission === 'granted') {
    pollSettingsNotifications();
}
setInterval(pollSettingsNotifications, 8000);
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
        * { box-sizing:border-box; }
        body { margin:0; font-family:Arial,sans-serif; background:#5b5b5b; color:#ececec; overflow-x:hidden; }
        .wrap { max-width:1180px; margin:0 auto; padding:24px; }
        .topbar a { color:#ececec; text-decoration:none; }
        .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:16px; margin-top:16px; min-width:0; }
        .detail { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid #818181; }
        .detail:last-child { border-bottom:0; }
        .label { color:#d2d2d2; }
        .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
        .sub { color:#d2d2d2; margin-bottom:14px; }
        .collapse { margin-top:14px; }
        .collapse summary { cursor:pointer; list-style:none; padding:12px 14px; border:1px solid #8a8a8a; border-radius:10px; background:#686868; font-weight:700; }
        .collapse summary::-webkit-details-marker { display:none; }
        .collapse[open] summary { margin-bottom:12px; }
        .table-wrap { overflow:auto; -webkit-overflow-scrolling:touch; border:1px solid #818181; border-radius:10px; background:#686868; }
        table { width:100%; border-collapse:collapse; font-size:14px; table-layout:fixed; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; overflow-wrap:anywhere; word-break:break-word; }
        @media (max-width: 700px) {
            .wrap { padding:12px; }
            h1 { font-size:24px; }
            .panel { padding:12px; }
            .detail { flex-direction:column; align-items:flex-start; }
            table { font-size:13px; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>
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
            <details class="collapse" open>
                <summary>Open controller version table</summary>
                <div class="table-wrap">
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
            </details>
        </div>
    </div>
</body>
</html>
"""


FARM_HEALTH_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Farm Health</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing:border-box; }
        body { margin:0; font-family:Arial,sans-serif; background:#5b5b5b; color:#ececec; overflow-x:hidden; }
        .wrap { max-width:1400px; margin:0 auto; padding:16px; }
        .topbar { margin-bottom:16px; }
        .topbar a { color:#ececec; text-decoration:none; }
        h1 { margin:0 0 8px 0; }
        .sub { color:#d2d2d2; margin-bottom:14px; }
        .summary-grid { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:12px; margin-bottom:16px; }
        .panel { background:#737373; border:1px solid #8a8a8a; border-radius:14px; padding:16px; min-width:0; }
        .action-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:16px; }
        .action-link {
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-height:46px;
            padding:10px 14px;
            border-radius:10px;
            border:1px solid #8a8a8a;
            background:#686868;
            color:#ececec;
            text-decoration:none;
        }
        .health-card { background:#686868; border:1px solid #8a8a8a; border-radius:12px; padding:12px; min-width:0; overflow-wrap:anywhere; word-break:break-word; }
        .health-label { color:#d2d2d2; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; }
        .health-value { margin-top:6px; font-size:24px; font-weight:700; }
        .health-note { margin-top:6px; color:#dcdcdc; font-size:12px; line-height:1.35; }
        .collapse summary { cursor:pointer; list-style:none; padding:12px 14px; border:1px solid #8a8a8a; border-radius:10px; background:#686868; font-weight:700; }
        .collapse summary::-webkit-details-marker { display:none; }
        .collapse[open] summary { margin-bottom:12px; }
        .table-wrap { overflow:auto; -webkit-overflow-scrolling:touch; border:1px solid #818181; border-radius:10px; background:#686868; }
        table { width:100%; border-collapse:collapse; font-size:14px; table-layout:fixed; }
        th, td { padding:10px 8px; border-bottom:1px solid #818181; text-align:left; vertical-align:top; overflow-wrap:anywhere; word-break:break-word; }
        th { color:#f0f0f0; }
        .state-ok { color:#8ff0ba; }
        .state-bad { color:#ffb0b0; }
        @media (max-width: 1000px) { .summary-grid { grid-template-columns:1fr 1fr; } }
        @media (max-width: 700px) {
            .wrap { padding:12px; }
            h1 { font-size:24px; }
            .summary-grid { grid-template-columns:1fr; }
            .action-grid { grid-template-columns:1fr; }
            .panel { padding:12px; }
            table { font-size:13px; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>
        <h1>Farm Health</h1>
        <div class="sub">Live controller heartbeat, Pico link, and backup health across sheds and the bore hole.</div>
        <div class="action-grid">
            <a class="action-link" href="{{ url_for('office_crop_reports_view') }}">🧾 Crop Reports</a>
            <a class="action-link" href="{{ url_for('office_settings_view') }}">⚙ Settings</a>
        </div>
        <div class="summary-grid">
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
        <div class="panel">
            <details class="collapse" open>
                <summary>Open controller health table</summary>
                <div class="table-wrap">
                    <table>
                        <thead><tr><th>Controller</th><th>Heartbeat</th><th>Pico</th><th>Controller Backup</th><th>Office Copy</th></tr></thead>
                        <tbody>
                            {% for row in rows %}
                            <tr>
                                <td>{{ row.label }}</td>
                                <td class="{{ 'state-ok' if row.heartbeat_ok else 'state-bad' }}">{{ row.heartbeat }}</td>
                                <td class="{{ 'state-ok' if row.pico_ok else 'state-bad' }}">{{ row.pico }}</td>
                                <td class="{{ 'state-ok' if row.backup_ok else 'state-bad' }}">{{ row.backup }}</td>
                                <td class="{{ 'state-ok' if row.office_copy_ok else 'state-bad' }}">{{ row.office_copy }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </details>
        </div>
    </div>
</body>
</html>
"""


def compute_farm_health_summary(controller_meta=None, borehole_meta=None, collector_status=None):
    controller_meta = controller_meta if isinstance(controller_meta, dict) else load_controller_meta()
    borehole_meta = borehole_meta if isinstance(borehole_meta, dict) else load_borehole_meta()
    collector_status = collector_status if isinstance(collector_status, dict) else load_controller_backup_status()
    stale_labels = []
    pico_offline_labels = []
    backup_issue_labels = []
    collect_ages = []

    def inspect_controller(label, meta, office_copy):
        if not controller_heartbeat_ok(meta):
            stale_labels.append(label)
        if not effective_pico_connected(meta):
            pico_offline_labels.append(label)
        backup_status = str(meta.get("last_backup_status", "") or "--")
        if backup_status == "--" or "fail" in backup_status.lower():
            backup_issue_labels.append(label)
        try:
            collected_ts = int(office_copy.get("last_collected_ts")) if office_copy.get("last_collected_ts") not in [None, ""] else None
        except Exception:
            collected_ts = None
        if collected_ts is not None:
            collect_ages.append(max(0, int(time.time()) - collected_ts))

    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        inspect_controller(
            "Shed %s" % shed_no,
            controller_meta.get(str(int(shed_no)), {}) if isinstance(controller_meta, dict) else {},
            collector_status.get("shed_%d" % shed_no, {}) if isinstance(collector_status, dict) else {},
        )
        i += 1
    inspect_controller("Bore Hole", borehole_meta, collector_status.get("borehole", {}) if isinstance(collector_status, dict) else {})
    return {
        "stale_count": len(stale_labels),
        "stale_labels": ", ".join(stale_labels) if stale_labels else "All controller heartbeats are current",
        "pico_offline_count": len(pico_offline_labels),
        "pico_offline_labels": ", ".join(pico_offline_labels) if pico_offline_labels else "All controller Pico links currently report connected",
        "backup_issue_count": len(backup_issue_labels),
        "backup_issue_labels": ", ".join(backup_issue_labels) if backup_issue_labels else "No current controller backup issues reported",
        "last_collect_age": ("%ss ago" % min(collect_ages)) if collect_ages else "--",
        "last_collect_note": ("Newest office-collected controller copy" if collect_ages else "No controller copies collected yet"),
    }


DETAIL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} Detail</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
            overflow-x: hidden;
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
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
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
            min-width: 0;
            overflow-wrap: anywhere;
            word-break: break-word;
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
            min-width: 0;
        }
        .table-card h2 {
            margin-top: 0;
            font-size: 22px;
        }
        .collapse {
            margin-top: 14px;
        }
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid #8a8a8a;
            border-radius: 10px;
            background: #686868;
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker {
            display: none;
        }
        .collapse[open] summary {
            margin-bottom: 12px;
        }
        .table-wrap {
            overflow: auto;
            -webkit-overflow-scrolling: touch;
            border: 1px solid #818181;
            border-radius: 10px;
            background: #686868;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
            table-layout: fixed;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 10px 8px;
            text-align: left;
            vertical-align: middle;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        th {
            color: #f0f0f0;
        }
        input[type="number"], input[type="datetime-local"] {
            width: 110px;
            box-sizing: border-box;
            padding: 8px 10px;
            border-radius: 8px;
            border: 1px solid #8a8a8a;
            background: #686868;
            color: #ececec;
        }
        input[type="datetime-local"] {
            width: 190px;
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
            flex-wrap: wrap;
            max-width: 100%;
        }
        @media (max-width: 1200px) {
            table {
                font-size: 13px;
            }
            input[type="number"] {
                width: 90px;
            }
            input[type="datetime-local"] {
                width: 170px;
            }
        }
        @media (max-width: 700px) {
            .wrap {
                padding: 12px;
            }
            h1 {
                font-size: 24px;
            }
            .navcard {
                padding: 14px;
            }
            .navtitle {
                font-size: 20px;
            }
            .table-card {
                padding: 12px;
            }
            button {
                width: 100%;
            }
            .form-inline {
                display: flex;
                margin-right: 0;
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>

        <h1>{{ shed_name }}</h1>
        <div class="sub">Current crop {{ active_crop_code }}</div>

        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}

        <div class="grid">
            <a class="navcard" href="{{ url_for('shed_tables_graphs_view', shed_no=shed_no) }}">
                <div class="navtitle">Feed & Water</div>
                <div class="navsub">Feed and water tables with pill selectors for 6-hour or daily charts.</div>
            </a>

            <a class="navcard" href="{{ url_for('shed_crop_history', shed_no=shed_no) }}">
                <div class="navtitle">Crop history</div>
                <div class="navsub">Open the last 6 crops for this shed.</div>
            </a>

            <a class="navcard" href="{{ url_for('shed_mortality_view', shed_no=shed_no) }}">
                <div class="navtitle">Mortality</div>
                <div class="navsub">Enter losses and deduct them from live bird numbers.</div>
            </a>

            <a class="navcard" href="{{ url_for('shed_thresholds_view', shed_no=shed_no) }}">
                <div class="navtitle">Tile thresholds</div>
                <div class="navsub">Set temp, humidity, live water, and feed glow thresholds for this shed.</div>
            </a>
        </div>

        <div class="table-card">
            <h2>Shed entries</h2>
            <details class="collapse" open>
                <summary>Open shed entry table</summary>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Entry Shed</th>
                                <th>Birds</th>
                                <th>Placed At</th>
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
                                    <form id="entry-form-{{ r.dest_shed }}" class="form-inline" method="post" action="{{ url_for('shed_entry_save', shed_no=shed_no, dest_shed=r.dest_shed) }}">
                                        <input type="number" name="bird_count" min="0" step="1" value="{{ '' if r.bird_count == 0 else r.bird_count }}">
                                        <input type="datetime-local" name="placement_at" value="{{ r.placement_input_value }}">
                                    </form>
                                </td>
                                <td>{{ r.placement_str }}</td>
                                <td>
                                    {% if r.crop_active == 1 %}
                                        <span class="entry-yes">Yes</span>
                                    {% else %}
                                        <span class="entry-no">No</span>
                                    {% endif %}
                                </td>
                                <td>
                                    <button form="entry-form-{{ r.dest_shed }}" formaction="{{ url_for('shed_entry_start', shed_no=shed_no, dest_shed=r.dest_shed) }}" type="submit">Start</button>
                                    <form class="form-inline" method="post" action="{{ url_for('shed_entry_end', shed_no=shed_no, dest_shed=r.dest_shed) }}">
                                        <button class="danger" type="submit">End</button>
                                    </form>
                                </td>
                                <td>
                                    {% if r.can_move %}
                                    <form class="form-inline" method="post" action="{{ url_for('shed_entry_move', shed_no=shed_no, dest_shed=r.dest_shed) }}" onsubmit="return confirm('Move birds from Shed {{ shed_no }} to Shed {{ r.dest_shed }}?');">
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
            </details>
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
        * { box-sizing: border-box; }
        body { margin: 0; font-family: Arial, sans-serif; background: #5b5b5b; color: #ececec; overflow-x:hidden; }
        .wrap { max-width: 1200px; margin: 0 auto; padding: 16px; }
        a { color: #f0f0f0; text-decoration: none; }
        h1 { margin: 0 0 6px 0; font-size: 30px; }
        .sub { color: #d2d2d2; margin-bottom: 16px; font-size: 14px; }
        .topbar { margin-bottom: 14px; }
        .status { margin-bottom: 14px; padding: 10px 12px; border-radius: 10px; background: #737373; border: 1px solid #8a8a8a; }
        .status.ok { border-color: #35d07f; color: #dff9ea; }
        .status.err { border-color: #ff5b5b; color: #ffd6d6; }
        .grid { display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 14px; }
        .card { background: #737373; border: 2px solid #8a8a8a; border-radius: 12px; padding: 14px; min-width:0; }
        .card h2 { margin-top: 0; font-size: 22px; }
        label { display: block; color: #f0f0f0; margin-bottom: 6px; font-size: 14px; }
        input[type="number"], input[type="text"], select { width: 100%; box-sizing: border-box; padding: 10px 12px; border-radius: 8px; border: 1px solid #8a8a8a; background: #686868; color: #ececec; margin-bottom: 12px; }
        button { background: #727272; color: #f2f2f2; border: 1px solid #8a8a8a; border-radius: 8px; padding: 10px 14px; cursor: pointer; }
        .collapse { margin-top: 14px; }
        .collapse summary { cursor: pointer; list-style: none; padding: 12px 14px; border: 1px solid #8a8a8a; border-radius: 10px; background: #686868; font-weight: 700; }
        .collapse summary::-webkit-details-marker { display:none; }
        .collapse[open] summary { margin-bottom: 12px; }
        .table-wrap { overflow:auto; -webkit-overflow-scrolling:touch; border:1px solid #818181; border-radius:10px; background:#686868; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; table-layout:fixed; }
        th, td { border-bottom: 1px solid #818181; padding: 10px 8px; text-align: left; vertical-align: middle; overflow-wrap:anywhere; word-break:break-word; }
        th { color: #f0f0f0; }
        .empty { color: #d2d2d2; }
        @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
        @media (max-width: 700px) {
            .wrap { padding: 12px; }
            h1 { font-size: 24px; }
            .card { padding: 12px; }
            table { font-size: 13px; }
            button { width: 100%; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>
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
                <details class="collapse" open>
                <summary>Open mortality log</summary>
                <h2 style="margin-top:18px;">Mortality Log</h2>
                {% if history_rows %}
                <div class="table-wrap">
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
                </div>
                {% else %}
                <div class="empty">No mortality logged for this crop yet.</div>
                {% endif %}
                </details>
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


SHED_THRESHOLDS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} Tile Thresholds</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; font-family: Arial, sans-serif; background: #5b5b5b; color: #ececec; overflow-x:hidden; }
        .wrap { max-width: 980px; margin: 0 auto; padding: 16px; }
        a { color: #f0f0f0; text-decoration: none; }
        h1 { margin: 0 0 6px 0; font-size: 30px; }
        .sub { color: #d2d2d2; margin-bottom: 16px; font-size: 14px; }
        .topbar { margin-bottom: 14px; }
        .status { margin-bottom: 14px; padding: 10px 12px; border-radius: 10px; background: #737373; border: 1px solid #8a8a8a; }
        .status.ok { border-color: #35d07f; color: #dff9ea; }
        .status.err { border-color: #ff5b5b; color: #ffd6d6; }
        .card { background: #737373; border: 2px solid #8a8a8a; border-radius: 12px; padding: 14px; min-width:0; }
        .field-rows { display:grid; grid-template-columns:1fr; gap:12px; }
        .field-row { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; }
        .field { display:flex; flex-direction:column; gap:6px; }
        .field label { color:#f0f0f0; font-size:14px; }
        .field input {
            width:100%;
            padding:10px 12px;
            border-radius:8px;
            border:1px solid #8a8a8a;
            background:#686868;
            color:#ececec;
        }
        .note { color:#d2d2d2; font-size:13px; line-height:1.45; margin-top:12px; }
        .preview {
            margin-top: 14px;
            padding: 12px;
            border-radius: 10px;
            background: #686868;
            border: 1px solid #8a8a8a;
        }
        .preview-title {
            font-size: 13px;
            font-weight: 700;
            color: #f0f0f0;
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
            padding: 4px 8px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 6px;
            border: 1px solid #8a8a8a;
        }
        .preview-pill.red {
            color: #ffd6d6;
            border-color: #ff5b5b;
            box-shadow: 0 0 8px rgba(255,91,91,0.45);
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
            color: #d2d2d2;
            font-size: 12px;
            line-height: 1.35;
        }
        button {
            margin-top:14px;
            background:#727272;
            color:#ececec;
            border:1px solid #8a8a8a;
            border-radius:8px;
            padding:10px 14px;
            cursor:pointer;
            min-width:180px;
        }
        @media (max-width: 700px) {
            .wrap { padding: 12px; }
            h1 { font-size: 24px; }
            .card { padding: 12px; }
            .field-row { grid-template-columns:repeat(3, minmax(0, 1fr)); gap:8px; }
            .field label { font-size:12px; }
            .field input { padding:8px 10px; font-size:14px; }
            .preview-grid { grid-template-columns: 1fr; }
            button { width:100%; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>
        <h1>{{ shed_name }} Tile Thresholds</h1>
        <div class="sub">Control the glow thresholds used on this shed’s dashboard tile.</div>
        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}
        <div class="card">
            <form method="post" action="{{ url_for('shed_thresholds_save_view', shed_no=shed_no) }}">
                <div class="field-rows">
                    <div class="field-row">
                        <div class="field">
                            <label for="temp_low_c">Temp Red Low C</label>
                            <input id="temp_low_c" type="number" step="0.1" name="temp_low_c" value="{{ row.temp_low_c }}">
                        </div>
                        <div class="field">
                            <label for="temp_high_c">Temp Red High C</label>
                            <input id="temp_high_c" type="number" step="0.1" name="temp_high_c" value="{{ row.temp_high_c }}">
                        </div>
                        <div class="field">
                            <label for="temp_amber_margin_c">Temp Amber Margin C</label>
                            <input id="temp_amber_margin_c" type="number" step="0.1" name="temp_amber_margin_c" value="{{ row.temp_amber_margin_c }}">
                        </div>
                    </div>
                    <div class="field-row">
                        <div class="field">
                            <label for="rh_low_pct">RH Red Low %</label>
                            <input id="rh_low_pct" type="number" step="1" name="rh_low_pct" value="{{ row.rh_low_pct }}">
                        </div>
                        <div class="field">
                            <label for="rh_high_pct">RH Red High %</label>
                            <input id="rh_high_pct" type="number" step="1" name="rh_high_pct" value="{{ row.rh_high_pct }}">
                        </div>
                        <div class="field">
                            <label for="rh_amber_margin_pct">RH Amber %</label>
                            <input id="rh_amber_margin_pct" type="number" step="1" name="rh_amber_margin_pct" value="{{ row.rh_amber_margin_pct }}">
                        </div>
                    </div>
                    <div class="field-row">
                        <div class="field">
                            <label for="water_low_lpm">Water Red Low L/min</label>
                            <input id="water_low_lpm" type="number" step="0.01" name="water_low_lpm" value="{{ row.water_low_lpm }}">
                        </div>
                        <div class="field">
                            <label for="water_amber_buffer_lpm">Water Amber Buffer L/min</label>
                            <input id="water_amber_buffer_lpm" type="number" step="0.01" name="water_amber_buffer_lpm" value="{{ row.water_amber_buffer_lpm }}">
                        </div>
                    </div>
                    <div class="field-row">
                        <div class="field">
                            <label for="feed_low_kg">Feed Red Low KG</label>
                            <input id="feed_low_kg" type="number" step="1" name="feed_low_kg" value="{{ row.feed_low_kg }}">
                        </div>
                        <div class="field">
                            <label for="feed_amber_buffer_kg">Feed Amber Buffer KG</label>
                            <input id="feed_amber_buffer_kg" type="number" step="1" name="feed_amber_buffer_kg" value="{{ row.feed_amber_buffer_kg }}">
                        </div>
                    </div>
                </div>
                <div class="note">Temp and RH go red outside the red-below and red-above limits. The amber margin creates an amber zone just inside those limits. Water and feed go red below the red-below value, then amber for the size of the amber buffer above it.</div>
                <div class="preview">
                    <div class="preview-title">How The Colours Work</div>
                    <div class="preview-grid">
                        <div class="preview-item">
                            <div class="preview-pill red">RED</div>
                            <div class="preview-text">Outside the safe range, or below the low red threshold for water and feed.</div>
                        </div>
                        <div class="preview-item">
                            <div class="preview-pill amber">AMBER</div>
                            <div class="preview-text">Close to the red limit. Temp and RH use the amber margin. Water and feed use the amber buffer above red.</div>
                        </div>
                        <div class="preview-item">
                            <div class="preview-pill green">GREEN</div>
                            <div class="preview-text">Comfortably in range, with enough distance from the red and amber trigger points.</div>
                        </div>
                    </div>
                </div>
                <button type="submit">Save Tile Thresholds</button>
            </form>
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
        * {
            box-sizing: border-box;
        }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
            overflow-x: hidden;
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
            min-width: 0;
            overflow-wrap: anywhere;
            word-break: break-word;
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
        @media (max-width: 700px) {
            .wrap { padding: 12px; }
            h1 { font-size: 24px; }
            .navcard { padding: 14px; }
            .navtitle { font-size: 20px; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>

        <h1>Bore Hole</h1>
        <div class="sub">Hourly and daily water usage with zoomable charts.</div>

        <div class="grid">
            <a class="navcard" href="{{ url_for('borehole_period_view', period='hourly') }}">
                <div class="navtitle">Hourly</div>
                <div class="navsub">Hourly list and zoomable water chart.</div>
            </a>

            <a class="navcard" href="{{ url_for('borehole_period_view', period='daily') }}">
                <div class="navtitle">Daily</div>
                <div class="navsub">Completed 6am-6am daily list and zoomable water chart.</div>
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
        * {
            box-sizing: border-box;
        }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
            overflow-x: hidden;
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
            min-width: 0;
        }
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid #8a8a8a;
            border-radius: 10px;
            background: #686868;
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker {
            display: none;
        }
        .collapse[open] summary {
            margin-bottom: 12px;
        }
        .table-wrap {
            overflow: auto;
            -webkit-overflow-scrolling: touch;
            border: 1px solid #818181;
            border-radius: 10px;
            background: #686868;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
            table-layout: fixed;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 10px 8px;
            text-align: left;
            overflow-wrap: anywhere;
            word-break: break-word;
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
        @media (max-width: 700px) {
            .wrap { padding: 12px; }
            h1 { font-size: 24px; }
            .card { padding: 12px; }
            .actions a { display:block; margin:0 0 8px 0; }
            table { font-size: 13px; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>

        <h1>{{ shed_name }} Crop history</h1>
        <div class="sub">Last 6 crops found in hourly log data.</div>

        <div class="card">
            {% if crops %}
            <details class="collapse" open>
                <summary>Open crop history table</summary>
                <div class="table-wrap">
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
                                    <a href="{{ url_for('shed_crop_summary_view', shed_no=shed_no, crop_id=c.crop_id) }}">Summary</a>
                                    <a href="{{ url_for('shed_crop_period_view', shed_no=shed_no, crop_id=c.crop_id, period='hourly') }}">6 Hour</a>
                                    <a href="{{ url_for('shed_crop_period_view', shed_no=shed_no, crop_id=c.crop_id, period='daily') }}">Daily</a>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </details>
            {% else %}
            <div class="empty">No crop history found yet.</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""


CROP_SUMMARY_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} {{ summary.crop_code }} Summary</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
            overflow-x: hidden;
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
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-bottom: 14px;
        }
        .card {
            background: #737373;
            border: 2px solid #8a8a8a;
            border-radius: 12px;
            padding: 14px;
            min-width: 0;
        }
        .metric-label {
            color: #d2d2d2;
            font-size: 13px;
            margin-bottom: 6px;
        }
        .metric-value {
            font-size: 28px;
            font-weight: 700;
            color: #f5f5f5;
        }
        .metric-sub {
            color: #d2d2d2;
            font-size: 12px;
            margin-top: 6px;
        }
        .status-pill {
            display: inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            background: #4a4a4a;
            border: 1px solid #8a8a8a;
            color: #f3f3f3;
            font-size: 13px;
            font-weight: 700;
        }
        .actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 14px;
        }
        .actions a {
            display: inline-block;
            padding: 10px 12px;
            border-radius: 10px;
            background: #727272;
            border: 1px solid #8a8a8a;
        }
        .two-col {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
        }
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid #8a8a8a;
            border-radius: 10px;
            background: #686868;
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker {
            display: none;
        }
        .collapse[open] summary {
            margin-bottom: 12px;
        }
        .table-wrap {
            max-height: 780px;
            overflow: auto;
            border: 1px solid #818181;
            border-radius: 10px;
            background: #686868;
            -webkit-overflow-scrolling: touch;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            table-layout: fixed;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 8px 6px;
            text-align: left;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        th {
            color: #f0f0f0;
            position: sticky;
            top: 0;
            background: #686868;
        }
        .empty {
            color: #d2d2d2;
            font-size: 14px;
        }
        @media (max-width: 1200px) {
            .two-col {
                grid-template-columns: 1fr;
            }
        }
        @media (max-width: 700px) {
            .wrap { padding: 12px; }
            h1 { font-size: 24px; }
            .summary-grid { grid-template-columns: 1fr; }
            .card { padding: 12px; }
            .metric-value { font-size: 24px; }
            .actions a, .status-pill { width: 100%; text-align: center; }
            table { font-size: 12px; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>

        <h1>{{ shed_name }} {{ summary.crop_code }} End of Crop Summary</h1>
        <div class="sub">Historic crop roll-up using crop events, mortality, hourly water, and hourly feed history, displayed in 6-hour feed/water views.</div>

        <div class="actions">
            <span class="status-pill">{{ summary.status }}</span>
            <a href="{{ url_for('shed_crop_period_view', shed_no=shed_no, crop_id=summary.crop_id, period='hourly') }}">Open 6 hour history</a>
            <a href="{{ url_for('shed_crop_period_view', shed_no=shed_no, crop_id=summary.crop_id, period='daily') }}">Open daily history</a>
        </div>

        <div class="summary-grid">
            <div class="card"><div class="metric-label">Start</div><div class="metric-value" style="font-size:20px">{{ summary.start_label }}</div></div>
            <div class="card"><div class="metric-label">End</div><div class="metric-value" style="font-size:20px">{{ summary.end_label }}</div></div>
            <div class="card"><div class="metric-label">Crop Days</div><div class="metric-value">{{ summary.crop_days }}</div></div>
            <div class="card"><div class="metric-label">Birds Placed</div><div class="metric-value">{{ summary.birds_placed }}</div></div>
            <div class="card"><div class="metric-label">Birds Remaining</div><div class="metric-value">{{ summary.birds_remaining_end }}</div><div class="metric-sub">At crop end</div></div>
            <div class="card"><div class="metric-label">Mortality</div><div class="metric-value">{{ summary.mortality_display }}</div><div class="metric-sub">{{ summary.mortality_events }} entries</div></div>
            <div class="card"><div class="metric-label">Manual Feed Recorded KG</div><div class="metric-value">{{ summary.manual_feed_adjustment_kg }}</div><div class="metric-sub">Floor-fed / allocated feed</div></div>
            <div class="card"><div class="metric-label">Total Feed KG</div><div class="metric-value">{{ summary.total_feed }}</div></div>
            <div class="card"><div class="metric-label">Feed Left In Bin KG</div><div class="metric-value">{{ summary.feed_bin_end_kg }}</div><div class="metric-sub">Informational crop-end bin balance</div></div>
            <div class="card"><div class="metric-label">Total Water L</div><div class="metric-value">{{ summary.total_water }}</div></div>
            <div class="card"><div class="metric-label">Avg Daily Feed KG</div><div class="metric-value">{{ summary.avg_daily_feed }}</div></div>
            <div class="card"><div class="metric-label">Avg Daily Water L</div><div class="metric-value">{{ summary.avg_daily_water }}</div></div>
            <div class="card"><div class="metric-label">Feed / Bird KG</div><div class="metric-value">{{ summary.feed_per_bird }}</div></div>
            <div class="card"><div class="metric-label">Water / Bird L</div><div class="metric-value">{{ summary.water_per_bird }}</div></div>
            <div class="card"><div class="metric-label">Peak Daily Feed KG</div><div class="metric-value">{{ summary.peak_daily_feed }}</div></div>
            <div class="card"><div class="metric-label">Peak Daily Water L</div><div class="metric-value">{{ summary.peak_daily_water }}</div></div>
            <div class="card"><div class="metric-label">Hourly Points</div><div class="metric-value">{{ summary.hourly_points }}</div></div>
            <div class="card"><div class="metric-label">Completed Days</div><div class="metric-value">{{ summary.complete_days }}</div></div>
        </div>

        <div class="two-col">
            <div class="card">
                <h2>Daily Performance</h2>
                {% if daily_rows %}
                <details class="collapse" open>
                    <summary>Open daily performance table</summary>
                    <div class="table-wrap">
                        <table>
                            <thead>
                                <tr>
                                    <th>Day</th>
                                    <th>Water L</th>
                                    <th>Feed KG</th>
                                    <th>Running Water L</th>
                                    <th>Running Feed KG</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for r in daily_rows %}
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
                </details>
                {% else %}
                <div class="empty">No completed daily history found for this crop yet.</div>
                {% endif %}
            </div>

            <div class="card">
                <h2>Summary Notes</h2>
                <table>
                    <tbody>
                        <tr><th>Crop ID</th><td>{{ summary.crop_code }}</td></tr>
                        <tr><th>Status</th><td>{{ summary.status }}</td></tr>
                        <tr><th>Start</th><td>{{ summary.start_label }}</td></tr>
                        <tr><th>End</th><td>{{ summary.end_label }}</td></tr>
                        <tr><th>Mortality %</th><td>{{ summary.mortality_pct }}</td></tr>
                        <tr><th>Based on</th><td>Crop events, hourly feed/water, and mortality history</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""


CROP_REPORTS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>End of Crop Reports</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
            overflow-x: hidden;
        }
        .wrap {
            max-width: 1500px;
            margin: 0 auto;
            padding: 16px;
        }
        a { color: #ececec; text-decoration: none; }
        a:hover { text-decoration: underline; }
        h1 {
            margin: 0 0 8px 0;
            font-size: 30px;
        }
        .sub {
            color: #d2d2d2;
            margin-bottom: 16px;
            font-size: 14px;
        }
        .topbar { margin-bottom: 14px; }
        .card {
            background: #737373;
            border: 2px solid #8a8a8a;
            border-radius: 12px;
            padding: 14px;
            min-width: 0;
        }
        .msg {
            margin-bottom: 14px;
            padding: 10px 12px;
            border-radius: 10px;
            border: 1px solid #8a8a8a;
            background: #686868;
        }
        .msg.ok {
            border-color: #35d07f;
            color: #d8ffe9;
        }
        .msg.bad {
            border-color: #ff6c6c;
            color: #ffd2d2;
        }
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid #8a8a8a;
            border-radius: 10px;
            background: #686868;
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker {
            display: none;
        }
        .collapse[open] summary {
            margin-bottom: 12px;
        }
        .table-wrap {
            overflow: auto;
            -webkit-overflow-scrolling: touch;
            border: 1px solid #818181;
            border-radius: 10px;
            background: #686868;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
            table-layout: fixed;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 10px 8px;
            text-align: left;
            vertical-align: top;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        th { color: #f0f0f0; }
        .actions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .actions a, .actions button {
            padding: 8px 10px;
            border-radius: 9px;
            border: 1px solid #8a8a8a;
            background: #666;
            color: #f2f2f2;
            text-decoration: none;
            cursor: pointer;
            font-size: 13px;
        }
        .actions form {
            margin: 0;
        }
        .pill {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 999px;
            border: 1px solid #8a8a8a;
            background: #666;
            font-size: 12px;
            font-weight: 700;
        }
        .pill.emailed { border-color: #35d07f; color: #d8ffe9; }
        .pill.generated { border-color: #ffd06a; color: #fff0c0; }
        .pill.failed { border-color: #ff6c6c; color: #ffd2d2; }
        .pill.processing, .pill.queued { border-color: #8ec7ff; color: #d9ecff; }
        .empty { color: #d2d2d2; }
        .path {
            font-size: 12px;
            color: #d0d0d0;
            word-break: break-all;
        }
        @media (max-width: 700px) {
            .wrap { padding: 12px; }
            h1 { font-size: 24px; }
            .card { padding: 12px; }
            .actions a, .actions button { width: 100%; text-align: center; }
            table { font-size: 13px; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>

        <h1>End of Crop Reports</h1>
        <div class="sub">Stored locally on the office Pi and available to download or resend by email.</div>

        {% if status_msg %}
        <div class="msg {% if status_ok %}ok{% else %}bad{% endif %}">{{ status_msg }}</div>
        {% endif %}

        <div class="card">
            {% if rows %}
            <details class="collapse" open>
                <summary>Open crop report table</summary>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Crop</th>
                                <th>Farm</th>
                                <th>Created</th>
                                <th>Status</th>
                                <th>File</th>
                                <th>Email</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for row in rows %}
                            <tr>
                                <td>{{ row.crop_code }}</td>
                                <td>{{ row.farm_name }}</td>
                                <td>{{ row.generated_label }}</td>
                                <td><span class="pill {{ row.status }}">{{ row.status }}</span></td>
                                <td>
                                    {{ row.report_name }}
                                    {% if row.file_exists and row.report_path %}
                                    <div class="path">{{ row.report_path }}</div>
                                    {% endif %}
                                </td>
                                <td>
                                    {% if row.email_sent %}Sent{% else %}Not sent{% endif %}
                                    <div class="path">{{ row.email_message }}</div>
                                </td>
                                <td>
                                    <div class="actions">
                                        {% if row.file_exists %}
                                        <a href="{{ url_for('office_crop_report_download', crop_id=row.crop_id) }}">Download XLSX</a>
                                        {% endif %}
                                        <form method="post" action="{{ url_for('office_crop_report_resend', crop_id=row.crop_id) }}">
                                            <button type="submit">Resend Email</button>
                                        </form>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </details>
            {% else %}
            <div class="empty">No end-of-crop reports have been generated yet.</div>
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
        * {
            box-sizing: border-box;
        }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
            overflow-x: hidden;
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
            min-width: 0;
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
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid #8a8a8a;
            border-radius: 10px;
            background: #686868;
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker {
            display: none;
        }
        .collapse[open] summary {
            margin-bottom: 12px;
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
            -webkit-overflow-scrolling: touch;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            table-layout: fixed;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 8px 6px;
            text-align: left;
            overflow-wrap: anywhere;
            word-break: break-word;
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
        .table-controls {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
            margin-top: 10px;
        }
        @media (max-width: 1200px) {
            .grid { grid-template-columns: 1fr; }
        }
        @media (max-width: 700px) {
            .wrap { padding: 12px; }
            h1 { font-size: 24px; }
            .card { padding: 12px; }
            .toolbar button { width: 100%; }
            .chart-box { height: 320px; }
        }
    </style>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>

        <h1>{{ shed_name }} {{ period_title }}</h1>
        <div class="sub">{{ period_sub }}</div>

        <div class="grid">
            <div class="card">
                <h2>{{ period_title }} list</h2>
                {% if rows %}
                <details class="collapse" open>
                    <summary>Open {{ period_title|lower }} list</summary>
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
                                {% for r in table_rows %}
                                <tr class="paged-row">
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
                    <div class="table-controls">
                        <button type="button" id="periodTableLoadMore">Load next 20</button>
                        <div class="hint" id="periodTableInfo"></div>
                    </div>
                </details>
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
setupPagedTable('periodTableLoadMore', 'periodTableInfo');
</script>
</body>
</html>
"""


METRIC_PERIOD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} {{ metric_title }} {{ period_title }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="30">
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; font-family: Arial, sans-serif; background: #5b5b5b; color: #ececec; overflow-x: hidden; }
        .wrap { max-width: 1500px; margin: 0 auto; padding: 16px; }
        a { color: #f0f0f0; text-decoration: none; }
        a:hover { text-decoration: underline; }
        h1 { margin: 0 0 6px 0; font-size: 30px; }
        .sub { color: #d2d2d2; margin-bottom: 16px; font-size: 14px; }
        .topbar { margin-bottom: 14px; }
        .status { margin-bottom: 14px; padding: 10px 12px; border-radius: 10px; background: #686868; border: 1px solid #8a8a8a; }
        .status.ok { border-color: #35d07f; color: #e4ffed; }
        .status.err { border-color: #c65460; color: #ffdbe1; }
        .switches { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
        .switch {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 42px;
            padding: 8px 12px;
            border-radius: 10px;
            border: 1px solid #8a8a8a;
            background: #686868;
            color: #ececec;
        }
        .switch.active {
            border-color: #35d07f;
            color: #dff9ea;
            box-shadow: 0 0 8px rgba(53,208,127,0.35);
        }
        .grid { display: grid; grid-template-columns: 1fr 1.15fr; gap: 14px; }
        .card { background: #737373; border: 2px solid #8a8a8a; border-radius: 12px; padding: 14px; min-width: 0; }
        .card h2 { margin-top: 0; font-size: 20px; }
        .summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; margin-bottom: 16px; }
        .summary-card { background: #737373; border: 2px solid #8a8a8a; border-radius: 12px; padding: 14px; }
        .summary-label { color: #d2d2d2; font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }
        .summary-value { margin-top: 8px; font-size: 28px; font-weight: 700; }
        .summary-note { color: #d2d2d2; font-size: 12px; margin-top: 6px; }
        .action-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: stretch; }
        .action-card {
            background: #686868;
            border: 1px solid #8a8a8a;
            border-radius: 12px;
            padding: 12px;
            min-width: 0;
        }
        .action-card h3 {
            margin: 0 0 6px 0;
            font-size: 18px;
        }
        .action-card-sub {
            color: #d2d2d2;
            font-size: 12px;
            line-height: 1.35;
            margin-bottom: 12px;
        }
        .action-row {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 8px;
            align-items: end;
            margin-bottom: 10px;
        }
        .action-row:last-child { margin-bottom: 0; }
        .field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
        .field label { color: #f0f0f0; font-size: 14px; }
        input, select {
            width: 100%;
            padding: 10px 12px;
            border-radius: 8px;
            border: 1px solid #8a8a8a;
            background: #686868;
            color: #ececec;
            font-family: inherit;
        }
        button.full {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            min-height: 44px;
            padding: 10px 14px;
            border-radius: 10px;
            border: 1px solid #8a8a8a;
            background: #686868;
            color: #ececec;
            cursor: pointer;
        }
        .action-row button.full {
            width: auto;
            min-width: 150px;
        }
        .inline-note { margin-top: 8px; }
        .feed-extra-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
        .toolbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
        .toolbar button {
            background: #727272;
            color: #ececec;
            border: 1px solid #8a8a8a;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
        }
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid #8a8a8a;
            border-radius: 10px;
            background: #686868;
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker { display: none; }
        .collapse[open] summary { margin-bottom: 12px; }
        .chart-wrap { background: #686868; border: 1px solid #818181; border-radius: 10px; padding: 10px; overflow: hidden; }
        .chart-box { position: relative; height: 420px; }
        .table-wrap { max-height: 900px; overflow: auto; border: 1px solid #818181; border-radius: 10px; background: #686868; -webkit-overflow-scrolling: touch; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
        th, td { border-bottom: 1px solid #818181; padding: 8px 6px; text-align: left; overflow-wrap: anywhere; word-break: break-word; }
        th { color: #f0f0f0; position: sticky; top: 0; background: #686868; }
        .hint { color: #d2d2d2; font-size: 12px; margin-top: 8px; }
        .empty { color: #d2d2d2; font-size: 14px; padding: 10px 0; }
        .table-controls {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
            margin-top: 10px;
        }
        @media (max-width: 1200px) {
            .grid { grid-template-columns: 1fr; }
            .summary-grid { grid-template-columns: 1fr 1fr; }
            .feed-extra-grid { grid-template-columns: 1fr; }
        }
        @media (max-width: 700px) {
            .wrap { padding: 12px; }
            h1 { font-size: 24px; }
            .card { padding: 12px; }
            .switch { width: 100%; }
            .toolbar button { width: 100%; }
            .summary-grid, .action-grid { grid-template-columns: 1fr; }
            .action-row { grid-template-columns: 1fr; }
            .action-row button.full { width: 100%; }
            .chart-box { height: 320px; }
        }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>

        <h1>{{ shed_name }} {{ metric_title }} {{ period_title }}</h1>
        <div class="sub">{{ period_sub }}</div>
        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}

        <div class="switches">
            <a class="switch {% if metric == 'feed' %}active{% endif %}" href="{{ url_for('shed_metric_period_view', shed_no=shed_no, metric='feed', period=period) }}">Feed</a>
            <a class="switch {% if metric == 'water' %}active{% endif %}" href="{{ url_for('shed_metric_period_view', shed_no=shed_no, metric='water', period=period) }}">Water</a>
            <a class="switch {% if period == 'hourly' %}active{% endif %}" href="{{ url_for('shed_metric_period_view', shed_no=shed_no, metric=metric, period='hourly') }}">6 Hour</a>
            <a class="switch {% if period == 'daily' %}active{% endif %}" href="{{ url_for('shed_metric_period_view', shed_no=shed_no, metric=metric, period='daily') }}">Daily</a>
        </div>

        <div class="grid">
            <div class="card">
                <h2>{{ metric_title }} {{ period_title }} table</h2>
                {% if rows %}
                <details class="collapse" open>
                    <summary>Open {{ metric_title|lower }} {{ period_title|lower }} table</summary>
                    <div class="table-wrap">
                        <table>
                            <thead>
                                <tr>
                                    <th>{{ first_col }}</th>
                                    <th>{{ metric_table_label }}</th>
                                    <th>{{ running_table_label }}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for r in table_rows %}
                                <tr class="paged-row">
                                    <td>{{ r.label }}</td>
                                    <td>{{ value_format(r[metric_key]) if r[metric_key] is not none else "--" }}</td>
                                    <td>{{ value_format(r[running_key]) if r[running_key] is not none else "--" }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    <div class="table-controls">
                        <button type="button" id="metricTableLoadMore">Load next 20</button>
                        <div class="hint" id="metricTableInfo"></div>
                    </div>
                </details>
                {% else %}
                <div class="empty">No data yet.</div>
                {% endif %}
            </div>

            <div class="card">
                <h2>{{ metric_title }} {{ period_title }} chart</h2>
                {% if rows %}
                <div class="toolbar">
                    <button type="button" onclick="resetZoomSafe(metricChart)">Reset zoom</button>
                </div>
                <div class="chart-wrap">
                    <div class="chart-box">
                        <canvas id="metricChart"></canvas>
                    </div>
                </div>
                <div class="hint">Mouse wheel to zoom, drag to pan, shift + drag to zoom box.</div>
                {% else %}
                <div class="empty">No data yet.</div>
                {% endif %}
            </div>
        </div>

        {% if metric == 'feed' %}
        <div class="summary-grid">
            <div class="summary-card">
                <div class="summary-label">Manual Feed Recorded KG</div>
                <div class="summary-value">{{ shed_feed_stock_label }}</div>
                <div class="summary-note">Manual entries added to this shed in the active crop.</div>
            </div>
        </div>

        <div class="card" style="margin-bottom:14px;">
            <h2>Record Feed For {{ shed_name }}</h2>
            <div class="sub" style="margin-bottom:14px;">Normal silo feeding is recorded automatically from the weigh cells. Use this only for extra feed that the weigh cells will not see, such as floor-fed feed or feed moved between sheds.</div>
            <div class="action-card">
                <form class="action-row" method="post" action="{{ url_for('office_feed_stock_allocate_view') }}">
                    <input type="hidden" name="shed_no" value="{{ shed_no }}">
                    <input type="hidden" name="next" value="{{ feed_page_url }}">
                    <div class="field">
                        <label for="feed_apply_kg">Feed KG</label>
                        <input id="feed_apply_kg" type="number" step="0.1" min="0" name="kg" value="" placeholder="0.0">
                        <input class="inline-note" id="feed_apply_note" type="text" name="note" value="" placeholder="Note, e.g. floor fed or moved from another shed">
                    </div>
                    <button class="full" type="submit">Record Feed</button>
                </form>
            </div>
        </div>

        <div class="feed-extra-grid">
            <div class="card">
                <h2>Manual Feed Entry History</h2>
                {% if shed_stock_rows %}
                <details class="collapse" open>
                    <summary>Open manual feed table</summary>
                    <div class="table-wrap">
                        <table>
                            <thead>
                                <tr><th>Time</th><th>Feed KG</th><th>Note</th></tr>
                            </thead>
                            <tbody>
                                {% for row in shed_stock_rows %}
                                {% if row.kind == "shed_allocation" %}
                                <tr>
                                    <td>{{ row.ts_label }}</td>
                                    <td>{{ row.feed_kg_label }}</td>
                                    <td>{{ row.note if row.note else "--" }}</td>
                                </tr>
                                {% endif %}
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </details>
                {% else %}
                <div class="empty">No manual feed entries recorded for this shed in the current crop yet.</div>
                {% endif %}
            </div>

            <div class="card">
                <h2>Auger Run Timestamps</h2>
                <div id="augerRunsMeta" class="hint">{% if auger_runs_backup_name %}Auger source: {{ auger_runs_backup_name }}{% if auger_runs_backup_at %} at {{ auger_runs_backup_at }}{% endif %}{% else %}No auger source available yet.{% endif %}</div>
                <div id="augerRunsContent">
                    {% if auger_run_rows %}
                    <details class="collapse" open>
                        <summary>Open auger timestamp table</summary>
                        <div class="table-wrap">
                            <table>
                                <thead>
                                    <tr><th>Auger</th><th>Started</th><th>Stopped</th><th>Duration</th><th>Runs</th></tr>
                                </thead>
                                <tbody>
                                    {% for r in auger_run_rows %}
                                    <tr>
                                        <td>{{ r.auger_label }}</td>
                                        <td>{{ r.started_at }}</td>
                                        <td>{{ r.stopped_at }}</td>
                                        <td>{{ r.duration }}</td>
                                        <td>{{ r.run_count_label if r.run_count_label else "1" }}</td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    </details>
                    {% else %}
                    <div class="empty">No auger run timestamps available from the latest controller backup yet.</div>
                    {% endif %}
                </div>
            </div>
        </div>
        {% endif %}
    </div>

<script>
const labels = {{ labels|tojson }};
const values = {{ values|tojson }};
const xAxisTitle = {{ first_col|tojson }};
const yAxisTitle = {{ metric_axis_title|tojson }};
const chartLabel = {{ metric_chart_label|tojson }};
const lineColor = {{ metric_chart_color|tojson }};
const augerRunsApiUrl = {{ auger_runs_api_url|tojson }};
let augerRunsSignature = {{ auger_run_rows|tojson }};
let metricChart = null;

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

function resetZoomSafe(chart) {
    if (chart && chart.resetZoom) chart.resetZoom();
}

function buildChart() {
    const el = document.getElementById('metricChart');
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
            interaction: { mode: 'nearest', intersect: false },
            plugins: {
                legend: { labels: { color: '#f2f2f2' } },
                tooltip: { enabled: true },
                zoom: {
                    limits: { x: { minRange: 1 }, y: { minRange: 1 } },
                    pan: { enabled: true, mode: 'xy' },
                    zoom: {
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        drag: { enabled: true, modifierKey: 'shift' },
                        mode: 'xy'
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#f0f0f0', maxRotation: 60, minRotation: 30, autoSkip: true, maxTicksLimit: 18 },
                    grid: { color: '#818181' },
                    title: { display: true, text: xAxisTitle, color: '#f2f2f2' }
                },
                y: {
                    ticks: { color: '#f0f0f0' },
                    grid: { color: '#818181' },
                    title: { display: true, text: yAxisTitle, color: '#f2f2f2' }
                }
            }
        }
    });
}

function escapeHtml(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderAugerRuns(rows) {
    if (!Array.isArray(rows) || !rows.length) {
        return '<div class="empty">No auger run timestamps available from the latest controller backup yet.</div>';
    }
    let body = '';
    for (const row of rows) {
        body += `<tr><td>${escapeHtml(row.auger_label || '--')}</td><td>${escapeHtml(row.started_at || '--')}</td><td>${escapeHtml(row.stopped_at || '--')}</td><td>${escapeHtml(row.duration || '--')}</td><td>${escapeHtml(row.run_count_label || row.run_count || '1')}</td></tr>`;
    }
    return `
<details class="collapse" open>
    <summary>Open auger timestamp table</summary>
    <div class="table-wrap">
        <table>
            <thead>
                <tr><th>Auger</th><th>Started</th><th>Stopped</th><th>Duration</th><th>Runs</th></tr>
            </thead>
            <tbody>${body}</tbody>
        </table>
    </div>
</details>`;
}

async function refreshAugerRuns() {
    if (!augerRunsApiUrl) return;
    try {
        const resp = await fetch(augerRunsApiUrl, { cache: 'no-store' });
        if (!resp.ok) return;
        const data = await resp.json();
        const rows = Array.isArray(data.rows) ? data.rows : [];
        const nextSignature = JSON.stringify(rows);
        const metaEl = document.getElementById('augerRunsMeta');
        const contentEl = document.getElementById('augerRunsContent');
        if (metaEl) {
            if (data.latest_backup_name) {
                metaEl.textContent = `Auger source: ${data.latest_backup_name}` + (data.latest_backup_at ? ` at ${data.latest_backup_at}` : '');
            } else {
                metaEl.textContent = 'No auger source available yet.';
            }
        }
        if (contentEl && nextSignature !== JSON.stringify(augerRunsSignature)) {
            contentEl.innerHTML = renderAugerRuns(rows);
            augerRunsSignature = rows;
        }
    } catch (err) {
    }
}

metricChart = buildChart();
setupPagedTable('metricTableLoadMore', 'metricTableInfo');
if (augerRunsApiUrl) {
    refreshAugerRuns();
    setInterval(refreshAugerRuns, 60000);
}
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
        * {
            box-sizing: border-box;
        }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #ececec;
            overflow-x: hidden;
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
            min-width: 0;
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
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid #8a8a8a;
            border-radius: 10px;
            background: #686868;
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker {
            display: none;
        }
        .collapse[open] summary {
            margin-bottom: 12px;
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
            -webkit-overflow-scrolling: touch;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            table-layout: fixed;
        }
        th, td {
            border-bottom: 1px solid #818181;
            padding: 8px 6px;
            text-align: left;
            overflow-wrap: anywhere;
            word-break: break-word;
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
        .table-controls {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
            margin-top: 10px;
        }
        @media (max-width: 1200px) {
            .grid { grid-template-columns: 1fr; }
        }
        @media (max-width: 700px) {
            .wrap { padding: 12px; }
            h1 { font-size: 24px; }
            .card { padding: 12px; }
            .toolbar button { width: 100%; }
            .chart-box { height: 320px; }
        }
    </style>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
</head>
<body>
    <div class="wrap">
        <div class="topbar">{{ render_page_nav() }}</div>

        <h1>Bore Hole {{ period_title }}</h1>
        <div class="sub">{{ period_sub }}</div>

        <div class="grid">
            <div class="card">
                <h2>{{ period_title }} list</h2>
                {% if rows %}
                <details class="collapse" open>
                    <summary>Open {{ period_title|lower }} list</summary>
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
                                {% for r in table_rows %}
                                <tr class="paged-row">
                                    <td>{{ r.label }}</td>
                                    <td>{{ "%.1f"|format(r.water) if r.water is not none else "--" }}</td>
                                    <td>{{ "%.1f"|format(r.running_water) if r.running_water is not none else "--" }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    <div class="table-controls">
                        <button type="button" id="boreholeTableLoadMore">Load next 20</button>
                        <div class="hint" id="boreholeTableInfo"></div>
                    </div>
                </details>
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
setupPagedTable('boreholeTableLoadMore', 'boreholeTableInfo');
</script>
</body>
</html>
"""


TV_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Cherry Dene Farm Dashboard TV</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        html, body {
            width: 100%;
            height: 100%;
            margin: 0;
            overflow: hidden;
            background: #5b5b5b;
        }
        #stage {
            position: fixed;
            top: 0;
            left: 0;
            width: 1900px;
            transform-origin: top left;
            background: #5b5b5b;
        }
        #dashboardFrame {
            display: block;
            width: 1900px;
            min-height: 1100px;
            border: 0;
            background: #5b5b5b;
        }
        #fitNotice {
            position: fixed;
            right: 8px;
            bottom: 6px;
            z-index: 2;
            color: rgba(255,255,255,0.45);
            font: 11px Arial, sans-serif;
            pointer-events: none;
        }
    </style>
</head>
<body>
    <div id="stage">
        <iframe id="dashboardFrame" src="/" title="Cherry Dene Farm Dashboard"></iframe>
    </div>
    <div id="fitNotice">/tv</div>
    <script>
        const DESIGN_WIDTH = 1900;
        const MIN_DESIGN_HEIGHT = 1100;
        const stage = document.getElementById('stage');
        const frame = document.getElementById('dashboardFrame');

        function dashboardHeight() {
            try {
                const doc = frame.contentDocument || frame.contentWindow.document;
                const body = doc.body;
                const html = doc.documentElement;
                return Math.max(
                    MIN_DESIGN_HEIGHT,
                    body ? body.scrollHeight : 0,
                    html ? html.scrollHeight : 0
                );
            } catch (err) {
                return MIN_DESIGN_HEIGHT;
            }
        }

        function fitDashboard() {
            const height = dashboardHeight();
            frame.style.height = `${height}px`;
            stage.style.height = `${height}px`;

            const scale = Math.min(
                window.innerWidth / DESIGN_WIDTH,
                window.innerHeight / height
            );
            const safeScale = Math.max(0.1, scale || 1);
            stage.style.transform = `scale(${safeScale})`;
            stage.style.left = `${Math.max(0, (window.innerWidth - (DESIGN_WIDTH * safeScale)) / 2)}px`;
            stage.style.top = `${Math.max(0, (window.innerHeight - (height * safeScale)) / 2)}px`;
        }

        frame.addEventListener('load', () => {
            fitDashboard();
            setTimeout(fitDashboard, 500);
            setTimeout(fitDashboard, 1500);
        });
        window.addEventListener('resize', fitDashboard);
        setInterval(fitDashboard, 2000);
        setInterval(() => {
            try {
                frame.contentWindow.location.reload();
            } catch (err) {
                frame.src = '/';
            }
        }, 30 * 60 * 1000);
    </script>
</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(HTML, **build_dashboard_context())


@app.route("/tv")
def tv_dashboard():
    return render_template_string(TV_HTML, **build_dashboard_context())


@app.route("/events")
def office_events_view():
    return render_template_string(EVENTS_HTML, rows=get_recent_events(250))


@app.route("/crop-reports")
def office_crop_reports_view():
    return render_template_string(
        CROP_REPORTS_HTML,
        rows=list_crop_report_rows(),
        status_msg=request.args.get("msg", ""),
        status_ok=request.args.get("ok", "1") == "1",
    )


@app.route("/crop-reports/<int:crop_id>/download")
def office_crop_report_download(crop_id):
    report_path = ensure_crop_report_file(crop_id, force_rebuild=True)
    if not report_path or not os.path.isfile(report_path):
        return redirect(url_for("office_crop_reports_view", ok=0, msg="Crop report file not found"))
    return send_file(
        report_path,
        as_attachment=True,
        download_name=os.path.basename(report_path),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/crop-reports/<int:crop_id>/resend", methods=["POST"])
def office_crop_report_resend(crop_id):
    try:
        ok, message, _ = resend_crop_report(crop_id)
    except Exception as exc:
        ok = False
        message = str(exc)
    return redirect(url_for("office_crop_reports_view", ok=1 if ok else 0, msg=message))


@app.route("/settings")
def office_settings_view():
    update_status = load_office_update_status()
    checked_at = update_status.get("checked_at")
    latest_backups = list_office_backup_files()
    controller_meta = load_controller_meta()
    collector_status = load_controller_backup_status()
    controller_backup_rows = []
    farm_health = None
    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        meta = controller_meta.get(str(int(shed_no)), {}) if isinstance(controller_meta, dict) else {}
        office_copy = collector_status.get("shed_%d" % shed_no, {}) if isinstance(collector_status, dict) else {}
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
    controller_backup_rows.append({
        "label": "Bore Hole",
        "controller_key": "borehole",
        "last_backup": datetime.fromtimestamp(int(borehole_meta.get("last_backup_ts"))).strftime("%d %b %Y %H:%M:%S") if borehole_meta.get("last_backup_ts") not in [None, ""] else "--",
        "last_backup_status": str(borehole_meta.get("last_backup_status", "") or "--"),
        "office_copy_at": datetime.fromtimestamp(int(borehole_copy.get("last_collected_ts"))).strftime("%d %b %Y %H:%M:%S") if borehole_copy.get("last_collected_ts") not in [None, ""] else "--",
        "office_copy_status": str(borehole_copy.get("last_status", "") or "--"),
        "office_copy_name": os.path.basename(list_controller_backup_files("borehole")[0]) if list_controller_backup_files("borehole") else "--",
    })
    farm_health = compute_farm_health_summary(controller_meta, borehole_meta, collector_status)
    return render_template_string(
        OFFICE_SETTINGS_HTML,
        update_status=update_status,
        update_checked_at=datetime.fromtimestamp(int(checked_at)).strftime("%d %b %Y %H:%M:%S") if checked_at else "--",
        backup_dir=backups_dir(),
        backup_keep_count=OFFICE_BACKUP_KEEP_COUNT,
        latest_backup_name=os.path.basename(latest_backups[0]) if latest_backups else "--",
        email_settings=office_email_settings_form_state(),
        farm_health=farm_health,
        controller_backup_rows=controller_backup_rows,
        status_msg=request.args.get("msg", ""),
        status_ok=request.args.get("ok", "1") == "1",
    )


@app.route("/feed-stock")
def office_feed_stock_view():
    context = build_feed_stock_context(request.args.get("shed_no"))
    return render_template_string(
        MANUAL_FEED_ENTRY_HTML,
        transaction_rows=context["transaction_rows"],
        transaction_count=fmt_value(len(context["transaction_rows"]), "i"),
        active_targets=context["active_targets"],
        preselected_shed_no=context["preselected_shed_no"],
        status_msg=request.args.get("msg", ""),
        status_ok=request.args.get("ok", "1") == "1",
    )


@app.route("/feed-stock/allocate", methods=["POST"])
def office_feed_stock_allocate_view():
    try:
        shed_no = int(request.form.get("shed_no", "").strip())
    except Exception:
        shed_no = None
    try:
        kg = round(float(request.form.get("kg", "").strip()), 3)
    except Exception:
        kg = None
    if shed_no not in SHED_NUMBERS:
        return redirect_with_next("office_feed_stock_view", False, "Choose a valid active shed")
    if kg is None or kg <= 0:
        return redirect_with_next("office_feed_stock_view", False, "Enter a valid shed feed KG", shed_no=shed_no)
    shed_name = shed_name_from_number(shed_no)
    crop_id = get_active_crop_id_for_shed(shed_name)
    if crop_id in [None, ""]:
        return redirect_with_next("office_feed_stock_view", False, "That shed does not have an active crop to apply feed against", shed_no=shed_no)
    note = str(request.form.get("note", "") or "").strip()
    ok = append_feed_stock_transaction("shed_allocation", -kg, note=note, shed_no=shed_no, crop_id=crop_id)
    if ok:
        log_event("office", "manual_feed_recorded", "Manual feed recorded for shed", shed_no=shed_no, detail="%s KG to %s" % (fmt_value(kg, "f1"), fmt_crop_code(crop_id)))
    return redirect_with_next("office_feed_stock_view", ok, "Feed recorded for shed" if ok else "Shed feed entry failed", shed_no=shed_no)


@app.route("/farm-health")
def office_farm_health_view():
    controller_meta = load_controller_meta()
    borehole_meta = load_borehole_meta()
    collector_status = load_controller_backup_status()
    farm_health = compute_farm_health_summary(controller_meta, borehole_meta, collector_status)
    rows = []

    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        label = "Shed %s" % shed_no
        meta = controller_meta.get(str(int(shed_no)), {}) if isinstance(controller_meta, dict) else {}
        office_copy = collector_status.get("shed_%d" % shed_no, {}) if isinstance(collector_status, dict) else {}
        sync_age = controller_sync_age(meta)
        heartbeat_ok = controller_heartbeat_ok(meta)
        heartbeat = ("OK • %ss ago" % sync_age) if heartbeat_ok and sync_age is not None else "STALE"
        pico_ok = effective_pico_connected(meta)
        pico = "Connected" if pico_ok else "Disconnected"
        backup_status = str(meta.get("last_backup_status", "") or "--")
        backup_ok = backup_status != "--" and "fail" not in backup_status.lower()
        office_copy_status = str(office_copy.get("last_status", "") or "--")
        office_copy_ok = office_copy_status != "--" and "failed" not in office_copy_status.lower()
        rows.append({
            "label": label,
            "heartbeat": heartbeat,
            "heartbeat_ok": heartbeat_ok,
            "pico": pico,
            "pico_ok": pico_ok,
            "backup": backup_status,
            "backup_ok": backup_ok,
            "office_copy": office_copy_status,
            "office_copy_ok": office_copy_ok,
        })
        i += 1

    office_copy = collector_status.get("borehole", {}) if isinstance(collector_status, dict) else {}
    sync_age = controller_sync_age(borehole_meta)
    heartbeat_ok = controller_heartbeat_ok(borehole_meta)
    heartbeat = ("OK • %ss ago" % sync_age) if heartbeat_ok and sync_age is not None else "STALE"
    pico_ok = effective_pico_connected(borehole_meta)
    pico = "Connected" if pico_ok else "Disconnected"
    backup_status = str(borehole_meta.get("last_backup_status", "") or "--")
    backup_ok = backup_status != "--" and "fail" not in backup_status.lower()
    office_copy_status = str(office_copy.get("last_status", "") or "--")
    office_copy_ok = office_copy_status != "--" and "failed" not in office_copy_status.lower()
    rows.append({
        "label": "Bore Hole",
        "heartbeat": heartbeat,
        "heartbeat_ok": heartbeat_ok,
        "pico": pico,
        "pico_ok": pico_ok,
        "backup": backup_status,
        "backup_ok": backup_ok,
        "office_copy": office_copy_status,
        "office_copy_ok": office_copy_ok,
    })

    return render_template_string(FARM_HEALTH_HTML, farm_health=farm_health, rows=rows)


@app.route("/settings/update/check", methods=["POST"])
def office_check_update_view():
    check_office_update()
    return redirect(url_for("office_settings_view"))


@app.route("/settings/email/save", methods=["POST"])
def office_save_email_settings_view():
    try:
        save_office_email_settings_from_form(request.form)
        return redirect(url_for("office_settings_view", ok=1, msg="Email settings saved"))
    except Exception as exc:
        return redirect(url_for("office_settings_view", ok=0, msg="Email settings save failed: %s" % exc))


@app.route("/settings/email/add-recipient", methods=["POST"])
def office_add_email_recipient_view():
    try:
        add_office_email_recipient(request.form.get("recipient_email", ""))
        return redirect(url_for("office_settings_view", ok=1, msg="Recipient added"))
    except Exception as exc:
        return redirect(url_for("office_settings_view", ok=0, msg=str(exc)))


@app.route("/settings/email/remove-recipient", methods=["POST"])
def office_remove_email_recipient_view():
    try:
        remove_office_email_recipient(request.form.get("recipient_email", ""))
        return redirect(url_for("office_settings_view", ok=1, msg="Recipient removed"))
    except Exception as exc:
        return redirect(url_for("office_settings_view", ok=0, msg=str(exc)))


@app.route("/settings/update/apply", methods=["POST"])
def office_apply_update_view():
    status = check_office_update()
    if not status.get("update_available"):
        return redirect(url_for("office_settings_view", ok=1, msg="Office dashboard is already up to date"))

    branch = status.get("branch", "main")
    code, stdout, stderr = run_office_git_command(["pull", "--ff-only", "origin", branch], timeout=60)
    local_git = get_office_git_status()
    save_office_update_status({
        "checked_at": int(time.time()),
        "status": "Update applied. Restarting office dashboard..." if code == 0 else (stderr or stdout or "Update failed"),
        "local_commit": local_git.get("local_commit", "--"),
        "remote_commit": local_git.get("local_commit", "--") if code == 0 else status.get("remote_commit", "--"),
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
    maybe_collect_controller_backups(force=True)
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


@app.route("/api/notifications")
def dashboard_notifications_api():
    try:
        since_ts = int(request.args.get("since", "0") or 0)
    except Exception:
        since_ts = 0

    events = build_notification_events_since(since_ts)
    active_alarms = build_active_alarm_notifications()
    latest_ts = since_ts

    i = 0
    while i < len(events):
        try:
            latest_ts = max(latest_ts, int(events[i].get("ts") or 0))
        except Exception:
            pass
        i += 1

    return jsonify({
        "generated_ts": int(time.time()),
        "latest_ts": latest_ts,
        "events": events,
        "active_alarms": active_alarms,
    })


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


@app.route("/shed/<int:shed_no>/tables-graphs")
def shed_tables_graphs_view(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    return redirect(url_for("shed_metric_period_view", shed_no=shed_no, metric="feed", period="hourly"))


@app.route("/shed/<int:shed_no>/<metric>/<period>")
def shed_metric_period_view(shed_no, metric, period):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    if metric not in ["feed", "water"]:
        abort(404)
    if period not in ["hourly", "daily"]:
        abort(404)

    shed_name = shed_name_from_number(shed_no)
    active_crop_id = get_active_crop_id_for_shed(shed_name)
    active_crop = active_crop_record_for_shed(shed_name)
    active_crop_code = fmt_crop_code(active_crop_id, active_crop.get("placement_epoch"))
    showing_out_of_crop = active_crop_id in [None, ""]
    rows, period_title, first_col = shed_rows_for_period(shed_name, period, crop_id=active_crop_id)

    if metric == "feed":
        metric_title = "Feed"
        metric_key = "feed"
        running_key = "running_feed"
        metric_table_label = "Feed KG"
        running_table_label = "Running Feed KG"
        metric_axis_title = "Feed KG"
        metric_chart_label = "Feed KG"
        metric_chart_color = "#35d07f"
        value_format = lambda v: "%.2f" % float(v)
    else:
        metric_title = "Water"
        metric_key = "water"
        running_key = "running_water"
        metric_table_label = "Water L"
        running_table_label = "Running Water L"
        metric_axis_title = "Water L"
        metric_chart_label = "Water L"
        metric_chart_color = "#4db6ff"
        value_format = lambda v: "%.1f" % float(v)

    if showing_out_of_crop:
        period_sub = "Out-of-crop %s %s table and zoomable chart." % (period_title.lower(), metric_title.lower())
    else:
        period_sub = "Current crop %s %s %s table and zoomable chart." % (active_crop_code, period_title.lower(), metric_title.lower())

    labels = []
    values = []
    i = 0
    while i < len(rows):
        labels.append(rows[i]["label"])
        values.append(rows[i].get(metric_key))
        i += 1

    feed_page_url = url_for("shed_metric_period_view", shed_no=shed_no, metric="feed", period=period)
    status_msg = request.args.get("msg", "")
    status_ok = request.args.get("ok", "1") == "1"
    shed_feed_stock_label = fmt_value(0, "f1")
    shed_stock_rows = []
    auger_run_rows = []
    auger_runs_backup_name = ""
    auger_runs_backup_at = ""
    auger_runs_api_url = ""
    if metric == "feed":
        stock_context = build_feed_stock_context(shed_no)
        live_auger_runs = fetch_live_auger_runs_from_controller(shed_no, limit=200)
        if live_auger_runs.get("ok"):
            auger_run_rows = live_auger_runs.get("rows", [])
            auger_runs_backup_name = str(live_auger_runs.get("source_label") or "")
            auger_runs_backup_at = str(live_auger_runs.get("updated_at") or "")
        else:
            auger_run_rows = auger_runs_from_latest_controller_backup(shed_no, limit=200)
            backup_info = latest_controller_backup_info("shed_%d" % shed_no)
            auger_runs_backup_name = str(backup_info.get("name") or "")
            collected_at = backup_info.get("collected_at")
            if collected_at not in [None, ""]:
                try:
                    auger_runs_backup_at = datetime.fromtimestamp(int(collected_at)).strftime("%d %b %Y %H:%M:%S")
                except Exception:
                    auger_runs_backup_at = ""
        auger_runs_api_url = url_for("shed_auger_runs_api_get", shed_no=shed_no)
        if active_crop_id not in [None, ""]:
            shed_feed_stock_label = fmt_value(feed_stock_allocated_kg_for_target(shed_no, active_crop_id), "f1")

        tx_rows = stock_context.get("transaction_rows", [])
        i = 0
        while i < len(tx_rows):
            row = tx_rows[i]
            try:
                if int(row.get("shed_no")) != int(shed_no):
                    i += 1
                    continue
            except Exception:
                i += 1
                continue
            if active_crop_id not in [None, ""]:
                try:
                    if int(row.get("crop_id")) != int(active_crop_id):
                        i += 1
                        continue
                except Exception:
                    i += 1
                    continue
            shed_stock_rows.append(row)
            i += 1

    return render_template_string(
        METRIC_PERIOD_HTML,
        shed_name=shed_name,
        shed_no=shed_no,
        metric=metric,
        metric_title=metric_title,
        period=period,
        period_title=period_title,
        period_sub=period_sub,
        first_col=first_col,
        rows=rows,
        table_rows=list(reversed(rows)),
        labels=labels,
        values=values,
        metric_key=metric_key,
        running_key=running_key,
        metric_table_label=metric_table_label,
        running_table_label=running_table_label,
        metric_axis_title=metric_axis_title,
        metric_chart_label=metric_chart_label,
        metric_chart_color=metric_chart_color,
        value_format=value_format,
        feed_page_url=feed_page_url,
        status_msg=status_msg,
        status_ok=status_ok,
        shed_feed_stock_label=shed_feed_stock_label,
        auger_run_rows=auger_run_rows,
        auger_runs_backup_name=auger_runs_backup_name,
        auger_runs_backup_at=auger_runs_backup_at,
        auger_runs_api_url=auger_runs_api_url,
        shed_stock_rows=shed_stock_rows,
    )


@app.route("/shed/<int:shed_no>/thresholds")
def shed_thresholds_view(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    shed_name = shed_name_from_number(shed_no)
    status_msg = request.args.get("msg", "")
    status_ok = request.args.get("ok", "1") == "1"
    return render_template_string(
        SHED_THRESHOLDS_HTML,
        shed_no=shed_no,
        shed_name=shed_name,
        row=office_environment_settings_row_for_shed(shed_no),
        status_msg=status_msg,
        status_ok=status_ok,
    )


@app.route("/shed/<int:shed_no>/thresholds/save", methods=["POST"])
def shed_thresholds_save_view(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    try:
        save_office_environment_settings_for_shed(shed_no, request.form)
        return redirect(url_for("shed_thresholds_view", shed_no=shed_no, ok=1, msg="Tile thresholds saved"))
    except Exception as exc:
        return redirect(url_for("shed_thresholds_view", shed_no=shed_no, ok=0, msg="Threshold save failed: %s" % exc))


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


@app.route("/api/shed/<int:shed_no>/auger-runs", methods=["GET"])
def shed_auger_runs_api_get(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    live = fetch_live_auger_runs_from_controller(shed_no, limit=200)
    if live.get("ok"):
        return jsonify({
            "rows": live.get("rows", []),
            "latest_backup_name": live.get("source_label", "Live controller feed"),
            "latest_backup_at": live.get("updated_at", ""),
        })
    info = latest_controller_backup_info("shed_%d" % shed_no)
    collected_at = info.get("collected_at")
    return jsonify({
        "rows": auger_runs_from_latest_controller_backup(shed_no, limit=200),
        "latest_backup_name": info.get("name") or "",
        "latest_backup_at": datetime.fromtimestamp(int(collected_at)).strftime("%d %b %Y %H:%M:%S") if collected_at not in [None, ""] else "",
    })


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
    ended_entries = state.get(shed_name, {}).get("ended_entries", {})

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
    prev_rec = dict(rec)

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
    if str(dest_shed) in ended_entries:
        del ended_entries[str(dest_shed)]
    save_shed_entries_state(state)
    if bird_count == 0:
        refresh_farm_crop_current_id(state)
        if had_active_crop:
            prev_rec["updated_ts"] = now_ts
            prev_rec["updated_by"] = "dashboard"
            log_crop_event(shed_name, prev_rec, False)
        log_event("office", "entry_cleared", "Entry saved as zero birds", shed_no=shed_no, detail="Entry Shed %d" % dest_shed)
    else:
        log_event("office", "entry_saved", "Bird count saved", shed_no=shed_no, detail="Entry Shed %d = %d" % (dest_shed, bird_count))
    push_shed_state_to_controller_async(shed_no)
    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg="Entry saved"))


@app.route("/shed/<int:shed_no>/entry/<int:dest_shed>/start", methods=["POST"])
def shed_entry_start(shed_no, dest_shed):
    if shed_no not in SHED_NUMBERS or dest_shed not in SHED_NUMBERS:
        abort(404)

    state = load_shed_entries_state()
    shed_name = shed_name_from_number(shed_no)
    entries = ensure_shed_entry_bucket(state, shed_name)
    ended_entries = state.get(shed_name, {}).get("ended_entries", {})

    rec = entries.get(str(dest_shed), {
        "bird_count": 0,
        "crop_active": 0,
        "placement_epoch": None,
        "crop_id": None,
        "updated_ts": None,
        "updated_by": "dashboard",
    })
    rec = clean_entry_record(rec)

    raw = str(request.form.get("bird_count", "") or "").strip()
    placement_at_raw = request.form.get("placement_at", "")
    if raw != "":
        try:
            bird_count = int(raw)
            if bird_count < 0:
                raise ValueError()
            rec["bird_count"] = bird_count
            rec["updated_ts"] = int(time.time())
            rec["updated_by"] = "dashboard"
        except Exception:
            return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Invalid bird count"))

    try:
        bird_count = int(rec.get("bird_count", 0) or 0)
    except Exception:
        bird_count = 0

    if bird_count <= 0:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Set birds before starting"))

    placement_epoch = parse_datetime_local_value(placement_at_raw)
    if str(placement_at_raw or "").strip() and placement_epoch is None:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Invalid placement date"))
    now_ts = int(time.time())
    if placement_epoch is not None and placement_epoch > now_ts:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Placement date cannot be in the future"))

    other_shed = active_entry_location_for_dest(state, dest_shed, exclude_shed_name=shed_name)
    if other_shed:
        return redirect(
            url_for(
                "shed_detail",
                shed_no=shed_no,
                ok=0,
                msg="Entry Shed %d is already active in %s" % (dest_shed, other_shed),
            )
        )

    rec["crop_active"] = 1
    if placement_epoch is not None:
        rec["placement_epoch"] = placement_epoch
    elif rec.get("placement_epoch") is None:
        rec["placement_epoch"] = now_ts
    if rec.get("crop_id") in [None, ""]:
        rec["crop_id"] = crop_id_for_new_start(state)
    rec["updated_ts"] = now_ts
    rec["updated_by"] = "dashboard"

    entries[str(dest_shed)] = rec
    if str(dest_shed) in ended_entries:
        del ended_entries[str(dest_shed)]
    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)
    log_crop_event(shed_name, rec, True)
    log_event("office", "entry_started", "Entry started", shed_no=shed_no, detail="Entry Shed %d Crop %s" % (dest_shed, rec.get("crop_id")))
    push_shed_state_to_controller_async(shed_no)
    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg="Entry started"))


@app.route("/shed/<int:shed_no>/entry/<int:dest_shed>/end", methods=["POST"])
def shed_entry_end(shed_no, dest_shed):
    if shed_no not in SHED_NUMBERS or dest_shed not in SHED_NUMBERS:
        abort(404)

    state = load_shed_entries_state()
    shed_name = shed_name_from_number(shed_no)
    entries = ensure_shed_entry_bucket(state, shed_name)
    ended_entries = state.get(shed_name, {}).get("ended_entries", {})

    rec = entries.get(str(dest_shed))
    if not rec:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Entry not found"))

    rec = clean_entry_record(rec)
    rec["updated_ts"] = int(time.time())
    rec["updated_by"] = "dashboard"
    log_crop_event(shed_name, rec, False)
    ended_entries[str(dest_shed)] = int(time.time())
    del entries[str(dest_shed)]
    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)
    log_event("office", "entry_ended", "Entry ended", shed_no=shed_no, detail="Entry Shed %d" % dest_shed)
    push_shed_state_to_controller_async(shed_no)

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
    try:
        dest_active = int(dest_rec.get("crop_active", 0) or 0)
    except Exception:
        dest_active = 0

    same_crop = str(dest_rec.get("crop_id")) == str(rec.get("crop_id"))
    same_epoch = str(dest_rec.get("placement_epoch")) == str(rec.get("placement_epoch"))
    duplicate_move = existing > 0 and dest_active == 1 and same_crop and same_epoch

    if existing > 0 and dest_active == 1 and not duplicate_move:
        return redirect(
            url_for(
                "shed_detail",
                shed_no=shed_no,
                ok=0,
                msg="Destination already has active birds for that entry",
            )
        )

    dest_rec["bird_count"] = existing if duplicate_move else (existing + bird_count)
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

    moved_mortality = move_mortality_history_between_sheds(
        from_name,
        to_name,
        dest_shed,
        rec.get("crop_id"),
    )

    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)
    log_event("office", "entry_moved", "Entry moved between sheds", shed_no=shed_no, detail="Entry Shed %d moved to Shed %d" % (dest_shed, dest_shed))
    if duplicate_move:
        log_event(
            "office",
            "entry_move_duplicate_blocked",
            "Duplicate shed move suppressed",
            shed_no=shed_no,
            detail="Entry Shed %d already present in Shed %d" % (dest_shed, dest_shed),
        )
    if moved_mortality > 0:
        log_event(
            "office",
            "mortality_moved",
            "Mortality moved with active entry",
            shed_no=shed_no,
            detail="Moved %d mortality rows from %s to %s for Entry Shed %d" % (moved_mortality, from_name, to_name, dest_shed),
        )
    push_shed_state_to_controller_async(shed_no)
    push_shed_state_to_controller_async(dest_shed)
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
    changed = apply_external_shed_entries(shed_no, incoming_entries, source="controller", controller_meta=incoming_controller_meta)
    if isinstance(incoming_controller_meta, dict):
        save_controller_meta_for_shed(shed_no, incoming_controller_meta)
        save_live_snapshot_for_shed(shed_no, incoming_controller_meta)
        update_shed_hourly_metrics_from_meta(shed_no, incoming_controller_meta)
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
    rows = get_hourly_history_for_shed(shed_name, max_points=168, crop_id=active_crop_id, include_manual_feed=True)
    rows = aggregate_history_rows_by_hours(rows, bucket_hours=6)

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
        period_sub = "Bore Hole completed 6am-6am daily list with running totals and zoomable water chart."
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
        table_rows=list(reversed(rows)),
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


@app.route("/shed/<int:shed_no>/crop/<int:crop_id>")
def shed_crop_summary_view(shed_no, crop_id):
    if shed_no not in SHED_NUMBERS:
        abort(404)

    shed_name = shed_name_from_number(shed_no)
    summary = build_crop_summary_for_shed(shed_name, crop_id)
    farm_summary = build_farm_crop_summary(crop_id)
    daily_rows = summary.pop("daily_rows", [])

    summary["birds_placed"] = fmt_value(summary.get("birds_placed"), "i")
    summary["birds_remaining_end"] = fmt_value(summary.get("birds_remaining_end"), "i")
    summary["mortality_total"] = fmt_value(summary.get("mortality_total"), "i")
    summary["mortality_pct"] = fmt_value(summary.get("mortality_pct"), "f1")
    summary["manual_feed_adjustment_kg"] = fmt_value(summary.get("manual_feed_adjustment_kg"), "f1")
    summary["total_feed"] = fmt_value(summary.get("total_feed"), "f1")
    summary["feed_bin_end_kg"] = fmt_value(summary.get("feed_bin_end_kg"), "f1")
    summary["total_water"] = fmt_value(summary.get("total_water"), "f0")
    summary["avg_daily_feed"] = fmt_value(summary.get("avg_daily_feed"), "f1")
    summary["avg_daily_water"] = fmt_value(summary.get("avg_daily_water"), "f0")
    summary["peak_daily_feed"] = fmt_value(summary.get("peak_daily_feed"), "f1")
    summary["peak_daily_water"] = fmt_value(summary.get("peak_daily_water"), "f0")
    summary["feed_per_bird"] = fmt_value(summary.get("feed_per_bird"), "f3")
    summary["water_per_bird"] = fmt_value(summary.get("water_per_bird"), "f1")
    summary["crop_days"] = fmt_value(summary.get("crop_days"), "i")
    summary["hourly_points"] = fmt_value(summary.get("hourly_points"), "i")
    summary["complete_days"] = fmt_value(summary.get("complete_days"), "i")
    summary["mortality_events"] = fmt_value(summary.get("mortality_events"), "i")
    try:
        mortality_total_i = int(summary.get("mortality_total").replace(",", "")) if summary.get("mortality_total") not in [None, "--"] else 0
    except Exception:
        mortality_total_i = 0
    summary["mortality_display"] = (
        "%s (%s%%)" % (summary["mortality_total"], summary["mortality_pct"])
        if mortality_total_i > 0 and summary.get("mortality_pct") not in [None, "--"]
        else summary["mortality_total"]
    )

    return render_template_string(
        CROP_SUMMARY_HTML,
        shed_name=shed_name,
        shed_no=shed_no,
        summary=summary,
        daily_rows=daily_rows,
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
        rows = get_hourly_history_for_shed(shed_name, max_points=0, crop_id=crop_id, include_manual_feed=True)
        if rows:
            try:
                crop_start_epoch = int(rows[0].get("epoch"))
            except Exception:
                crop_start_epoch = None
        rows = aggregate_history_rows_by_hours(rows, bucket_hours=6)
        rows = add_running_totals(rows)
        period_title = "%s 6 Hour" % fmt_crop_code(crop_id, crop_start_epoch)
        period_sub = "Historic crop %s 6-hour list with running totals and separate zoomable feed and water charts." % fmt_crop_code(crop_id, crop_start_epoch)
        first_col = "6 Hour Block"
    else:
        rows = get_daily_history_for_shed(shed_name, max_days=0, crop_id=crop_id, include_manual_feed=True)
        if rows:
            try:
                crop_start_epoch = int(rows[0].get("bucket_start_epoch"))
            except Exception:
                crop_start_epoch = None
        rows = add_running_totals(rows)
        period_title = "%s Daily" % fmt_crop_code(crop_id, crop_start_epoch)
        period_sub = "Historic crop %s completed 6am-6am daily list with running totals and separate zoomable feed and water charts." % fmt_crop_code(crop_id, crop_start_epoch)
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
        table_rows=list(reversed(rows)),
        labels=labels,
        feed_values=feed_values,
        water_values=water_values,
    )


if __name__ == "__main__":
    ensure_data_dir()
    start_office_background_workers()
    app.run(host="0.0.0.0", port=8090)
