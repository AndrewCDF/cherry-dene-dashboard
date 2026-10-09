from flask import Flask, render_template_string, abort, url_for, request, redirect, jsonify, Response, send_file
import functools
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
import uuid
import zipfile
from collections import deque
from datetime import datetime, timedelta
from email.message import EmailMessage
from markupsafe import Markup, escape
from xml.sax.saxutils import escape as xml_escape

app = Flask(__name__)
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
STOCKSENSE_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CDF_APP_ICON_PATH = os.path.join(STOCKSENSE_ICON_DIR, "stocksense-icon-180.png")
FAVICON_PNG_PATH = os.path.join(STOCKSENSE_ICON_DIR, "stocksense-icon-64.png")

FAVICON_HEAD_HTML = (
    '<link rel="icon" type="image/png" href="/favicon.png">'
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
    '<link rel="manifest" href="/manifest.webmanifest">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-title" content="StockSense">'
    '<meta name="theme-color" content="#ffffff">'
)


def render_page_nav():
    previous_href = request.referrer or url_for("dashboard")
    dashboard_href = url_for("dashboard")
    return Markup(
        (
            '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">'
            '<a href="{previous_href}" onclick="if (window.history.length > 1) {{ window.history.back(); return false; }}" '
            'style="display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:10px 16px;'
            'border-radius:999px;border: 1px solid #d5dde6;background: #f5f8fb;color: #0d2b4a;text-decoration:none;'
            'font-weight:700;line-height:1;box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);">'
            '← Previous Page</a>'
            '<a href="{dashboard_href}" '
            'style="display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:10px 16px;'
            'border-radius:999px;border: 1px solid #d5dde6;background: #f5f8fb;color: #0d2b4a;text-decoration:none;'
            'font-weight:700;line-height:1;box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);">'
            'Return To Dashboard</a>'
            "</div>"
        ).format(
            previous_href=escape(previous_href),
            dashboard_href=escape(dashboard_href),
        )
    )


app.jinja_env.globals["render_page_nav"] = render_page_nav


# ---------------------------------------------------------------------------
# Office pages in the shed controller's style: OFFICE_PAGE_HEAD is the controller's
# ENTRY_PAGE_HEAD (same fonts, cards, buttons, inputs), and office_topbar() is the same
# white header with Back / Overview, the page title and the logo.
# ---------------------------------------------------------------------------
OFFICE_PAGE_HEAD = """
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


def office_topbar(title):
    back_href = request.referrer or url_for("dashboard")
    return Markup(
        '<header class="topbar ss-topbar">'
        '<a class="back" href="{back}" onclick="if (window.history.length > 1) {{ window.history.back(); return false; }}">&larr; Back</a>'
        '<a class="back" href="{home}">&#8962; Overview</a>'
        '<div class="title cond">{title}</div>'
        '<img class="brand-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">'
        '</header>'
    ).format(back=escape(back_href), home=escape(url_for("dashboard")), title=escape(title))


app.jinja_env.globals["office_page_head"] = Markup(OFFICE_PAGE_HEAD)
app.jinja_env.globals["office_topbar"] = office_topbar


# Shared rules that give the office's simpler table / status pages the controller look
# without rewriting their contents (panels, status cards, detail rows, links, pills).
OFFICE_COMPAT_CSS = """
<style>
  .panel, .card, .table-card, .health-card { background: var(--card); border-radius: 14px; padding: 18px; margin-bottom: 16px; border: 0; }
  .wrap > .sub, .panel > .sub, .card > .sub { color: var(--muted); font-size: 15px; margin: 0 0 12px; }
  .wrap > .sub { margin: 0 4px 16px; }
  h2 { margin: 0 0 10px; font-family: "Barlow Semi Condensed", "Barlow", sans-serif; font-size: 22px; font-weight: 600; color: var(--navy); }
  .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .summary-grid .card, .health-card { margin-bottom: 0; padding: 14px 18px; }
  .health-label, .metric-label { font-size: 13px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
  .health-value, .metric-value { margin-top: 2px; font-family: "Barlow Semi Condensed", "Barlow", sans-serif; font-size: 30px; font-weight: 600; color: var(--navy); line-height: 1.1; }
  .health-note, .metric-sub { font-size: 14px; color: var(--muted); }
  .grid, .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
  .grid > .panel, .two-col > .card { margin-bottom: 0; }
  .detail { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-top: 1px solid var(--track); font-size: 16px; }
  .detail .label { color: var(--muted); }
  details.collapse { margin-top: 6px; }
  details.collapse > summary { cursor: pointer; color: var(--navy); font-weight: 600; font-size: 15px; min-height: 40px; display: flex; align-items: center; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .actions form { margin: 0; }
  .action-link, .actions a, .actions button { display: inline-flex; align-items: center; justify-content: center; width: auto; min-height: 44px; padding: 0 16px; border-radius: 12px;
    border: 1px solid #c5d0dc; background: var(--card-2); color: var(--text); font: inherit; font-size: 15px; font-weight: 600; text-decoration: none; cursor: pointer; }
  .action-link:hover, .actions a:hover { background: var(--track); }
  .state-ok { color: #1e6b16; font-weight: 600; } .state-bad { color: #8f1f1f; font-weight: 600; }
  .pill, .status-pill { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 999px; font-size: 13px; font-weight: 600; background: var(--card-2); color: var(--muted); }
  .pill.emailed, .pill.generated, .status-pill.ok { background: #e3f4e1; color: #1e6b16; }
  .pill.failed { background: #fdecec; color: #8f1f1f; }
  .pill.processing, .pill.queued { background: #fff4e5; color: #9a4b00; }
  .msg.bad, .status.err { background: #fdecec; border-color: #e3a0a0; color: #8f1f1f; }
  .status { margin-bottom: 14px; padding: 12px 16px; border-radius: 12px; background: #e3f4e1; border: 1px solid #9fd39a; color: #1e6b16; font-weight: 600; }
  .empty { color: var(--muted); padding: 8px 0; }
  .mono, .path { font-family: ui-monospace, Menlo, monospace; font-size: 13px; overflow-wrap: anywhere; }
  td button, td .action-link { width: auto; min-height: 40px; padding: 0 12px; font-size: 14px; }
  @media (max-width: 860px) { .grid, .two-col { grid-template-columns: 1fr; } }
</style>
"""
app.jinja_env.globals["office_compat_css"] = Markup(OFFICE_COMPAT_CSS)


@app.route("/favicon.ico")
@app.route("/favicon.png")
@app.route("/favicon.svg")
def favicon_view():
    return send_file(FAVICON_PNG_PATH, mimetype="image/png", max_age=300)


@app.route("/apple-touch-icon.png")
@app.route("/apple-touch-icon-precomposed.png")
def apple_touch_icon_view():
    return send_file(CDF_APP_ICON_PATH, mimetype="image/png", max_age=300)


@app.route("/manifest.webmanifest")
def web_manifest_view():
    return jsonify({
        "name": "StockSense",
        "short_name": "StockSense",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#eef2f6",
        "theme_color": "#ffffff",
        "icons": [
            {"src": "/static/stocksense-icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/stocksense-icon-512.png", "sizes": "512x512", "type": "image/png"},
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


# Shared look matching the shed controllers' dark theme. Injected after each page's own
# styles so it wins; status colours, glows and alarm cards keep their own colours.
OFFICE_THEME_HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Semi+Condensed:wght@500;600;700&display=swap">'
    '<link id="cdf-theme" rel="stylesheet" href="/static/stocksense-theme.css?v=2">'
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
            changed = False
            if "<head>" in body and 'rel="icon"' not in body:
                body = body.replace('<head>', '<head>' + FAVICON_HEAD_HTML, 1)
                changed = True
            if "</head>" in body and 'cdf-theme' not in body:
                body = body.replace('</head>', OFFICE_THEME_HEAD + '</head>', 1)
                changed = True
            if changed:
                response.set_data(body)
                response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception:
        pass
    return response

DATA_DIR = os.path.join(APP_ROOT, "data")
SHED_NUMBERS = [1, 2, 3, 4, 6, 7, 8, 9, 10]
ENTRY_SHED_NUMBERS = [1, 2, 3, 4, 6, 61, 7, 8, 9, 10]
ENTRY_SHED_LABELS = {
    61: "Shed 6B",
}
SHED_DISPLAY_LABELS = {
    6: "Shed 6 & 6B",
}
OFFICE_AUTO_BACKUP_INTERVAL_SECONDS = 3600
OFFICE_AUTO_BACKUP_CHECK_SECONDS = 60
FEED_RECORDING_MIN_DROP_KG = 1.0
FEED_RECORDING_REFILL_RISE_KG = 8.0
FEED_RECORDING_NOISE_FACTOR = 2.0
FEED_REFILL_SETTLING_SECONDS = 5 * 60
FEED_MOVEMENT_APPLY_MIN_KG = 0.5
FEED_MOVEMENT_SESSION_GAP_SECONDS = 150
_office_backup_lock = threading.Lock()
_event_log_lock = threading.Lock()
_json_line_cache_lock = threading.Lock()


# Every load -> change -> save of shed_entries.json holds this lock, so an office edit
# and a controller sync arriving together can't overwrite each other.
_shed_entries_lock = threading.RLock()


def shed_entries_locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _shed_entries_lock:
            return fn(*args, **kwargs)
    return wrapper


_json_line_cache = {}
EVENT_LOG_MAX_BYTES = 5 * 1024 * 1024
EVENT_LOG_KEEP_LINES = 10000
NOTIFICATION_LOG_MAX_BYTES = 1024 * 1024
NOTIFICATION_LOG_KEEP_LINES = 1000


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
    with _json_line_cache_lock:
        _json_line_cache.pop(os.path.abspath(path), None)


def read_all_json_lines(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return []

    try:
        stat = os.stat(path)
        cache_key = os.path.abspath(path)
        signature = (stat.st_mtime_ns, stat.st_size)
        with _json_line_cache_lock:
            cached = _json_line_cache.get(cache_key)
            if cached and cached[0] == signature:
                return list(cached[1])
    except Exception:
        cache_key = None
        signature = None

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
    if cache_key is not None and signature is not None:
        with _json_line_cache_lock:
            _json_line_cache[cache_key] = (signature, out)
    return out


def read_recent_json_lines(filename, limit=200):
    path = os.path.join(DATA_DIR, filename)
    try:
        limit = max(0, int(limit))
    except Exception:
        limit = 200
    if limit <= 0 or not os.path.exists(path):
        return []

    lines = []
    remainder = b""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            position = f.tell()
            while position > 0 and len(lines) < limit:
                read_size = min(65536, position)
                position -= read_size
                f.seek(position)
                block = f.read(read_size) + remainder
                parts = block.splitlines()
                if position > 0 and parts:
                    remainder = parts[0]
                    parts = parts[1:]
                else:
                    remainder = b""
                lines = parts + lines
    except Exception:
        return []

    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line.decode("utf-8")))
        except Exception:
            pass
    return out


def compact_json_line_log(filename, max_bytes, keep_lines):
    path = os.path.join(DATA_DIR, filename)
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= int(max_bytes):
            return False
    except Exception:
        return False

    recent = deque(maxlen=max(1, int(keep_lines)))
    try:
        with open(path, "r") as f:
            for line in f:
                if line.strip():
                    recent.append(line if line.endswith("\n") else line + "\n")
        parent = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=parent)
        with os.fdopen(fd, "w") as f:
            for line in recent:
                f.write(line)
        os.replace(tmp, path)
        with _json_line_cache_lock:
            _json_line_cache.pop(os.path.abspath(path), None)
        return True
    except Exception:
        try:
            if "tmp" in locals() and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


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
    with _json_line_cache_lock:
        _json_line_cache.pop(os.path.abspath(path), None)


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


CLIMATE_LIMIT_KEYS = ["temp_low_c", "temp_high_c", "temp_amber_margin_c", "rh_low_pct", "rh_high_pct", "rh_amber_margin_pct"]


def office_climate_limits_ts(shed_no):
    # When the office last changed this shed's temperature / humidity limits.
    # 0 = an office override saved before change tracking existed; None = no override.
    cfg = load_office_config()
    raw = cfg.get("shed_environment_limits", {})
    if not isinstance(raw, dict) or str(int(shed_no)) not in raw:
        return None
    stamps = cfg.get("shed_climate_limits_ts", {})
    try:
        return int((stamps if isinstance(stamps, dict) else {}).get(str(int(shed_no))) or 0)
    except Exception:
        return 0


def adopt_controller_climate_limits(shed_no, meta):
    # Temperature / humidity limits are kept the same on the office and the shed
    # controller: whichever side changed them last wins. Called on every controller sync.
    meta = meta if isinstance(meta, dict) else {}
    try:
        controller_ts = int(meta.get("climate_limits_updated_ts"))
    except Exception:
        return False
    office_ts = office_climate_limits_ts(shed_no)
    if office_ts is None or controller_ts <= office_ts:
        return False
    cfg = load_office_config()
    raw = cfg.get("shed_environment_limits", {})
    current = clean_environment_limits(raw.get(str(int(shed_no))))
    for key in CLIMATE_LIMIT_KEYS:
        if meta.get(key) is not None:
            current[key] = meta.get(key)
    raw[str(int(shed_no))] = clean_environment_limits(current)
    stamps = cfg.get("shed_climate_limits_ts", {})
    stamps = stamps if isinstance(stamps, dict) else {}
    stamps[str(int(shed_no))] = controller_ts
    cfg["shed_environment_limits"] = raw
    cfg["shed_climate_limits_ts"] = stamps
    save_office_config(cfg)
    return True


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
    row = {
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
    # These fill number boxes, which show nothing for "2,000" or "--", so give them plain numbers.
    for key in list(row.keys()):
        if key != "shed_no":
            row[key] = "" if row[key] == "--" else str(row[key]).replace(",", "")
    return row


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
    stamps = cfg.get("shed_climate_limits_ts", {})
    stamps = stamps if isinstance(stamps, dict) else {}
    stamps[str(shed_no)] = int(time.time())
    cfg["shed_climate_limits_ts"] = stamps
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


def prune_controller_backup_files(controller_key, newest_path=None):
    prune_backups_layered(list_controller_backup_files(controller_key), newest_path=newest_path)


def list_office_backup_files():
    # Newest first, by the time each backup was made. (Sorting by name put any
    # "office_manual_" file ahead of every "office_auto_" one, so the office thought its
    # last backup was old and made a new one every minute.)
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
        path, healthy = mark_backup_suspect_if_bad(path)
        if healthy:
            prune_backups_layered(list_office_backup_files())
        else:
            log_event("office", "backup_suspect", "Office backup failed its check; older backups kept", detail=os.path.basename(path))
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
        prune_controller_backup_files(controller_key, newest_path=path)
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


@shed_entries_locked
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


@shed_entries_locked
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
        if dest_shed not in ENTRY_SHED_NUMBERS:
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


IMPORTANT_NOTIFICATION_EVENT_TYPES = {
    "crop_report_ready",
    "crop_report_emailed",
    "crop_report_failed",
    "backup_failed",
    "controller_backup_failed",
    "office_updated",
}


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
    with _event_log_lock:
        append_named_json_line("events.ndjson", payload)
        compact_json_line_log("events.ndjson", EVENT_LOG_MAX_BYTES, EVENT_LOG_KEEP_LINES)
        if payload["event_type"] in IMPORTANT_NOTIFICATION_EVENT_TYPES:
            append_named_json_line("notification_events.ndjson", payload)
            compact_json_line_log(
                "notification_events.ndjson",
                NOTIFICATION_LOG_MAX_BYTES,
                NOTIFICATION_LOG_KEEP_LINES,
            )


def get_recent_events(limit=200):
    rows = read_recent_json_lines("events.ndjson", limit=limit or 200)
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
    rows = read_recent_json_lines("notification_events.ndjson", limit=NOTIFICATION_LOG_KEEP_LINES)
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
        "climate_today": meta.get("climate_today") if isinstance(meta.get("climate_today"), dict) else None,
        "temp_low_c": meta.get("temp_low_c"),
        "temp_high_c": meta.get("temp_high_c"),
        "temp_amber_margin_c": meta.get("temp_amber_margin_c"),
        "rh_low_pct": meta.get("rh_low_pct"),
        "rh_high_pct": meta.get("rh_high_pct"),
        "rh_amber_margin_pct": meta.get("rh_amber_margin_pct"),
        "climate_limits_updated_ts": meta.get("climate_limits_updated_ts"),
        "water_lpm": meta.get("water_lpm"),
        "water_low_lpm": meta.get("water_low_lpm"),
        "water_amber_buffer_lpm": meta.get("water_amber_buffer_lpm"),
        "water_total_litres": meta.get("water_total_litres"),
        "feed_kg": meta.get("feed_kg"),
        "feed_kg_updated_ts": meta.get("feed_kg_updated_ts"),
        "feed_noise_kg": meta.get("feed_noise_kg"),
        "feed_low_kg": meta.get("feed_low_kg"),
        "feed_capacity_kg": meta.get("feed_capacity_kg"),
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
    climate = {}
    for key, field in [("temp", "temp_c"), ("rh", "rh_pct")]:
        try:
            climate[key] = float(meta.get(field))
        except Exception:
            pass
    if water_total_litres is None and feed_kg is None and not climate:
        return False

    shed_name = shed_name_from_number(shed_no)
    crop_id = get_active_crop_id_for_shed(shed_name)
    out_of_crop = crop_id in [None, ""]
    update_feed_movement_activity_from_meta(shed_no, meta)
    if out_of_crop:
        return False
    rows = read_all_json_lines("hourly.ndjson")

    def matches_crop(row):
        if row.get("shed") != shed_name:
            return False
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
            "crop_id": int(crop_id),
            "hour_epoch": int(hour_epoch),
            "out_of_crop": False,
            "source": "controller_sync",
        }
        rows.append(row)
        return row

    if climate:
        # Temperature and humidity low / high, kept per hour so each crop day's
        # high and low can be looked back on.
        row = hour_row((sensor_ts // 3600) * 3600)
        for key, value in climate.items():
            if row.get(key + "_min") is None or value < float(row.get(key + "_min")):
                row[key + "_min"] = round(value, 2)
            if row.get(key + "_max") is None or value > float(row.get(key + "_max")):
                row[key + "_max"] = round(value, 2)
        row["ts"] = int(time.time())
        row["source"] = "controller_sync"
        row["out_of_crop"] = False

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
        row["out_of_crop"] = False

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
            row["out_of_crop"] = False

    write_named_json_lines_atomic("hourly.ndjson", rows)
    return True


def save_controller_meta_for_shed(shed_no, meta):
    all_meta = load_controller_meta()
    all_meta[str(int(shed_no))] = clean_controller_meta(meta)
    save_controller_meta(all_meta)
    try:
        adopt_controller_climate_limits(shed_no, meta)
    except Exception:
        pass


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


def active_bird_count_for_shed_crop(shed_name, crop_id):
    if crop_id in [None, ""]:
        return None

    state = load_shed_entries_state()
    entries = ensure_shed_entry_bucket(state, shed_name)
    total = 0

    for key in entries:
        rec = clean_entry_record(entries.get(key, {}))
        try:
            rec_crop_id = int(rec.get("crop_id"))
        except Exception:
            continue

        if rec_crop_id != int(crop_id):
            continue
        if rec["crop_active"] != 1 or rec["bird_count"] <= 0:
            continue

        total += int(rec["bird_count"])

    return total if total > 0 else None


def active_placed_bird_count_for_shed_crop(shed_name, crop_id):
    if crop_id in [None, ""]:
        return None

    state = load_shed_entries_state()
    entries = ensure_shed_entry_bucket(state, shed_name)
    total = 0

    for key in entries:
        raw_rec = entries.get(key, {})
        rec = clean_entry_record(raw_rec)
        try:
            rec_crop_id = int(rec.get("crop_id"))
        except Exception:
            continue

        if rec_crop_id != int(crop_id):
            continue
        if rec["crop_active"] != 1 or rec["bird_count"] <= 0:
            continue

        placed_bird_count = int(rec.get("placed_bird_count") or rec["bird_count"])
        entry_mortality = mortality_total_for_entry(shed_name, crop_id, key)
        if entry_mortality > 0 and placed_bird_count <= rec["bird_count"]:
            placed_bird_count = rec["bird_count"] + entry_mortality
        total += placed_bird_count

    return total if total > 0 else None


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

    try:
        placed_bird_count = rec.get("placed_bird_count", rec.get("placed_count", None))
        if placed_bird_count not in [None, ""]:
            placed_bird_count = int(placed_bird_count)
        else:
            placed_bird_count = bird_count
    except Exception:
        placed_bird_count = bird_count

    payload = {
        "ts": int(time.time()),
        "shed": shed_name,
        "crop_id": crop_id,
        "crop_active": 1 if crop_active else 0,
        "placement_epoch": placement_epoch,
        "bird_count": bird_count,
        "placed_bird_count": placed_bird_count,
        "feed_kg": latest_feed_kg_for_shed(shed_name),
    }
    append_named_json_line("crop.ndjson", payload)


def mortality_occurred_ts(date_text, placement_epoch=None):
    # Turns a back-dated "YYYY-MM-DD" into the timestamp the loss is filed under.
    # Today (or no date) means now; earlier days are filed at midday.
    now_ts = int(time.time())
    date_text = str(date_text or "").strip()
    if not date_text:
        return now_ts, ""
    try:
        day = datetime.strptime(date_text, "%Y-%m-%d").date()
    except Exception:
        return None, "Invalid mortality date"
    today = datetime.fromtimestamp(now_ts).date()
    if day > today:
        return None, "Mortality date cannot be in the future"
    if day == today:
        return now_ts, ""
    if placement_epoch not in [None, ""]:
        try:
            if day < datetime.fromtimestamp(int(placement_epoch)).date():
                return None, "Mortality date is before the birds were placed"
        except Exception:
            pass
    return int(datetime(day.year, day.month, day.day, 12, 0, 0).timestamp()), ""


def log_mortality_event(shed_name, dest_shed, crop_id, bird_loss, note="", occurred_ts=None):
    now_ts = int(time.time())
    payload = {
        "ts": int(occurred_ts) if occurred_ts not in [None, ""] else now_ts,
        "recorded_ts": now_ts,
        "shed": shed_name,
        "dest_shed": int(dest_shed),
        "dest_shed_label": entry_shed_label(dest_shed),
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


def mortality_total_for_entry(shed_name, crop_id, dest_shed):
    if crop_id in [None, ""]:
        return 0

    rows = get_mortality_history_for_shed(shed_name, crop_id=crop_id)
    total = 0
    i = 0
    while i < len(rows):
        try:
            if int(rows[i].get("dest_shed")) == int(dest_shed):
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
    while i < len(ENTRY_SHED_NUMBERS):
        dest_shed = ENTRY_SHED_NUMBERS[i]
        rec = clean_entry_record(entries.get(str(dest_shed), {}))
        if rec["crop_active"] == 1 and rec["bird_count"] > 0:
            target_rows.append({
                "dest_shed": dest_shed,
                "dest_shed_label": entry_shed_label(dest_shed),
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
        history_rows[i]["dest_shed_label"] = entry_shed_label(history_rows[i].get("dest_shed"))
        try:
            history_rows[i]["ts_label"] = datetime.fromtimestamp(int(history_rows[i].get("ts"))).strftime("%d %b %Y %H:%M")
        except Exception:
            history_rows[i]["ts_label"] = "--"
        try:
            recorded_ts = int(history_rows[i].get("recorded_ts"))
            if datetime.fromtimestamp(recorded_ts).date() != datetime.fromtimestamp(int(history_rows[i].get("ts"))).date():
                history_rows[i]["ts_label"] = "%s (entered %s)" % (
                    datetime.fromtimestamp(int(history_rows[i].get("ts"))).strftime("%d %b %Y"),
                    datetime.fromtimestamp(recorded_ts).strftime("%d %b %H:%M"),
                )
        except Exception:
            pass
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


@shed_entries_locked
def apply_mortality_to_shed(shed_no, dest_shed, bird_loss, note="", updated_by="dashboard", date_text=""):
    if shed_no not in SHED_NUMBERS or not valid_entry_shed(dest_shed):
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
    occurred_ts, date_error = mortality_occurred_ts(date_text, rec.get("placement_epoch"))
    if date_error:
        return False, date_error

    crop_id = rec.get("crop_id")
    existing_mortality = mortality_total_for_entry(shed_name, crop_id, dest_shed)
    try:
        placed_bird_count = int(rec.get("placed_bird_count", 0) or 0)
    except Exception:
        placed_bird_count = 0
    if placed_bird_count < rec["bird_count"] + existing_mortality:
        placed_bird_count = rec["bird_count"] + existing_mortality
    rec["placed_bird_count"] = placed_bird_count
    rec["bird_count"] = max(0, rec["bird_count"] - bird_loss)
    rec["updated_ts"] = int(time.time())
    rec["updated_by"] = str(updated_by or "dashboard")
    if rec["bird_count"] <= 0:
        log_crop_event(shed_name, rec, False)
        if str(dest_shed) in entries:
            del entries[str(dest_shed)]
    else:
        entries[str(dest_shed)] = rec

    log_mortality_event(shed_name, dest_shed, crop_id, bird_loss, note=note, occurred_ts=occurred_ts)
    log_event("office", "mortality_recorded", "Mortality recorded", shed_no=shed_no, detail="%s Loss %d" % (entry_shed_label(dest_shed), bird_loss))
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
    "bin_fill": "Bin Fill-Up",
    "crop_carryover_credit": "Crop End Carryover (Legacy)",
    "manual_add": "Manual Add",
    "manual_remove": "Manual Remove",
    "shed_allocation": "Manual Shed Feed Entry",
    "shed_return": "Shed Feed Return (Legacy)",
}
EDITABLE_FEED_STOCK_KINDS = ["bin_fill", "shed_allocation"]


def feed_stock_record_id(rec, index):
    if isinstance(rec, dict):
        tx_id = str(rec.get("tx_id") or "").strip()
        if tx_id:
            return tx_id
    return "legacy-%d" % int(index)


def new_feed_stock_tx_id():
    return "feed-%s" % uuid.uuid4().hex


def feed_stock_display_kind(kind):
    kind = str(kind or "manual_add")
    if kind in ["manual_add", "bin_fill"]:
        return "bin_fill"
    if kind == "shed_allocation":
        return "shed_allocation"
    return kind


def feed_stock_delta_for_kind(kind, kg):
    try:
        kg = abs(round(float(kg), 3))
    except Exception:
        return None
    if kg <= 0:
        return None
    display_kind = feed_stock_display_kind(kind)
    if display_kind == "shed_allocation":
        return -kg
    if display_kind == "bin_fill":
        return kg
    return None


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
        tx_id = feed_stock_record_id(rec, i)
        out.append({
            "tx_id": tx_id,
            "ts": ts,
            "kind": str(rec.get("kind") or "manual_add"),
            "display_kind": feed_stock_display_kind(rec.get("kind")),
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
        "tx_id": new_feed_stock_tx_id(),
        "ts": tx_ts,
        "kind": str(kind or "manual_add"),
        "delta_kg": delta_kg,
        "shed_no": None if shed_no in [None, ""] else int(shed_no),
        "crop_id": None if crop_id in [None, ""] else int(crop_id),
        "source_crop_id": None if source_crop_id in [None, ""] else int(source_crop_id),
        "note": str(note or "").strip(),
    })
    return True


def rewrite_feed_stock_transaction(tx_id, new_rec=None):
    tx_id = str(tx_id or "").strip()
    if not tx_id:
        return False
    rows = read_all_json_lines("feed_stock.ndjson")
    changed = False
    out = []
    i = 0
    while i < len(rows):
        rec = rows[i]
        if isinstance(rec, dict):
            rec_id = feed_stock_record_id(rec, i)
            if rec.get("tx_id") in [None, ""]:
                rec = dict(rec)
                rec["tx_id"] = rec_id
            if rec_id == tx_id:
                changed = True
                if isinstance(new_rec, dict):
                    out.append(new_rec)
                i += 1
                continue
            out.append(rec)
        i += 1
    if changed:
        write_named_json_lines_atomic("feed_stock.ndjson", out)
    return changed


def feed_movement_activity_path():
    ensure_data_dir()
    return os.path.join(DATA_DIR, "feed_movement_activity.json")


def legacy_pre_crop_feed_activity_path():
    ensure_data_dir()
    return os.path.join(DATA_DIR, "pre_crop_feed_activity.json")


def load_feed_movement_activity():
    data = read_json_file(feed_movement_activity_path(), None)
    if data is None:
        data = read_json_file(legacy_pre_crop_feed_activity_path(), {})
    return data if isinstance(data, dict) else {}


def save_feed_movement_activity(data):
    write_json_file_atomic(feed_movement_activity_path(), data if isinstance(data, dict) else {})


def clean_feed_movement_activity_rec(rec):
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

    out_of_crop_feed_out_kg = float_or_none("out_of_crop_feed_out_kg")
    if out_of_crop_feed_out_kg is None:
        out_of_crop_feed_out_kg = float_or_none("activity_kg")
    if out_of_crop_feed_out_kg is None:
        out_of_crop_feed_out_kg = 0.0
    out_of_crop_feed_in_kg = float_or_none("out_of_crop_feed_in_kg")
    if out_of_crop_feed_in_kg is None:
        out_of_crop_feed_in_kg = 0.0
    in_crop_feed_out_kg = float_or_none("in_crop_feed_out_kg")
    if in_crop_feed_out_kg is None:
        in_crop_feed_out_kg = 0.0
    in_crop_feed_in_kg = float_or_none("in_crop_feed_in_kg")
    if in_crop_feed_in_kg is None:
        in_crop_feed_in_kg = 0.0
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
        if event_kg < FEED_MOVEMENT_APPLY_MIN_KG:
            continue
        try:
            event_shed_no = int(event.get("shed_no")) if event.get("shed_no") not in [None, ""] else None
        except Exception:
            event_shed_no = None
        try:
            event_crop_id = int(event.get("crop_id")) if event.get("crop_id") not in [None, ""] else None
        except Exception:
            event_crop_id = None
        try:
            feed_kg_after = round(float(event.get("feed_kg_after")), 3) if event.get("feed_kg_after") not in [None, ""] else None
        except Exception:
            feed_kg_after = None
        clean_events.append({
            "id": str(event.get("id") or uuid.uuid4().hex),
            "ts": event_ts,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "shed_no": event_shed_no,
            "movement": str(event.get("movement") or "").strip(),
            "kg": event_kg,
            "crop_state": str(event.get("crop_state") or "").strip(),
            "crop_id": event_crop_id,
            "feed_kg_after": feed_kg_after,
        })
    clean_events.sort(key=lambda row: int(row.get("ts") or 0))
    return {
        "baseline_kg": float_or_none("baseline_kg"),
        "low_kg": float_or_none("low_kg"),
        "last_feed_kg": float_or_none("last_feed_kg"),
        "last_sample_ts": int_or_none("last_sample_ts"),
        "start_ts": int_or_none("start_ts"),
        "updated_ts": int_or_none("updated_ts"),
        "out_of_crop_feed_out_kg": round(max(0.0, out_of_crop_feed_out_kg), 3),
        "out_of_crop_feed_in_kg": round(max(0.0, out_of_crop_feed_in_kg), 3),
        "in_crop_feed_out_kg": round(max(0.0, in_crop_feed_out_kg), 3),
        "in_crop_feed_in_kg": round(max(0.0, in_crop_feed_in_kg), 3),
        "last_crop_state": str(rec.get("last_crop_state") or "").strip(),
        "last_crop_id": int_or_none("last_crop_id"),
        "last_movement": str(rec.get("last_movement") or "").strip(),
        "events": clean_events[-500:],
        "last_applied_ts": int_or_none("last_applied_ts"),
        "last_applied_crop_id": int_or_none("last_applied_crop_id"),
        "last_applied_kg": float_or_none("last_applied_kg"),
    }


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

    if event["kg"] < FEED_MOVEMENT_APPLY_MIN_KG:
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
            and str(prev.get("shed_no") or "") == str(event.get("shed_no") or "")
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

    event["id"] = str(event.get("id") or uuid.uuid4().hex)
    events.append(event)
    return events[-500:]


def update_feed_movement_activity_from_meta(shed_no, meta):
    if not isinstance(meta, dict):
        return False
    shed_name = shed_name_from_number(shed_no)
    crop_id = get_active_crop_id_for_shed(shed_name)
    in_crop = crop_id not in [None, ""]
    try:
        feed_kg = float(meta.get("feed_kg"))
    except Exception:
        return False
    try:
        sample_ts = int(meta.get("feed_kg_updated_ts"))
    except Exception:
        try:
            sample_ts = int(meta.get("last_sensor_ts"))
        except Exception:
            sample_ts = int(time.time())
    try:
        noise_kg = max(0.0, float(meta.get("feed_noise_kg") or 0.0))
    except Exception:
        noise_kg = 0.0
    min_drop_kg = max(FEED_RECORDING_MIN_DROP_KG, noise_kg * FEED_RECORDING_NOISE_FACTOR)

    data = load_feed_movement_activity()
    key = str(int(shed_no))
    rec = clean_feed_movement_activity_rec(data.get(key, {}))
    last_sample_ts = rec.get("last_sample_ts")
    if last_sample_ts is not None and sample_ts <= last_sample_ts:
        return False

    if rec.get("baseline_kg") is None:
        rec["baseline_kg"] = feed_kg
    if rec.get("low_kg") is None:
        rec["low_kg"] = feed_kg
    if rec.get("start_ts") is None:
        rec["start_ts"] = sample_ts

    baseline_kg = float(rec.get("baseline_kg") or feed_kg)
    low_kg = float(rec.get("low_kg") or feed_kg)
    state_prefix = "in_crop" if in_crop else "out_of_crop"
    feed_out_key = "%s_feed_out_kg" % state_prefix
    feed_in_key = "%s_feed_in_kg" % state_prefix
    feed_out_kg = float(rec.get(feed_out_key) or 0.0)
    feed_in_kg = float(rec.get(feed_in_key) or 0.0)
    last_movement = rec.get("last_movement") or ""
    movement_kg = 0.0
    movement_kind = ""

    if feed_kg >= baseline_kg + FEED_RECORDING_REFILL_RISE_KG:
        fill_kg = max(0.0, feed_kg - low_kg)
        if fill_kg >= min_drop_kg:
            feed_in_kg += fill_kg
            last_movement = "bin_fill"
            movement_kind = "bin_fill"
            movement_kg = fill_kg
        baseline_kg = feed_kg
        low_kg = feed_kg
    elif feed_kg <= low_kg - min_drop_kg:
        movement_kg = low_kg - feed_kg
        feed_out_kg += movement_kg
        last_movement = "feed_out"
        movement_kind = "feed_out"
        low_kg = feed_kg
    elif feed_kg > low_kg + min_drop_kg:
        low_kg = feed_kg

    if movement_kind and movement_kg >= min_drop_kg:
        events = rec.get("events", [])
        if not isinstance(events, list):
            events = []
        events = append_feed_movement_event(events, {
            "id": uuid.uuid4().hex,
            "ts": int(sample_ts),
            "start_ts": int(sample_ts),
            "end_ts": int(sample_ts),
            "shed_no": int(shed_no),
            "movement": movement_kind,
            "kg": round(float(movement_kg), 3),
            "crop_state": "in_crop" if in_crop else "out_of_crop",
            "crop_id": None if crop_id in [None, ""] else int(crop_id),
            "feed_kg_after": round(feed_kg, 3),
        })
        rec["events"] = events[-500:]

    rec[feed_out_key] = round(max(0.0, feed_out_kg), 3)
    rec[feed_in_key] = round(max(0.0, feed_in_kg), 3)
    rec.update({
        "baseline_kg": round(baseline_kg, 3),
        "low_kg": round(low_kg, 3),
        "last_feed_kg": round(feed_kg, 3),
        "last_sample_ts": int(sample_ts),
        "updated_ts": int(time.time()),
        "last_crop_state": "in_crop" if in_crop else "out_of_crop",
        "last_crop_id": None if crop_id in [None, ""] else int(crop_id),
        "last_movement": last_movement,
    })
    data[key] = rec
    save_feed_movement_activity(data)
    return True


def clear_feed_movement_activity(shed_no, crop_id=None, applied_kg=None, out_of_crop_only=False):
    data = load_feed_movement_activity()
    key = str(int(shed_no))
    rec = clean_feed_movement_activity_rec(data.get(key, {}))
    current_feed_kg = rec.get("last_feed_kg")
    if out_of_crop_only:
        rec["out_of_crop_feed_out_kg"] = 0.0
        rec["out_of_crop_feed_in_kg"] = 0.0
    else:
        rec["out_of_crop_feed_out_kg"] = 0.0
        rec["out_of_crop_feed_in_kg"] = 0.0
        rec["in_crop_feed_out_kg"] = 0.0
        rec["in_crop_feed_in_kg"] = 0.0
    rec.update({
        "baseline_kg": current_feed_kg,
        "low_kg": current_feed_kg,
        "start_ts": int(time.time()),
        "updated_ts": int(time.time()),
        "last_applied_ts": int(time.time()),
        "last_applied_crop_id": None if crop_id in [None, ""] else int(crop_id),
        "last_applied_kg": None if applied_kg in [None, ""] else round(float(applied_kg), 3),
    })
    data[key] = rec
    save_feed_movement_activity(data)


def feed_movement_activity_rows():
    data = load_feed_movement_activity()
    rows = []
    i = 0
    while i < len(SHED_NUMBERS):
        shed_no = SHED_NUMBERS[i]
        key = str(int(shed_no))
        rec = clean_feed_movement_activity_rec(data.get(key, {}))
        shed_name = shed_name_from_number(shed_no)
        crop = active_crop_record_for_shed(shed_name)
        try:
            crop_id = int(crop.get("crop_id"))
        except Exception:
            crop_id = None
        out_of_crop_feed_out_kg = float(rec.get("out_of_crop_feed_out_kg") or 0.0)
        out_of_crop_feed_in_kg = float(rec.get("out_of_crop_feed_in_kg") or 0.0)
        in_crop_feed_out_kg = float(rec.get("in_crop_feed_out_kg") or 0.0)
        in_crop_feed_in_kg = float(rec.get("in_crop_feed_in_kg") or 0.0)
        movement_total = out_of_crop_feed_out_kg + out_of_crop_feed_in_kg + in_crop_feed_out_kg + in_crop_feed_in_kg
        last_feed_kg = rec.get("last_feed_kg")
        updated_ts = rec.get("last_sample_ts") or rec.get("updated_ts")
        is_in_crop = crop_id not in [None, ""]
        rows.append({
            "shed_no": shed_no,
            "shed_name": shed_name,
            "crop_state_label": "In Crop" if is_in_crop else "Out Of Crop",
            "crop_state_class": "in-crop" if is_in_crop else "out-crop",
            "out_of_crop_feed_out_kg": round(out_of_crop_feed_out_kg, 3),
            "out_of_crop_feed_out_label": fmt_value(out_of_crop_feed_out_kg if out_of_crop_feed_out_kg >= FEED_MOVEMENT_APPLY_MIN_KG else None, "f1"),
            "in_crop_feed_out_label": fmt_value(in_crop_feed_out_kg if in_crop_feed_out_kg >= FEED_MOVEMENT_APPLY_MIN_KG else None, "f1"),
            "out_of_crop_feed_in_label": fmt_value(out_of_crop_feed_in_kg if out_of_crop_feed_in_kg >= FEED_MOVEMENT_APPLY_MIN_KG else None, "f1"),
            "in_crop_feed_in_label": fmt_value(in_crop_feed_in_kg if in_crop_feed_in_kg >= FEED_MOVEMENT_APPLY_MIN_KG else None, "f1"),
            "last_feed_kg_label": fmt_value(last_feed_kg, "f0"),
            "updated_label": format_ts_label(updated_ts),
            "crop_id": crop_id,
            "crop_code": fmt_crop_code(crop_id, crop.get("placement_epoch")) if crop_id not in [None, ""] else "--",
            "can_apply": crop_id not in [None, ""] and out_of_crop_feed_out_kg >= FEED_MOVEMENT_APPLY_MIN_KG,
            "can_clear": movement_total >= FEED_MOVEMENT_APPLY_MIN_KG,
            "status": (
                "Out-of-crop feed ready to add"
                if crop_id not in [None, ""] and out_of_crop_feed_out_kg >= FEED_MOVEMENT_APPLY_MIN_KG
                else ("Tracking in crop" if is_in_crop else "Tracking out of crop")
            ),
        })
        i += 1
    return rows


def feed_movement_event_rows(shed_no=None, limit=200):
    data = load_feed_movement_activity()
    target_shed_no = None
    try:
        target_shed_no = int(shed_no) if shed_no not in [None, ""] else None
    except Exception:
        target_shed_no = None
    events = []
    for key in data:
        rec = clean_feed_movement_activity_rec(data.get(key, {}))
        i = 0
        while i < len(rec.get("events", [])):
            event = rec["events"][i]
            i += 1
            try:
                event_shed_no = int(event.get("shed_no") or key)
            except Exception:
                continue
            if target_shed_no is not None and event_shed_no != target_shed_no:
                continue
            movement = str(event.get("movement") or "")
            crop_state = str(event.get("crop_state") or "")
            crop_id = event.get("crop_id")
            start_ts = event.get("start_ts") or event.get("ts")
            end_ts = event.get("end_ts") or event.get("ts")
            ts_label = format_ts_label(start_ts)
            try:
                if int(end_ts or 0) > int(start_ts or 0):
                    ts_label = "%s - %s" % (format_ts_label(start_ts), format_ts_label(end_ts))
            except Exception:
                pass
            events.append({
                "id": event.get("id"),
                "ts": event.get("ts"),
                "ts_label": ts_label,
                "shed_no": event_shed_no,
                "shed_name": shed_name_from_number(event_shed_no),
                "movement": movement,
                "movement_label": "Feed Out" if movement == "feed_out" else ("Bin Fill-Up" if movement == "bin_fill" else "--"),
                "kg": event.get("kg"),
                "kg_label": fmt_value(event.get("kg"), "f1"),
                "crop_state": crop_state,
                "crop_state_label": "In Crop" if crop_state == "in_crop" else "Out Of Crop",
                "crop_state_class": "in-crop" if crop_state == "in_crop" else "out-crop",
                "crop_label": fmt_crop_code(crop_id) if crop_id not in [None, ""] else "--",
                "feed_kg_after_label": fmt_value(event.get("feed_kg_after"), "f0"),
            })
    events.sort(key=lambda row: int(row.get("ts") or 0), reverse=True)
    try:
        limit = max(0, int(limit))
    except Exception:
        limit = 200
    return events[:limit] if limit else events


def feed_movement_activity_row_for_shed(shed_no):
    try:
        shed_no = int(shed_no)
    except Exception:
        return {}
    rows = feed_movement_activity_rows()
    i = 0
    while i < len(rows):
        if rows[i].get("shed_no") == shed_no:
            return rows[i]
        i += 1
    return {}


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
    display_rows = list(reversed(tx_rows))
    i = 0
    while i < len(display_rows):
        rec = display_rows[i]
        display_kind = feed_stock_display_kind(rec.get("kind"))
        rec["display_kind"] = display_kind
        rec["kind_label"] = FEED_STOCK_KIND_LABELS.get(rec.get("kind"), str(rec.get("kind") or "").replace("_", " ").title())
        if display_kind == "bin_fill":
            rec["kind_label"] = "Bin Fill-Up"
        elif display_kind == "shed_allocation":
            rec["kind_label"] = "Shed Feed Entry"
        rec["delta_kg_label"] = fmt_value(rec.get("delta_kg"), "f1")
        rec["feed_kg_label"] = fmt_value(abs(float(rec.get("delta_kg") or 0.0)), "f1")
        rec["feed_kg_value"] = "%.1f" % abs(float(rec.get("delta_kg") or 0.0))
        rec["form_id"] = "feed-edit-%s" % re.sub(r"[^A-Za-z0-9_-]+", "-", str(rec.get("tx_id") or ""))
        rec["can_edit"] = display_kind in EDITABLE_FEED_STOCK_KINDS
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
        "feed_movement_rows": feed_movement_activity_rows(),
        "feed_movement_event_rows": feed_movement_event_rows(),
        "preselected_shed_no": preselected_shed_no,
        "shed_options": [{"shed_no": shed_no, "shed_name": shed_name_from_number(shed_no)} for shed_no in SHED_NUMBERS],
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

    updated_by = str(rec.get("updated_by", "dashboard") or "dashboard")
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

    climate_limits = None
    office_ts = office_climate_limits_ts(shed_no)
    if office_ts is not None:
        limits = office_environment_limits_map().get(str(shed_no), {})
        climate_limits = {key: limits.get(key) for key in CLIMATE_LIMIT_KEYS}
        climate_limits["updated_ts"] = office_ts

    pen_bucket = state.get(shed_name, {})
    return {
        "shed_no": shed_no,
        "shed": shed_name,
        "entries": payload_entries,
        "pen_order": {"order": pen_order_for_shed(state, shed_name), "updated_ts": pen_bucket.get("pen_order_ts") or None, "now": int(time.time())},
        "climate_limits": climate_limits,
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


@shed_entries_locked
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
            if dest_shed not in ENTRY_SHED_NUMBERS:
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
                    detail="%s older than dashboard end" % entry_shed_label(dest_shed),
                )
                continue
            if rec["bird_count"] > 0 and rec["crop_active"] == 1 and rec["crop_id"] is None:
                rec["crop_id"] = crop_id_for_new_start(state)
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
                    detail="%s retained in %s" % (entry_shed_label(key), shed_name),
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

        hour_row = {
            "epoch": hour_epoch,
            "label": label,
            "water": water_val,
            "feed": feed_val,
            "crop_id": p.get("crop_id"),
            "out_of_crop": bool(p.get("out_of_crop", False)),
        }
        for key in ["temp", "rh"]:
            try:
                hour_row[key + "_min"] = float(p[key + "_min"]) if p.get(key + "_min") is not None else None
                hour_row[key + "_max"] = float(p[key + "_max"]) if p.get(key + "_max") is not None else None
            except Exception:
                hour_row[key + "_min"] = hour_row[key + "_max"] = None
        rows.append(hour_row)
        i += 1

    rows.sort(key=lambda x: x["epoch"])
    if include_manual_feed and crop_id not in [None, ""]:
        manual_hour_map = feed_stock_feed_adjustment_hour_map_for_shed_crop(shed_name, crop_id)
        if manual_hour_map:
            # A manual feed entry dated before the crop began (e.g. a missing or broken
            # timestamp) is counted at the crop's start, so tables begin on placement day
            # and the crop's feed total is unchanged.
            crop_start_hour = None
            placement_epoch = crop_start_epoch_for_state(load_shed_entries_state(), crop_id)
            if placement_epoch not in [None, ""]:
                crop_start_hour = (int(placement_epoch) // 3600) * 3600
            elif rows:
                crop_start_hour = int(rows[0]["epoch"])
            if crop_start_hour is not None:
                clamped = {}
                for hour_epoch, delta in manual_hour_map.items():
                    key = max(int(hour_epoch), crop_start_hour)
                    clamped[key] = round(float(clamped.get(key) or 0.0) + float(delta or 0.0), 3)
                manual_hour_map = clamped
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
    # Temperature / humidity highs and lows run midnight to midnight, unlike feed and
    # water which use the 6am-6am farm day. Keyed by calendar date.
    climate_by_date = {}
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
        totals = climate_by_date.setdefault(dt_obj.strftime("%Y-%m-%d"), {})
        for key in ["temp", "rh"]:
            if row.get(key + "_min") is not None:
                totals[key + "_min"] = min(totals.get(key + "_min", row[key + "_min"]), row[key + "_min"])
            if row.get(key + "_max") is not None:
                totals[key + "_max"] = max(totals.get(key + "_max", row[key + "_max"]), row[key + "_max"])

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

            totals = day_totals[day_key]
            climate = climate_by_date.get(day_key, {})
            day_row = {
                "key": day_key,
                "label": label,
                "water": totals["water"],
                "feed": totals["feed"],
            }
            for key in ["temp", "rh"]:
                day_row[key + "_min"] = climate.get(key + "_min")
                day_row[key + "_max"] = climate.get(key + "_max")
            rows.append(day_row)
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
    current_active_birds = active_bird_count_for_shed_crop(shed_name, crop_id)
    current_placed_birds = active_placed_bird_count_for_shed_crop(shed_name, crop_id)
    if current_active_birds is not None:
        birds_remaining_end = current_active_birds
        birds_placed = current_placed_birds or (current_active_birds + int(mortality_total or 0))
    else:
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
        rows.append(["Day", "Water L", "Feed KG", "Running Water L", "Running Feed KG", "Temp High C", "Temp Low C", "RH High %", "RH Low %"])
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
                round(daily["temp_max"], 1) if daily.get("temp_max") is not None else None,
                round(daily["temp_min"], 1) if daily.get("temp_min") is not None else None,
                round(daily["rh_max"]) if daily.get("rh_max") is not None else None,
                round(daily["rh_min"]) if daily.get("rh_min") is not None else None,
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
            if dest_shed not in ENTRY_SHED_NUMBERS:
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
            if dest_shed not in ENTRY_SHED_NUMBERS:
                continue
            if ended_ts > 0:
                clean_ended_entries[str(dest_shed)] = ended_ts

        pen_order = shed_rec.get("pen_order", [])
        pen_order = [str(k) for k in pen_order] if isinstance(pen_order, list) else []
        try:
            pen_order_ts = int(shed_rec.get("pen_order_ts") or 0)
        except Exception:
            pen_order_ts = 0
        slot_of = shed_rec.get("pen_slot_of", {})
        slot_of = {str(k): int(v) for k, v in slot_of.items() if str(v).lstrip("-").isdigit()} if isinstance(slot_of, dict) else {}
        try:
            pen_slots = int(shed_rec.get("pen_slots") or 0)
        except Exception:
            pen_slots = 0
        result[shed_name] = {"entries": clean_entries, "ended_entries": clean_ended_entries,
                             "pen_order": pen_order, "pen_order_ts": pen_order_ts,
                             "pen_slots": pen_slots, "pen_slot_of": slot_of}

    return result


MAX_PENS_PER_SHED = 4


def shed_no_for_name(shed_name):
    # "Shed 6 & 6B" -> 6; works for every shed in SHED_NUMBERS.
    for no in SHED_NUMBERS:
        if shed_name_from_number(no) == shed_name:
            return no
    return shed_number_from_name(shed_name)


def pen_order_for_shed(state, shed_name):
    """Front-to-rear pen order (same as the shed controller's): pens with a known place
    first, then any others in shed-number order."""
    bucket = state.get(shed_name, {}) if isinstance(state.get(shed_name), dict) else {}
    entries = bucket.get("entries", {}) or {}
    known = [str(k) for k in (bucket.get("pen_order") or []) if str(k) in entries]
    rest = sorted([str(k) for k in entries if str(k) not in known], key=lambda k: int(k) if k.isdigit() else 0)
    ordered = known + rest
    # The shed's own birds always sit at the rear; the pens nearest the door move out first.
    home = shed_no_for_name(shed_name)
    own = [k for k in ordered if entry_home_shed_no(k) == home]
    return [k for k in ordered if k not in own] + own


def plan_boxes(state, shed_name):
    """The shed divided into pens, from the door (box 0) to the rear. The rear box(es)
    are kept for the shed's own birds. Returns (boxes, own_boxes): each box holds a pen's
    shed key or None when empty."""
    bucket = state.get(shed_name, {}) if isinstance(state.get(shed_name), dict) else {}
    entries = bucket.get("entries", {}) or {}
    home = shed_no_for_name(shed_name)
    active = [k for k in pen_order_for_shed(state, shed_name)
              if clean_entry_record(entries.get(k, {}))["crop_active"] == 1 and clean_entry_record(entries.get(k, {}))["bird_count"] > 0]
    visitors = [k for k in active if entry_home_shed_no(k) != home]
    own = [k for k in active if entry_home_shed_no(k) == home]
    # One rear box is kept for the shed's own birds, unless the visiting pens already
    # fill the shed.
    own_boxes = len(own) if own else (1 if len(visitors) < MAX_PENS_PER_SHED else 0)
    try:
        wanted = min(int(bucket.get("pen_slots") or 0), MAX_PENS_PER_SHED)
    except Exception:
        wanted = 0
    n = max(wanted, len(visitors) + own_boxes, 1)
    boxes = [None] * n
    for i, k in enumerate(own):
        boxes[n - own_boxes + i] = k
    slot_of = bucket.get("pen_slot_of") if isinstance(bucket.get("pen_slot_of"), dict) else {}
    last_visitor_box = n - own_boxes
    placed = set()
    for k in visitors:
        idx = slot_of.get(k)
        if isinstance(idx, int) and 0 <= idx < last_visitor_box and boxes[idx] is None:
            boxes[idx] = k
            placed.add(k)
    for k in visitors:
        if k in placed:
            continue
        for i in range(last_visitor_box):
            if boxes[i] is None:
                boxes[i] = k
                break
    return boxes, own_boxes


def save_plan_boxes(state, shed_name, boxes, own_boxes):
    """Store the boxes and the front-to-rear order the shed controller uses."""
    bucket = state.setdefault(shed_name, {})
    visitors = [(i, k) for i, k in enumerate(boxes[:len(boxes) - own_boxes]) if k]
    slot_of = {k: i for i, k in visitors}
    order = [k for k in boxes if k]
    if order != bucket.get("pen_order") or slot_of != bucket.get("pen_slot_of"):
        bucket["pen_order_ts"] = int(time.time())
    bucket["pen_slot_of"] = slot_of
    bucket["pen_order"] = order


def set_pen_box(state, shed_name, dest_shed, box):
    """Put a pen in a chosen box (0 = by the door). The shed's own birds go to the rear."""
    boxes, own_boxes = plan_boxes(state, shed_name)
    key = str(dest_shed)
    if entry_home_shed_no(dest_shed) != shed_no_for_name(shed_name) and key in boxes:
        boxes[boxes.index(key)] = None
        last_visitor_box = len(boxes) - own_boxes
        if 0 <= box < last_visitor_box and boxes[box] is None:
            boxes[box] = key
        else:
            free = [i for i in range(last_visitor_box) if boxes[i] is None]
            boxes[free[0] if free else 0] = key
    save_plan_boxes(state, shed_name, boxes, own_boxes)


def set_pen_count(state, shed_name, count):
    boxes, own_boxes = plan_boxes(state, shed_name)
    used = len([k for k in boxes if k]) + (own_boxes - len([k for k in boxes[len(boxes) - own_boxes:] if k]))
    bucket = state.setdefault(shed_name, {})
    bucket["pen_slots"] = min(max(int(count), used, 1), MAX_PENS_PER_SHED)
    boxes, own_boxes = plan_boxes(state, shed_name)
    save_plan_boxes(state, shed_name, boxes, own_boxes)
    return bucket["pen_slots"]


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
            parts.append("%s: %s" % (entry_shed_label(shed_no), fmt_value(bird_count, "i")))
        i += 1

    if not parts:
        return ""

    return " - ".join(parts)


def build_detail_entry_rows(current_shed_no, entries):
    rows = []
    shed_name = shed_name_from_number(current_shed_no)
    i = 0
    while i < len(ENTRY_SHED_NUMBERS):
        dest_shed = ENTRY_SHED_NUMBERS[i]
        raw_rec = entries.get(str(dest_shed), {})
        rec = clean_entry_record(raw_rec)

        try:
            bird_count = int(rec.get("bird_count", 0) or 0)
        except Exception:
            bird_count = 0

        try:
            placed_bird_count = int(rec.get("placed_bird_count", 0) or 0)
        except Exception:
            placed_bird_count = bird_count

        try:
            crop_active = 1 if int(rec.get("crop_active", 0) or 0) == 1 else 0
        except Exception:
            crop_active = 0

        entry_mortality = 0
        if crop_active == 1 and rec.get("crop_id") not in [None, ""]:
            entry_mortality = mortality_total_for_entry(shed_name, rec.get("crop_id"), dest_shed)
            if entry_mortality > 0 and placed_bird_count <= bird_count:
                placed_bird_count = bird_count + entry_mortality

        placement_epoch = rec.get("placement_epoch")
        placement_str = "--"
        if placement_epoch is not None:
            try:
                placement_str = datetime.fromtimestamp(int(placement_epoch)).strftime("%d %b %Y %H:%M")
            except Exception:
                placement_str = "--"

        can_move = (entry_home_shed_no(dest_shed) != current_shed_no) and crop_active == 1 and bird_count > 0
        placement_input_epoch = placement_epoch if (crop_active == 1 and bird_count > 0) else None
        rows.append({
            "dest_shed": dest_shed,
            "dest_shed_label": entry_shed_label(dest_shed),
            "bird_count": bird_count,
            "placed_bird_count": placed_bird_count,
            "entry_mortality": entry_mortality,
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
        if current_crop_id not in [None, ""]:
            shed_mortality = mortality_total_for_shed_crop(shed_name, current_crop_id)
            total_mortality += shed_mortality
            shed_placed = active_placed_bird_count_for_shed_crop(shed_name, current_crop_id)
            if shed_placed is not None:
                total_birds_placed += shed_placed
            else:
                total_birds_placed += birds_remaining + shed_mortality
        else:
            total_birds_placed += birds_remaining

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
        shed_display = shed_display_name_from_number(shed_no)
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
        live_display_active = is_online and bool(live)
        crop_operational_active = is_online and has_active_entry

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
        birds_placed = active_placed_bird_count_for_shed_crop(shed, active_crop_id) if active_crop_id is not None else None
        if birds_placed is None:
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
        if not live_display_active:
            temp_c = None
            rh_pct = None
            feed_kg = None
            water_lpm = None
            updated_ts = None

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
            force_red=not crop_operational_active,
        )
        lighting_visible = True
        lighting_on = bool(controller_meta.get("lighting_on", False))

        # Today's high / low from the controller, only if it is for today's date.
        climate_today = controller_meta.get("climate_today") if isinstance(controller_meta.get("climate_today"), dict) else {}
        if climate_today.get("date") != datetime.now().strftime("%Y-%m-%d"):
            climate_today = {}

        rows.append({
            "shed": shed_display,
            "shed_name": shed,
            "shed_no": shed_no,
            "temp_hi": fmt_value(climate_today.get("temp_max"), "f1"),
            "temp_lo": fmt_value(climate_today.get("temp_min"), "f1"),
            "rh_hi": fmt_value(climate_today.get("rh_max"), "f0"),
            "rh_lo": fmt_value(climate_today.get("rh_min"), "f0"),
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
        meta = controller_meta_map.get(str(int(shed_no)), {})
        if not (controller_online(meta) and bool(live)):
            live = {}
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
            color: #0d2b4a;
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
            color: #0d2b4a;
            text-decoration: none;
            font-size: 13px;
            padding: 7px 10px;
            border: 1px solid #d5dde6;
            border-radius: 10px;
            background: #f5f8fb;
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
            border-color: #2f9e3a;
            color: #1e6b16;
            box-shadow: 0 0 8px rgba(47,158,58,0.36),
                0 0 16px rgba(47,158,58,0.17);
        }
        .settings-link.notify-blocked {
            border-color: #d64545;
            color: #b42318;
            box-shadow: 0 0 8px rgba(214,69,69,0.36),
                0 0 16px rgba(214,69,69,0.17);
        }
        .settings-link.notify-off {
            border-color: #f08a12;
            color: #9a4b00;
        }
        .notify-status {
            margin-bottom: 12px;
            text-align: center;
            font-size: 13px;
            color: #0d2b4a;
            min-height: 18px;
        }
        .notify-status.state-on {
            color: #1e6b16;
            text-shadow: 0 0 8px rgba(47,158,58,0.25);
        }
        .notify-status.state-blocked {
            color: #b42318;
            text-shadow: 0 0 8px rgba(214,69,69,0.25);
        }
        .notify-status.state-off {
            color: #9a4b00;
        }
        h1 {
            margin: 0;
            font-size: 28px;
            color: #0d2b4a;
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
        .datetime {
            font-size: 18px;
            font-weight: bold;
            color: #0d2b4a;
            white-space: nowrap;
        }
        .access-ip {
            margin-top: 6px;
            font-size: 13px;
            color: #0d2b4a;
            text-align: right;
            word-break: break-word;
        }
        .datetime.active {
            text-shadow: 0 0 10px rgba(47,158,58,0.50),
                0 0 18px rgba(47,158,58,0.30),
                0 0 28px rgba(47,158,58,0.15);
        }
        .datetime.inactive {
            text-shadow: 0 0 10px rgba(214,69,69,0.50),
                0 0 18px rgba(214,69,69,0.30),
                0 0 28px rgba(214,69,69,0.15);
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
            background: #f5f8fb;
            border: 2px solid #d5dde6;
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
            border-color: #d64545;
            background: #241619;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .card.online {
            border-color: #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .card.offline {
            border-color: #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .card.flow-green {
            border-color: #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .card.flow-red {
            border-color: #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
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
            color: #0d2b4a;
            line-height: 1.3;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .alloc-top {
            font-size: 13px;
            color: #0d2b4a;
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
            border: 1px solid #d5dde6;
            color: #0d2b4a;
            background: transparent;
            overflow-wrap: anywhere;
            word-break: break-word;
            text-align: center;
        }
        .badge.online {
            border-color: #2f9e3a;
            color: #1e6b16;
            box-shadow: 0 0 8px rgba(47,158,58,0.41),
                0 0 16px rgba(47,158,58,0.19);
        }
        .badge.nodata {
            border-color: #d64545;
            color: #b42318;
            box-shadow: 0 0 8px rgba(214,69,69,0.41),
                0 0 16px rgba(214,69,69,0.19);
        }
        .badge.alarm {
            border-color: #d64545;
            color: #b42318;
            box-shadow: 0 0 8px rgba(214,69,69,0.41),
                0 0 16px rgba(214,69,69,0.19);
        }
        .badge.active {
            border-color: #2f9e3a;
            color: #1e6b16;
            box-shadow: 0 0 8px rgba(47,158,58,0.41),
                0 0 16px rgba(47,158,58,0.19);
        }
        .badge.sync-ok {
            border-color: #2f9e3a;
            color: #1e6b16;
            box-shadow: 0 0 8px rgba(47,158,58,0.41),
                0 0 16px rgba(47,158,58,0.19);
        }
        .badge.sync-stale {
            border-color: #f08a12;
            color: #9a4b00;
        }
        .badge.sync-missing {
            border-color: #d64545;
            color: #b42318;
            box-shadow: 0 0 8px rgba(214,69,69,0.41),
                0 0 16px rgba(214,69,69,0.19);
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
            color: #0d2b4a;
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
            /* Temp and RH get the room for their high/low; lighting only needs icon + On/Off. */
            grid-template-columns: minmax(0, 1.35fr) minmax(0, 1.35fr) minmax(0, 0.7fr);
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
            border-top: 1px solid #d5dde6;
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
            background: #f5f8fb;
            border: 1px solid #d5dde6;
            border-radius: 8px;
            padding: 7px 8px;
            min-width: 0;
        }
        .footer-stat-label {
            font-size: 10px;
            color: #0d2b4a;
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
            border: 2px solid #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .metric-lighting.lighting-off {
            border: 2px solid #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .metric-grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 6px 8px;
        }
        .metric {
            background: #f5f8fb;
            border: 1px solid #d5dde6;
            border-radius: 8px;
            padding: 5px 7px;
            min-width: 0;
        }
        .metric-label {
            font-size: 10px;
            color: #0d2b4a;
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
        .metric-hilo-row { display: flex; align-items: center; gap: 6px; flex-wrap: nowrap; }
        .metric-hilo-row .metric-val { white-space: nowrap; overflow-wrap: normal; word-break: normal; }
        .metric-hilo { margin-left: auto; display: flex; flex-direction: column; align-items: flex-end; font-size: 12px; line-height: 1.2; color: #4a6078; white-space: nowrap; }
        .metric-hilo b { color: #0d2b4a; font-weight: 600; }
        .flow-green {
            border: 2px solid #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .flow-warn {
            border: 2px solid #f08a12;
            box-shadow: 0 0 10px rgba(240,138,18,0.52),
                0 0 20px rgba(240,138,18,0.30),
                0 0 34px rgba(240,138,18,0.14);
        }
        .flow-red {
            border: 2px solid #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .feed-green {
            border: 2px solid #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .feed-warn {
            border: 2px solid #f08a12;
            box-shadow: 0 0 10px rgba(240,138,18,0.52),
                0 0 20px rgba(240,138,18,0.30),
                0 0 34px rgba(240,138,18,0.14);
        }
        .feed-red {
            border: 2px solid #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
        }
        .env-green {
            border: 2px solid #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.36),
                0 0 34px rgba(47,158,58,0.19);
        }
        .env-warn {
            border: 2px solid #f08a12;
            box-shadow: 0 0 10px rgba(240,138,18,0.52),
                0 0 20px rgba(240,138,18,0.36),
                0 0 34px rgba(240,138,18,0.19);
        }
        .env-red {
            border: 2px solid #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.36),
                0 0 34px rgba(214,69,69,0.19);
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
            color: #0d2b4a;
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
            border: 1px solid #d64545;
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
            border-bottom: 1px solid #d5dde6;
        }
        .bore-row:last-child {
            border-bottom: none;
        }
        .bore-date {
            color: #0d2b4a;
        }
        .bore-val {
            font-weight: bold;
        }
        .summary-tile {
            margin-top: 16px;
            background: #f5f8fb;
            border: 2px solid #d5dde6;
            border-radius: 12px;
            padding: 14px;
        }
        .summary-tile.online {
            border-color: #2f9e3a;
            box-shadow: 0 0 10px rgba(47,158,58,0.52),
                0 0 20px rgba(47,158,58,0.25),
                0 0 34px rgba(47,158,58,0.12);
        }
        .summary-tile.offline {
            border-color: #d64545;
            box-shadow: 0 0 10px rgba(214,69,69,0.52),
                0 0 20px rgba(214,69,69,0.25),
                0 0 34px rgba(214,69,69,0.12);
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
            border: 2px solid #d5dde6;
            background: #f5f8fb;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .auger-mini.state-green {
            border-color: #2f9e3a;
            box-shadow: 0 0 8px rgba(47,158,58,0.25);
        }
        .auger-mini.state-warn {
            border-color: #f08a12;
            box-shadow: 0 0 8px rgba(240,138,18,0.18);
        }
        .auger-mini.state-red {
            border-color: #d64545;
            box-shadow: 0 0 8px rgba(214,69,69,0.22);
        }
        .auger-mini-label {
            font-size: 10px;
            color: #0d2b4a;
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
            color: #0d2b4a;
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
            background: #f5f8fb;
            border: 1px solid #d5dde6;
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
            color: #0d2b4a;
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
            .big-triple { grid-template-columns: minmax(0, 1.35fr) minmax(0, 1.35fr) minmax(0, 0.7fr); gap: 6px; }
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
                <div style="display: flex; align-items: center; gap: 16px">
                    <img src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring" style="height: 52px; width: auto; display: block">
                    <h1 id="headerTitle" class="{{ header_class }}" style="padding-left: 16px; border-left: 1px solid #d5dde6">Cherry Dene Farm</h1>
                </div>
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
                            <div class="birds-top">Birds: <span id="shed-birds-placed-{{ s.shed_no }}">{{ s.birds_placed }}</span> (<span id="shed-birds-remaining-{{ s.shed_no }}">{{ s.birds_remaining }}</span>) • Age: <span id="shed-age-{{ s.shed_no }}">{{ s.bird_age }}</span></div>
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
                            <div class="metric-hilo-row">
                                <div id="shed-temp-{{ s.shed_no }}" class="metric-val">{{ s.temp_c }}</div>
                                <div class="metric-hilo" aria-label="Today's high and low">
                                    <span>H <b id="shed-temp-hi-{{ s.shed_no }}">{{ s.temp_hi }}</b></span>
                                    <span>L <b id="shed-temp-lo-{{ s.shed_no }}">{{ s.temp_lo }}</b></span>
                                </div>
                            </div>
                        </div>
                        <div id="shed-rh-tile-{{ s.shed_no }}" class="metric metric-big {% if s.rh_glow %}{{ s.rh_glow }}{% endif %}">
                            <div class="metric-label">RH %</div>
                            <div class="metric-hilo-row">
                                <div id="shed-rh-{{ s.shed_no }}" class="metric-val">{{ s.rh_pct }}</div>
                                <div class="metric-hilo" aria-label="Today's high and low">
                                    <span>H <b id="shed-rh-hi-{{ s.shed_no }}">{{ s.rh_hi }}</b></span>
                                    <span>L <b id="shed-rh-lo-{{ s.shed_no }}">{{ s.rh_lo }}</b></span>
                                </div>
                            </div>
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
    setDashText(`shed-temp-hi-${s.shed_no}`, s.temp_hi);
    setDashText(`shed-temp-lo-${s.shed_no}`, s.temp_lo);
    setDashText(`shed-rh-hi-${s.shed_no}`, s.rh_hi);
    setDashText(`shed-rh-lo-${s.shed_no}`, s.rh_lo);
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
    if (pollDashboard.inFlight) return;
    pollDashboard.inFlight = true;
    try {
        const resp = await fetch('/api/overview', { cache: 'no-store' });
        if (!resp.ok) return;
        const payload = await resp.json();
        (payload.sheds || []).forEach(renderShed);
        if (payload.borehole) renderBorehole(payload.borehole);
        if (payload.overall) renderOverall(payload.overall);
    } catch (err) {
    } finally {
        pollDashboard.inFlight = false;
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


OFFICE_CARDS_HTML = """
<section aria-label="Farm summary" class="ss-summary">
  {% for m in summary %}
  <div class="ss-sum">
    <div class="ss-sum-label">{{ m.label }}</div>
    <div class="ss-sum-value tone-{{ m.tone }}">{{ m.value }}</div>
    <div class="ss-sum-sub">{{ m.sub }}</div>
  </div>
  {% endfor %}
</section>

{% if alarms %}
<section aria-label="Needs a look" class="ss-alarms">
  <span class="ss-alarms-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#c76300" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20L12 3z"></path><path d="M12 10v4"></path><path d="M12 17h.01"></path></svg>
    {{ alarms|length }} need{% if alarms|length == 1 %}s{% endif %} a look
  </span>
  {% for a in alarms %}<span class="ss-alarm-item">{{ a }}</span>{% endfor %}
</section>
{% endif %}

<section aria-label="Sheds" class="ss-grid">
  {% for s in sheds %}
  <article class="ss-card kind-{{ s.kind }}" data-shed="{{ s.shed_no }}">
    {% set off = not s.live %}
    {% if tv and pc %}<a class="ss-card-head ss-static ss-card-link" href="{{ url_for('shed_detail', shed_no=s.shed_no) }}">{% elif tv %}<div class="ss-card-head ss-static">{% else %}<button type="button" class="ss-card-head" aria-expanded="false" data-toggle="{{ s.shed_no }}">{% endif %}
      <span class="ss-row">
        <span class="ss-name">{{ s.name }}</span>
        <span class="ss-pill sync-{{ s.sync_kind }}"><span class="ss-dot"></span>{{ s.sync_label }}</span>
        <span class="ss-status kind-{{ s.kind }}">{{ s.status }}</span>
        {% if not tv %}<span class="ss-chevron" aria-hidden="true">+</span>{% endif %}
      </span>
      <span class="ss-row">
        <span class="ss-birds">{{ s.birds_line }}</span>
        {% if s.show_lights %}
        <span class="ss-pill lights-{{ 'on' if s.lights_on else 'off' }}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18h6"></path><path d="M10 22h4"></path><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"></path></svg>
          Lights {{ s.lights_label }}
        </span>
        {% endif %}
      </span>
      {% if s.split %}<span class="ss-row"><span class="ss-split">{{ s.split }}</span></span>{% endif %}
    {% if tv and pc %}</a>{% elif tv %}</div>{% else %}</button>{% endif %}

    {% if s.live or tv %}
    <div class="ss-tiles">
      <div class="ss-tile edge-{{ 'none' if off else s.temp_edge }}">
        <div class="ss-tile-main"><span class="ss-tile-label">Temp °C</span><span class="ss-big">{{ '--' if off else s.temp }}</span></div>
        <div class="ss-hilo"><span>H <b>{{ '--' if off else s.temp_hi }}</b></span><span>L <b>{{ '--' if off else s.temp_lo }}</b></span></div>
      </div>
      <div class="ss-tile edge-{{ 'none' if off else s.rh_edge }}">
        <div class="ss-tile-main"><span class="ss-tile-label">Humidity %</span><span class="ss-big">{{ '--' if off else s.rh }}</span></div>
        <div class="ss-hilo"><span>H <b>{{ '--' if off else s.rh_hi }}</b></span><span>L <b>{{ '--' if off else s.rh_lo }}</b></span></div>
      </div>
      <div class="ss-tile edge-{{ 'none' if off else s.water_edge }}"{% if not off %} data-water-tile="{{ s.shed_no }}"{% endif %}>
        <div class="ss-tile-main"><span class="ss-tile-label">Water now</span><span class="ss-mid">{% if off %}--{% else %}<span data-water="{{ s.shed_no }}">{{ s.water }}</span> <small>L/min</small>{% endif %}</span></div>
      </div>
      <div class="ss-tile edge-{{ 'none' if off else s.bin_edge }} ss-tile-bin">
        <div class="ss-tile-main"><span class="ss-tile-label">Feed bin{% if s.bin_pct is not none and not off %} · {{ s.bin_pct }}%{% endif %}</span><span class="ss-mid">{% if off %}--{% else %}{{ s.bin }} <small>kg</small>{% endif %}</span></div>
        <div class="ss-bar">{% if s.bin_pct is not none and not off %}<div class="ss-bar-fill edge-{{ s.bin_edge }}" style="width: {{ s.bin_pct }}%"></div>{% endif %}</div>
      </div>
    </div>
    {% if s.has_alarm %}<div class="ss-card-alarm">{{ s.alarm }}</div>{% endif %}

    <div class="ss-more">
      <div class="ss-augers">
        {% for a in s.augers %}
        <div class="ss-auger"><span class="ss-auger-name"><span class="ss-dot dot-{{ 'none' if off else a.kind }}"></span>{{ a.name }}</span><span class="ss-auger-state">{{ '--' if off else a.state }}</span></div>
        {% endfor %}
      </div>
      <div class="ss-stats">
        {% for st in s.stats %}<div class="ss-stat"><span>{{ st.label }}</span><b>{{ '--' if off else st.value }}</b></div>{% endfor %}
      </div>
      <div class="ss-foot">
        <span>Crop {{ s.crop }} · Updated {{ s.updated }}</span>
        {% if not tv %}<a href="{{ url_for('shed_detail', shed_no=s.shed_no) }}">Open shed</a>{% endif %}
      </div>
    </div>
    {% else %}
    <div class="ss-idle">{{ s.idle_text }}</div>
    <div class="ss-foot"><span>Updated {{ s.updated }}</span>{% if not tv %}<a href="{{ url_for('shed_detail', shed_no=s.shed_no) }}">Open shed</a>{% endif %}</div>
    {% endif %}
  </article>
  {% endfor %}

  {% if tv %}
  <article class="ss-card kind-water">
    {% if pc %}<a class="ss-card-head ss-static ss-card-link" href="{{ url_for('borehole_detail') }}">{% else %}<div class="ss-card-head ss-static">{% endif %}
      <span class="ss-row"><span class="ss-name">Bore hole</span><span class="ss-status kind-{{ borehole.kind }}">{{ borehole.status }}</span></span>
      <span class="ss-row"><span class="ss-birds">Flow now {{ borehole.water }} L/min</span></span>
    {% if pc %}</a>{% else %}</div>{% endif %}
    <div class="ss-idle"><b>{{ borehole.daily }} L</b> today<br>Last 7 days {{ borehole.weekly }} L</div>
    <div class="ss-foot"><span>Updated {{ borehole.updated }}</span></div>
  </article>
  {% endif %}
</section>

{% if not tv %}
<section aria-label="Bore hole" class="ss-borehole kind-{{ borehole.kind }}">
  <h2>Bore hole</h2>
  <span class="ss-status kind-{{ borehole.kind }}">{{ borehole.status }}</span>
  <div class="ss-bh-stat"><span>Flow now</span><b><span data-bore-water>{{ borehole.water }}</span> L/min</b></div>
  <div class="ss-bh-stat"><span>Today</span><b>{{ borehole.daily }} L</b></div>
  <div class="ss-bh-stat"><span>Last 7 days</span><b>{{ borehole.weekly }} L</b></div>
  <div class="ss-bh-stat"><span>Updated</span><b>{{ borehole.updated }}</b></div>
  {% if borehole.alarm %}<div class="ss-card-alarm">{{ borehole.alarm }}</div>{% endif %}
  <a href="{{ url_for('borehole_detail') }}" class="ss-link">Bore hole history</a>
</section>
{% endif %}
"""


OFFICE_HOME_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ farm_name }} · StockSense</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="cdf-theme-native" content="1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Semi+Condensed:wght@500;600;700&display=swap">
<style>
  :root {
    --bg: #eef2f6; --card: #ffffff; --soft-bg: #f5f8fb; --line: #d5dde6; --rule: #e3e9ef;
    --navy: #0b3a6b; --text: #0d2b4a; --muted: #4a6078;
    --green: #2f9e3a; --amber: #f08a12; --red: #d64545; --grey: #9aa8b6; --blue: #1676b8;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font-family: "Barlow", "Helvetica Neue", Helvetica, sans-serif; }
  a { color: var(--blue); }
  a:focus-visible, button:focus-visible { outline: 3px solid var(--amber); outline-offset: 2px; }
  .cond, .ss-name, .ss-big, .ss-mid, .ss-sum-value, .ss-borehole h2, .ss-farm { font-family: "Barlow Semi Condensed", "Barlow", sans-serif; }

  /* Header */
  .ss-header { background: #ffffff; border-bottom: 1px solid var(--line); padding: 10px 28px; display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
  .ss-logo { height: 52px; width: auto; display: block; }
  .ss-farmblock { display: flex; flex-direction: column; gap: 2px; padding-left: 20px; border-left: 1px solid var(--line); }
  .ss-farm { font-size: 26px; font-weight: 700; color: var(--navy); }
  .ss-when { font-size: 15px; color: var(--muted); }
  .ss-nav { margin-left: auto; display: flex; gap: 10px; flex-wrap: wrap; }
  .ss-nav a { display: flex; align-items: center; min-height: 44px; padding: 0 16px; border-radius: 10px; border: 1px solid #c5d0dc; background: #ffffff; color: var(--navy); font-weight: 600; text-decoration: none; }
  .ss-nav a.primary { background: var(--navy); border-color: var(--navy); color: #ffffff; }
  .ss-nav a.ss-gear, body.tv.tv-pc .ss-nav a.ss-gear { width: 44px; min-height: 44px; height: 44px; padding: 0; justify-content: center; border-radius: 50%; color: var(--muted); }
  .ss-nav a.ss-gear:hover { color: var(--navy); border-color: var(--navy); }
  body.tv:not(.tv-pc) .ss-nav a.ss-gear { width: 54px; height: 54px; min-height: 54px; }
  body.tv:not(.tv-pc) .ss-nav a.ss-gear svg { width: 30px; height: 30px; }
  .ss-clock { font-size: 40px; font-weight: 700; color: var(--navy); }
  .ss-weather { margin-left: auto; display: flex; align-items: center; gap: 10px; padding-left: 20px; border-left: 1px solid var(--line); color: var(--navy); white-space: nowrap; }
  .ss-weather[hidden] { display: none; }
  .ss-weather + .ss-nav, .ss-weather + .ss-clock, .ss-weather[hidden] + .ss-nav { margin-left: 0; }
  .ss-weather[hidden] + .ss-nav, .ss-weather[hidden] + .ss-clock { margin-left: auto; }
  .ss-wx-icon { font-size: 34px; line-height: 1; }
  .ss-wx-temp { font-family: "Barlow Semi Condensed", "Barlow", sans-serif; font-size: 34px; font-weight: 700; line-height: 1; }
  .ss-wx-info { display: flex; flex-direction: column; gap: 1px; }
  .ss-wx-text { font-size: 16px; font-weight: 600; }
  .ss-wx-sub { font-size: 13px; color: var(--muted); }

  main { max-width: none; margin: 0; padding: 20px 24px 32px; display: flex; flex-direction: column; gap: 18px; }
  /* Wide PC screens: use the whole width with more shed columns. */
  @media (min-width: 1600px) { body:not(.tv) .ss-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
  @media (min-width: 2100px) { body:not(.tv) .ss-grid { grid-template-columns: repeat(5, minmax(0, 1fr)); } }

  /* Farm summary */
  .ss-summary { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
  .ss-sum { background: #ffffff; border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px; }
  .ss-sum-label { font-size: 13px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); }
  .ss-sum-value { font-size: 28px; font-weight: 700; }
  .ss-sum-sub { font-size: 14px; color: var(--muted); }
  .tone-navy { color: var(--navy); } .tone-blue { color: var(--blue); } .tone-green { color: #2f8a1f; } .tone-amber { color: #c76300; }

  /* Alarm strip */
  .ss-alarms { background: #fff4e5; border: 1px solid #f3b366; border-radius: 14px; padding: 12px 16px; display: flex; align-items: center; gap: 10px 20px; flex-wrap: wrap; font-size: 16px; color: #5b3200; }
  .ss-alarms-head { display: flex; align-items: center; gap: 8px; font-weight: 700; color: #a34f00; }

  /* Shed cards */
  .ss-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
  .ss-card { background: #ffffff; border-radius: 16px; border: 1px solid var(--line); padding: 16px; display: flex; flex-direction: column; gap: 12px; box-shadow: inset 0 4px 0 var(--accent, var(--green)); min-width: 0; }
  .ss-card.kind-ok { --accent: var(--green); } .ss-card.kind-warn { --accent: var(--amber); } .ss-card.kind-alarm { --accent: var(--red); }
  .ss-card.kind-offline, .ss-card.kind-empty { --accent: var(--grey); } .ss-card.kind-water { --accent: var(--blue); }
  .ss-card-head { all: unset; display: flex; flex-direction: column; gap: 4px; cursor: default; }
  .ss-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .ss-name { font-size: 26px; font-weight: 700; color: var(--navy); white-space: nowrap; }
  .ss-status { margin-left: auto; padding: 4px 10px; border-radius: 999px; font-size: 13px; font-weight: 700; white-space: nowrap; }
  .ss-status.kind-ok { background: #e3f4e1; color: #1e6b16; } .ss-status.kind-warn { background: #fff0dc; color: #9a4b00; }
  .ss-status.kind-alarm { background: #fdecec; color: #8f1f1f; } .ss-status.kind-offline, .ss-status.kind-empty { background: #eceff3; color: var(--muted); }
  .ss-chevron { display: none; font-size: 22px; color: var(--muted); width: 18px; text-align: center; }
  .ss-pill { display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px; border-radius: 999px; font-size: 12px; font-weight: 700; white-space: nowrap; flex-shrink: 0; }
  .ss-pill.sync-ok { background: #e3f4e1; color: #1e6b16; } .ss-pill.sync-bad { background: #fdecec; color: #8f1f1f; }
  .ss-pill .ss-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .ss-pill.lights-on { margin-left: auto; background: #fff4cf; color: #7a5600; } .ss-pill.lights-off { margin-left: auto; background: #eceff3; color: var(--muted); }
  .ss-birds { font-size: 15px; color: var(--muted); }
  .ss-tiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .ss-tile { border-radius: 12px; padding: 10px 12px; background: var(--soft-bg); border: 2px solid var(--green); display: flex; align-items: center; gap: 8px; min-width: 0; }
  .ss-tile.edge-warn { border-color: var(--amber); } .ss-tile.edge-alarm { border-color: var(--red); }
  .ss-tile-bin { flex-direction: column; align-items: stretch; gap: 4px; }
  .ss-tile-main { display: flex; flex-direction: column; min-width: 0; }
  .ss-tile-label { font-size: 13px; color: var(--muted); }
  .ss-big { font-size: 32px; font-weight: 700; line-height: 1; }
  .ss-mid { font-size: 26px; font-weight: 700; line-height: 1.1; white-space: nowrap; }
  .ss-mid small { font-size: 15px; font-weight: 600; color: var(--muted); font-family: "Barlow", sans-serif; }
  .ss-hilo { margin-left: auto; display: flex; flex-direction: column; align-items: flex-end; font-size: 13px; color: var(--muted); line-height: 1.25; }
  .ss-hilo b { color: var(--text); }
  .ss-bar { height: 6px; width: 100%; align-self: stretch; border-radius: 3px; background: #dbe3ec; }
  .ss-bar-fill { height: 6px; border-radius: 3px; background: var(--blue); }
  .ss-bar-fill.edge-warn { background: var(--amber); }
  .ss-card-alarm { border-radius: 10px; padding: 8px 12px; background: #fdecec; color: #8f1f1f; font-size: 14px; font-weight: 600; }
  .ss-more { display: flex; flex-direction: column; gap: 12px; border-top: 1px solid var(--rule); padding-top: 10px; }
  .ss-alloc { font-size: 14px; color: var(--muted); }
  .ss-split { font-size: 14px; font-weight: 600; color: var(--muted); }
  .ss-augers { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
  .ss-auger { border-radius: 10px; padding: 6px 10px; background: var(--soft-bg); display: flex; flex-direction: column; min-width: 0; }
  .ss-auger-name { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 700; }
  .ss-auger-state { font-size: 13px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ss-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); flex-shrink: 0; }
  .ss-dot.dot-warn { background: var(--amber); } .ss-dot.dot-alarm { background: var(--red); }
  .ss-stats { border-top: 1px solid var(--rule); padding-top: 10px; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
  .ss-stat { display: flex; flex-direction: column; min-width: 0; border: 2px solid #c9d4df; border-radius: 7px; background: var(--soft-bg); padding: 3px 7px; }
  .ss-stat span { font-size: 12px; color: var(--muted); white-space: nowrap; }
  .ss-stat b { font-size: 16px; white-space: nowrap; }
  .ss-foot { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; color: var(--muted); margin-top: auto; }
  .ss-foot a { font-weight: 600; }
  .ss-idle { border-radius: 12px; background: var(--soft-bg); padding: 16px; font-size: 15px; color: #31475e; line-height: 1.4; }

  /* Bore hole */
  .ss-borehole { background: #ffffff; border-radius: 16px; border: 1px solid var(--line); box-shadow: inset 0 4px 0 var(--blue); padding: 16px 20px; display: flex; align-items: center; gap: 14px 28px; flex-wrap: wrap; }
  .ss-borehole h2 { margin: 0; font-size: 26px; font-weight: 700; color: var(--navy); }
  .ss-borehole .ss-status { margin-left: 0; }
  .ss-bh-stat { display: flex; flex-direction: column; }
  .ss-bh-stat span { font-size: 13px; color: var(--muted); }
  .ss-bh-stat b { font-size: 20px; }
  .ss-link { margin-left: auto; font-weight: 600; }

  /* Tablets */
  @media (max-width: 1100px) {
    body:not(.tv) .ss-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    body:not(.tv) .ss-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }

  /* iPhone: stacked cards, tap a card to open its details */
  @media (max-width: 700px) {
    /* Phone header: logo and farm name side by side, then the date and time, then the
       office address, all centred, then the menu buttons. */
    body:not(.tv) .ss-header { padding: 10px 14px; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; column-gap: 12px; row-gap: 4px; text-align: center; }
    body:not(.tv) .ss-farmblock { display: contents; }
    body:not(.tv) .ss-logo { grid-column: 1; grid-row: 1; }
    body:not(.tv) .ss-farm { grid-column: 2; grid-row: 1; white-space: nowrap; overflow: hidden; line-height: 1.1; text-align: left; }
    body:not(.tv) .ss-when { grid-column: 1 / -1; grid-row: 2; display: flex; flex-direction: column; align-items: stretch; gap: 2px; min-width: 0; }
    body:not(.tv) #ssDate { display: block; white-space: nowrap; overflow: hidden; font-weight: 600; color: var(--navy); line-height: 1.15; }
    body:not(.tv) .ss-ip-sep { display: none; }
    body:not(.tv) .ss-weather { grid-column: 1 / -1; grid-row: 3; margin: 2px 0 0; padding: 6px 0 0; border-left: 0; border-top: 1px solid var(--line); justify-content: center; }
    body:not(.tv) .ss-nav { grid-column: 3; grid-row: 1; }
    body:not(.tv) .ss-logo { height: 40px; }
    body:not(.tv) .ss-farmblock { padding-left: 12px; }
    body:not(.tv) .ss-farm { font-size: 20px; }
    body:not(.tv) .ss-nav { margin-left: 0; display: flex; }
    body:not(.tv) .ss-nav a.ss-gear { width: 38px; height: 38px; min-height: 38px; }
    body:not(.tv) main { padding: 12px 12px 24px; gap: 12px; }
    body:not(.tv) .ss-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    body:not(.tv) .ss-sum { padding: 10px 12px; }
    body:not(.tv) .ss-sum-value { font-size: 22px; }
    body:not(.tv) .ss-alarms { flex-direction: column; align-items: flex-start; gap: 4px; font-size: 15px; }
    body:not(.tv) .ss-grid { grid-template-columns: 1fr; gap: 12px; }
    body:not(.tv) .ss-card { padding: 14px; gap: 10px; }
    body:not(.tv) .ss-card-head { cursor: pointer; }
    body:not(.tv) .ss-name { font-size: 22px; }
    body:not(.tv) .ss-chevron { display: inline-block; }
    body:not(.tv) .ss-tiles { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
    body:not(.tv) .ss-tile { padding: 6px 8px; flex-direction: column; align-items: flex-start; gap: 2px; }
    body:not(.tv) .ss-tile-label { font-size: 11px; }
    body:not(.tv) .ss-big, body:not(.tv) .ss-mid { font-size: 20px; }
    body:not(.tv) .ss-mid small { display: block; font-size: 12px; line-height: 1.1; }
    body:not(.tv) .ss-hilo { display: none; }
    body:not(.tv) .ss-card:not(.open) .ss-more { display: none; }
    body:not(.tv) .ss-card.open .ss-hilo { display: flex; margin-left: 0; flex-direction: row; gap: 6px; font-size: 12px; }
    body:not(.tv) .ss-augers { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    body:not(.tv) .ss-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    body:not(.tv) .ss-borehole { gap: 10px 18px; }
    body:not(.tv) .ss-link { margin-left: 0; }
  }

  /* TV wall: everything on one screen, no buttons */
  /* TV: fills the screen on its own; once the fit script runs (tv-scaled) it is laid out
     at 1920 x 1080 and scaled to fit, so every TV shows the same wall. */
  html.tv-html, body.tv { height: 100%; overflow: hidden; }
  body.tv { height: 100vh; overflow: hidden; }
  body.tv .ss-page { height: 100vh; display: flex; flex-direction: column; }
  body.tv.tv-scaled .ss-page { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; -webkit-transform-origin: 0 0; transform-origin: 0 0; }
  body.tv .ss-header { padding: 8px 24px; }
  body.tv .ss-clock { margin-left: auto; }
  body.tv main { max-width: none; flex: 1 1 auto; min-height: 0; padding: 12px 20px 14px; gap: 12px; }
  body.tv #ssCards { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
  body.tv .ss-summary { grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
  body.tv .ss-sum { padding: 8px 14px; gap: 0; }
  body.tv .ss-sum-sub { display: none; }
  body.tv .ss-sum-value { font-size: 26px; }
  body.tv .ss-alarms { padding: 8px 16px; font-size: 18px; }
  body.tv .ss-grid { flex: 1 1 auto; min-height: 0; grid-template-columns: repeat(5, minmax(0, 1fr)); grid-template-rows: repeat(2, minmax(0, 1fr)); gap: 12px; }
  body.tv .ss-card { padding: 12px 12px 8px; gap: 6px; overflow: hidden; min-height: 0; }
  body.tv .ss-name { font-size: 24px; }
  body.tv .ss-birds { font-size: 14px; }
  body.tv .ss-tiles { gap: 5px; }
  body.tv .ss-tile { padding: 4px 8px; }
  body.tv .ss-big { font-size: 28px; }
  body.tv .ss-mid { font-size: 22px; }
  body.tv .ss-more { gap: 6px; }
  body.tv .ss-alloc { font-size: 12px; }
  body.tv .ss-auger { padding: 3px 7px; }
  body.tv .ss-auger-name, body.tv .ss-auger-state { font-size: 12px; }
  body.tv .ss-stats { padding-top: 6px; gap: 3px 6px; }
  body.tv .ss-stat span { font-size: 11px; }
  body.tv .ss-stat b { font-size: 14px; }
  body.tv .ss-card-alarm { padding: 5px 8px; font-size: 13px; }
  body.tv .ss-foot { font-size: 11px; }
  body.tv .ss-idle { font-size: 17px; margin: auto 0; }
  body.tv { --bg: #b4c2d1; --soft-bg: #e6ecf3; --line: #7f93a9; --rule: #b9c6d4; --muted: #3c5167; }
  body.tv .ss-header { border-bottom: 3px solid #7f93a9; }
  body.tv .ss-sum, body.tv .ss-card { border: 2px solid #7f93a9; }
  body.tv .ss-card { box-shadow: inset 0 6px 0 var(--accent, var(--green)); }
  body.tv .ss-tile.edge-none, body.tv .ss-auger, body.tv .ss-idle, body.tv .ss-card-note { border: 2px solid #a3b3c4; }
  body.tv .ss-stats { border-top: 2px solid #b9c6d4; }
  body.tv .ss-more { border-top: 2px solid #b9c6d4; padding-top: 4px; gap: 4px; }
  body.tv .ss-alarms { border-width: 2px; }
  body.tv .ss-chevron { display: none !important; }
  body.tv .ss-card .ss-more { display: flex !important; }
  body.tv .ss-card-head { cursor: default; }
  body.tv .ss-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  body.tv .ss-augers { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  body.tv .ss-stats { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  body.tv .ss-hilo { display: flex; }
  body.tv .ss-tile.edge-none { border-color: #a3b3c4; }
  body.tv .ss-dot.dot-none { background: var(--grey); }
  body.tv .ss-card.kind-offline .ss-big, body.tv .ss-card.kind-offline .ss-mid,
  body.tv .ss-card.kind-empty .ss-big, body.tv .ss-card.kind-empty .ss-mid { color: var(--grey); }
  body.tv .ss-card-note { border-radius: 8px; padding: 5px 8px; background: #eceff3; color: var(--muted); font-size: 13px; font-weight: 600; }
  /* TV readability: a bigger header with the date beside the farm name, and larger,
     darker small print in the cards (they have the room). */
  body.tv { --muted: #2c3f54; }
  body.tv .ss-header { padding: 8px 32px; gap: 28px; }
  body.tv .ss-logo { height: 70px; }
  body.tv .ss-farmblock { flex-direction: row; align-items: baseline; gap: 22px; padding-left: 28px; border-left-width: 3px; }
  body.tv .ss-farm { font-size: 44px; }
  body.tv .ss-when { font-size: 30px; font-weight: 600; color: var(--text); }
  body.tv .ss-farmblock { gap: 16px; }
  body.tv .ss-clock { font-size: 64px; display: flex; align-items: baseline; gap: 18px; white-space: nowrap; }
  body.tv .ss-clock-date { font-size: 30px; font-weight: 600; color: var(--text); }
  body.tv .ss-sum-label { font-size: 15px; color: var(--muted); }
  body.tv .ss-sum-value { font-size: 32px; }
  body.tv .ss-alarms { font-size: 21px; }
  body.tv .ss-name { font-size: 28px; }
  body.tv .ss-status, body.tv .ss-pill { font-size: 15px; }
  body.tv .ss-birds { font-size: 17px; font-weight: 600; color: var(--text); }
  body.tv .ss-tile-label { font-size: 15px; font-weight: 600; color: var(--muted); }
  body.tv .ss-big { font-size: 34px; line-height: 1.05; }
  body.tv .ss-mid { font-size: 27px; line-height: 1.1; }
  body.tv .ss-mid small { font-size: 16px; color: var(--muted); }
  body.tv .ss-hilo { font-size: 15px; line-height: 1.2; color: var(--muted); }
  body.tv .ss-alloc { font-size: 15px; color: var(--text); }
  body.tv .ss-auger-name { font-size: 15px; font-weight: 700; }
  body.tv .ss-auger-state { font-size: 15px; color: var(--text); }
  body.tv .ss-stat span { font-size: 14px; font-weight: 600; color: var(--muted); }
  body.tv .ss-stat b { font-size: 17px; white-space: nowrap; }
  body.tv .ss-grid .ss-stats { grid-template-columns: repeat(4, auto); justify-content: stretch; gap: 3px; padding-top: 3px; }
  body.tv .ss-grid .ss-stat { border: 2px solid #a3b3c4; border-radius: 7px; background: var(--soft-bg); padding: 1px 4px 1px; }
  body.tv .ss-grid .ss-stat span { font-size: 13px; line-height: 1.15; }
  body.tv .ss-grid .ss-stat b { font-size: 16px; line-height: 1.15; }
  body.tv .ss-grid .ss-card { gap: 5px; }
  /* Sections sit together with no empty gaps (an alarm line only takes space when
     there is one). Any spare height goes into the eight boxed figures at the bottom,
     so the reading tiles stay compact and there are no blank strips. */
  body.tv .ss-grid .ss-more { flex: 1 1 auto; min-height: 0; }
  body.tv .ss-grid .ss-stats { flex: 1 1 auto; grid-auto-rows: 1fr; align-content: stretch; }
  body.tv .ss-grid .ss-stat { justify-content: center; }
  body.tv .ss-card-alarm, body.tv .ss-card-note { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  body.tv .ss-card-alarm { font-size: 16px; }
  body.tv .ss-card-note { font-size: 15px; color: var(--text); }
  body.tv .ss-grid .ss-foot { display: none; }
  body.tv .ss-card > *, body.tv .ss-more > * { flex-shrink: 0; }
  body.tv .ss-grid .ss-split { font-size: 15px; line-height: 1.15; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  body.tv .ss-grid .ss-card { gap: 4px; padding: 10px 12px 6px; }
  body.tv .ss-grid .ss-card-head { gap: 2px; }
  body.tv .ss-grid .ss-tile { padding-top: 2px; padding-bottom: 2px; }
  body.tv .ss-card-alarm + .ss-card-note { display: none; }
  /* PC wall: same as the TV, plus the menu buttons and clickable sheds. */
  body.tv.tv-pc .ss-nav { display: flex; margin-left: auto; gap: 10px; }
  body.tv.tv-pc .ss-nav a { min-height: 50px; padding: 0 20px; font-size: 18px; }
  body.tv.tv-pc .ss-clock { font-size: 56px; }
  /* The wall's header always stays on one line, so the cards keep their full height. */
  body.tv .ss-header { flex-wrap: nowrap; }
  body.tv .ss-header > * { flex-shrink: 0; }
  body.tv .ss-farmblock { flex-shrink: 1; min-width: 0; overflow: hidden; white-space: nowrap; }
  body.tv.tv-pc .ss-farm { font-size: 38px; }
  body.tv.tv-pc .ss-when { font-size: 26px; }
  body.tv.tv-pc .ss-nav a { min-height: 46px; padding: 0 16px; font-size: 17px; }
  body.tv .ss-weather { gap: 14px; padding-left: 28px; border-left: 3px solid var(--line); }
  body.tv .ss-wx-icon { font-size: 52px; }
  body.tv .ss-wx-temp { font-size: 56px; }
  body.tv .ss-wx-text { font-size: 24px; color: var(--text); }
  body.tv .ss-wx-sub { font-size: 19px; color: var(--text); }
  /* Divider lines between the weather, the date and time, and the settings gear. */
  body.tv .ss-weather + .ss-clock { margin-left: 0; padding-left: 28px; }
  body.tv .ss-clock + .ss-nav { display: flex; margin-left: 0; padding-left: 24px; align-items: center; }
  /* All four header dividers are drawn the same height, centred, whatever is beside them. */
  body.tv .ss-farmblock, body.tv .ss-weather { border-left: 0; }
  body.tv .ss-farmblock, body.tv .ss-weather, body.tv .ss-weather + .ss-clock, body.tv .ss-clock + .ss-nav { position: relative; }
  body.tv .ss-farmblock::before, body.tv .ss-weather::before, body.tv .ss-weather + .ss-clock::before, body.tv .ss-clock + .ss-nav::before {
    content: ""; position: absolute; left: 0; top: 50%; width: 3px; height: var(--ss-div-h, 54px); margin-top: calc(var(--ss-div-h, 54px) / -2); background: var(--line); }
  body.tv.tv-pc { --ss-div-h: 48px; }
  body.tv.tv-pc .ss-weather + .ss-nav { margin-left: 8px; }

  /* The farm name sits centred between the dividers either side of it. */
  body.tv .ss-farmblock { flex: 1 1 auto; justify-content: center; text-align: center; padding-right: 28px; }
  body.tv .ss-farm { overflow: hidden; text-overflow: ellipsis; }
  body.tv .ss-weather { margin-left: 0; }
  body.tv.tv-pc .ss-clock-date { font-size: 26px; }
  body.tv.tv-pc .ss-wx-icon, body.tv.tv-pc .ss-wx-temp { font-size: 46px; }
  body.tv.tv-pc .ss-wx-text { font-size: 21px; }
  body.tv.tv-pc .ss-wx-sub { font-size: 16px; }
  body.tv .ss-grid .ss-birds { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .ss-card-link { color: inherit; text-decoration: none; cursor: pointer; }
  .ss-card-link:hover .ss-name { text-decoration: underline; }
  /* PC wall: the shed name's link covers the whole card, so a click anywhere opens it. */
  body.tv.tv-pc .ss-grid .ss-card { position: relative; }
  body.tv.tv-pc .ss-grid .ss-card-link::after { content: ""; position: absolute; inset: 0; z-index: 2; border-radius: inherit; }
  body.tv.tv-pc .ss-grid .ss-card:hover { border-color: #0b3a6b; box-shadow: inset 0 6px 0 var(--accent, var(--green)), 0 0 0 2px #0b3a6b; }
  body.tv .ss-header { padding-top: 6px; padding-bottom: 6px; }
  body.tv main { padding-top: 10px; padding-bottom: 10px; gap: 10px; }
  body.tv #ssCards { gap: 10px; }
  body.tv .ss-sum { padding: 6px 14px; }
  body.tv .ss-alarms { padding: 6px 16px; }
  body.tv .ss-idle { font-size: 22px; }
  body.tv .ss-card.kind-offline .ss-big, body.tv .ss-card.kind-offline .ss-mid,
  body.tv .ss-card.kind-empty .ss-big, body.tv .ss-card.kind-empty .ss-mid { color: #6b7d90; }
</style>
</head>
<body class="{{ 'tv' if tv else '' }}{{ ' tv-pc' if pc else '' }}">
<div class="ss-page">
  <header class="ss-header">
    <img class="ss-logo" src="/static/stocksense-logo.png" alt="StockSense, Smarter Livestock Monitoring">
    <div class="ss-farmblock">
      <div class="ss-farm">{{ farm_name }}</div>
      {% if not tv %}<div class="ss-when"><span id="ssDate">--</span><span class="ss-ip"><span class="ss-ip-sep"> · </span>Office {{ host_ips }}</span></div>{% endif %}
    </div>
    <div class="ss-weather" id="ssWeather" title="Weather at NR15 1BE"{% if not weather %} hidden{% endif %}>
      <span class="ss-wx-icon" id="ssWxIcon" aria-hidden="true">{{ weather.icon if weather else '' }}</span>
      <span class="ss-wx-temp" id="ssWxTemp">{{ weather.temp if weather else '' }}</span>
      <span class="ss-wx-info">
        <span class="ss-wx-text" id="ssWxText">{{ weather.text if weather else '' }}</span>
        <span class="ss-wx-sub" id="ssWxSub">{{ ([weather.wind, weather.range, weather.rain]|select|join(' · ')) if weather else '' }}</span>
      </span>
    </div>
    {% if tv %}
    <div class="ss-clock"><span class="ss-clock-date" id="ssDate">--</span><span id="ssClock">--:--</span></div>
    {% endif %}
    <nav class="ss-nav" aria-label="Office pages">
      <a href="{{ url_for('office_settings_view') }}" class="ss-gear" title="Settings" aria-label="Settings"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg></a>
    </nav>
  </header>
  <main>
    <div id="ssCards">{{ cards_html|safe }}</div>
  </main>
</div>
<script>
// Weather in the header, refreshed every 10 minutes. Old-style JavaScript so TVs run it.
(function () {
  function set(id, text) { var el = document.getElementById(id); if (el) el.textContent = text || ''; }
  function load() {
    var req = new XMLHttpRequest();
    req.open('GET', '/api/weather?_=' + new Date().getTime(), true);
    req.onload = function () {
      var w = null;
      try { w = JSON.parse(req.responseText); } catch (e) { return; }
      var box = document.getElementById('ssWeather');
      if (!box) return;
      if (!w || !w.temp) { box.setAttribute('hidden', ''); return; }
      set('ssWxIcon', w.icon); set('ssWxTemp', w.temp); set('ssWxText', w.text);
      var sub = []; if (w.wind) sub.push(w.wind); if (w.range) sub.push(w.range); if (w.rain) sub.push(w.rain);
      set('ssWxSub', sub.join(' \u00b7 '));
      box.removeAttribute('hidden');
    };
    req.send();
  }
  setTimeout(load, {{ 15000 if weather else 3000 }});
  setInterval(load, 600000);
})();
</script>
{% if not tv or pc %}
<script>
// Fully Kiosk Browser (the farm TV) adds a "fully" object to every page. Show it the
// TV wall; open the page with ?tv=0 to keep the normal layout on a Fully Kiosk device.
if (window.fully && !/[?&]tv=0/.test(window.location.search)) { window.location.replace('/?tv=1'); }
{% if not tv %}
// Some TV browsers say they are phones. A screen too wide for a phone gets the wall,
// unless the phone layout was asked for with ?tv=0.
(function () {
  var wide = Math.max(window.innerWidth || 0, document.documentElement.clientWidth || 0) >= 1000;
  var chosen = /[?&]tv=0/.test(window.location.search) || /(^|;\s*)ss_tv=0/.test(document.cookie);
  if (wide && !chosen) { window.location.replace('/?tv=1'); }
})();
{% endif %}
</script>
{% endif %}
{% if tv %}
<script>
// TV wall. Written in old-style JavaScript on purpose: some smart TV browsers can't run
// the main script below, so fitting the screen, the clock and the refresh live here.
(function () {
  var body = document.body;
  var page = document.querySelector('.ss-page');
  document.documentElement.className += ' tv-html';
  // Some TV browsers report a window bigger than the screen they show (the page's full
  // height, or the screen before the TV's own zoom), which made the wall too big and cut
  // off the right and bottom. Use the smallest size any of them reports.
  function smallest(list) {
    var best = 0;
    for (var i = 0; i < list.length; i++) {
      var v = list[i];
      if (v && v > 0 && (!best || v < best)) best = v;
    }
    return best;
  }
  function fit() {
    var de = document.documentElement;
    var vv = window.visualViewport;
    var w = smallest([window.innerWidth, de.clientWidth, vv && vv.width, window.screen && window.screen.width]);
    var h = smallest([window.innerHeight, de.clientHeight, vv && vv.height, window.screen && window.screen.height]);
    if (!w || !h || !page) return;
    // Fit the height to 1080 and let the width follow the screen's shape, so the wall
    // fills a browser window or TV edge to edge. Very narrow windows keep 1920 wide instead.
    var scale = h / 1080;
    var width = w / scale;
    if (width < 1600) { scale = w / 1920; width = 1920; }
    if ((' ' + body.className + ' ').indexOf(' tv-scaled ') < 0) body.className += ' tv-scaled';
    page.style.width = width + 'px';
    page.style.webkitTransform = 'scale(' + scale + ')';
    page.style.transform = 'scale(' + scale + ')';
    page.style.left = Math.max(0, (w - width * scale) / 2) + 'px';
    page.style.top = Math.max(0, (h - 1080 * scale) / 2) + 'px';
  }
  fit();
  window.addEventListener('resize', fit);
  window.addEventListener('load', fit);
  setInterval(fit, 5000);

  setTimeout(function () {
    if (window.ssMainLoaded) return;
    var days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    var months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function clock() {
      var now = new Date();
      var c = document.getElementById('ssClock');
      var d = document.getElementById('ssDate');
      if (c) c.textContent = pad(now.getHours()) + ':' + pad(now.getMinutes());
      if (d) d.textContent = days[now.getDay()] + ' ' + now.getDate() + ' ' + months[now.getMonth()];
    }
    clock();
    setInterval(clock, 1000);
    setInterval(function () {
      var req = new XMLHttpRequest();
      req.open('GET', '/api/home-cards?tv=1&_=' + new Date().getTime(), true);
      req.onload = function () {
        var cards = document.getElementById('ssCards');
        if (req.status === 200 && cards) cards.innerHTML = req.responseText;
      };
      req.send();
    }, 5000);
  }, 1500);
})();
</script>
{% endif %}
<script>
window.ssMainLoaded = true;
const SS_TV = {{ 'true' if tv else 'false' }};
const SS_PC = {{ 'true' if pc else 'false' }};
const ssOpen = new Set();

function ssClock() {
  const now = new Date();
  const date = now.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
  const time = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const d = document.getElementById('ssDate');
  if (d) d.textContent = SS_TV ? now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }) : date + ' · ' + time;
  const c = document.getElementById('ssClock');
  if (c) c.textContent = time;
  ssFitPhoneHeader();
}

// Phone: size the farm name to fill the space beside the logo, with the date and time
// just smaller underneath.
function ssFitText(el, maxSize) {
  if (!el || !el.clientWidth) return;
  let lo = 12, hi = maxSize;
  while (hi - lo > 0.5) {
    const mid = (lo + hi) / 2;
    el.style.fontSize = mid + 'px';
    if (el.scrollWidth <= el.clientWidth) lo = mid; else hi = mid;
  }
  el.style.fontSize = lo + 'px';
}
function ssFitPhoneHeader() {
  if (SS_TV || !window.matchMedia('(max-width: 700px)').matches) {
    ['.ss-farm', '#ssDate'].forEach((sel) => { const el = document.querySelector(sel); if (el) el.style.fontSize = ''; });
    return;
  }
  const farm = document.querySelector('.ss-farm');
  ssFitText(farm, 44);
  // The date and time sit just under the farm name's size.
  const farmSize = parseFloat(farm && farm.style.fontSize) || 22;
  ssFitText(document.getElementById('ssDate'), farmSize * 0.85);
}
window.addEventListener('resize', ssFitPhoneHeader);
ssClock();
setInterval(ssClock, 1000);

// iPhone: tap a card's header to open or close its details. The open cards are
// remembered across the automatic refreshes below.
function ssApplyOpen() {
  document.querySelectorAll('.ss-card[data-shed]').forEach((card) => {
    const open = ssOpen.has(card.dataset.shed);
    card.classList.toggle('open', open);
    const head = card.querySelector('[data-toggle]');
    if (head) {
      head.setAttribute('aria-expanded', open ? 'true' : 'false');
      const chev = head.querySelector('.ss-chevron');
      if (chev) chev.textContent = open ? '−' : '+';
    }
  });
}
document.addEventListener('click', (event) => {
  const head = event.target.closest('[data-toggle]');
  if (!head || !window.matchMedia('(max-width: 700px)').matches) return;
  const key = head.dataset.toggle;
  if (ssOpen.has(key)) ssOpen.delete(key); else ssOpen.add(key);
  ssApplyOpen();
});

async function ssRefresh() {
  try {
    const resp = await fetch('/api/home-cards?tv=' + (SS_TV ? '1' : '0') + (SS_PC ? '&pc=1' : ''), { cache: 'no-store' });
    if (!resp.ok) return;
    document.getElementById('ssCards').innerHTML = await resp.text();
    ssApplyOpen();
  } catch (err) {
  }
}
setInterval(ssRefresh, 3000);

// Live water flow between refreshes.
if (window.EventSource) {
  const waterSource = new EventSource('/api/water-stream');
  waterSource.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      (payload.sheds || []).forEach((s) => {
        document.querySelectorAll('[data-water="' + s.shed_no + '"]').forEach((el) => { el.textContent = s.water_lpm; });
        const tile = document.querySelector('[data-water-tile="' + s.shed_no + '"]');
        if (tile) {
          tile.classList.remove('edge-ok', 'edge-warn', 'edge-alarm');
          tile.classList.add(String(s.water_glow || '').endsWith('-red') ? 'edge-alarm' : 'edge-ok');
        }
      });
      if (payload.borehole) {
        document.querySelectorAll('[data-bore-water]').forEach((el) => { el.textContent = payload.borehole.water_lpm; });
      }
    } catch (err) {
    }
  };
}

// Phone alarm notifications (unchanged from the previous office page).
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


def add_css_var_fallbacks(html, values):
    """Older TV browsers don't understand CSS variables (var(--x)), so every colour that
    uses one loses it: no grey background, no green/amber/red tile edges. Put a plain
    copy of each such declaration in front of it; modern browsers still use the var()."""
    def resolve(value):
        pattern = re.compile(r"var\(--([\w-]+)\s*(?:,\s*([^()]*))?\)")
        for _ in range(5):
            new = pattern.sub(lambda m: values.get(m.group(1)) or (m.group(2) or "").strip(), value)
            if new == value:
                break
            value = new
        return value

    def fix_style(block):
        def decl(m):
            prop, value = m.group(1), m.group(2)
            plain = resolve(value)
            if "var(" in plain or not plain.strip():
                return m.group(0)
            return "%s: %s; %s: %s" % (prop, plain.strip(), prop, value.strip())
        return re.sub(r"(?<=[{;\s])([a-z][a-z-]*)\s*:\s*([^;{}]*var\(--[^;{}]*?)(?=\s*;|\s*})", decl, block)

    return re.sub(r"(<style[^>]*>)(.*?)(</style>)", lambda m: m.group(1) + fix_style(m.group(2)) + m.group(3), html, flags=re.S)


# The colours the TV wall uses (the :root values with the TV's stronger overrides).
OFFICE_TV_CSS_VALUES = {
    "bg": "#b4c2d1", "card": "#ffffff", "soft-bg": "#e6ecf3", "line": "#7f93a9", "rule": "#b9c6d4",
    "navy": "#0b3a6b", "text": "#0d2b4a", "muted": "#2c3f54",
    "green": "#2f9e3a", "amber": "#f08a12", "red": "#d64545", "grey": "#9aa8b6", "blue": "#1676b8",
    "ss-div-h": "54px",
}
OFFICE_HOME_HTML = add_css_var_fallbacks(OFFICE_HOME_HTML.replace("</style>\n</head>", """
  /* Card top colour for browsers without CSS variables (same as the --accent rules). */
  body.tv .ss-card.kind-ok { box-shadow: inset 0 6px 0 #2f9e3a; } body.tv .ss-card.kind-warn { box-shadow: inset 0 6px 0 #f08a12; }
  body.tv .ss-card.kind-alarm { box-shadow: inset 0 6px 0 #d64545; } body.tv .ss-card.kind-water { box-shadow: inset 0 6px 0 #1676b8; }
  body.tv .ss-card.kind-offline, body.tv .ss-card.kind-empty { box-shadow: inset 0 6px 0 #9aa8b6; }
</style>
</head>""", 1), OFFICE_TV_CSS_VALUES)


EVENTS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Office Event Log</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    {{ office_page_head }}
    {{ office_compat_css }}
</head>
<body>
    {{ office_topbar('Event log') }}
    <div class="wrap">
        <div class="panel">
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
    {{ office_page_head }}
    {{ office_compat_css }}
</head>
<body>
    {{ office_topbar('Restore backup') }}
    <div class="wrap">
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
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Manual Feed Entry</title>
    {{ office_page_head }}
    <style>
        .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .form-row .full { grid-column: 1 / -1; }
        .state-pill { display: inline-flex; padding: 3px 10px; border-radius: 999px; font-size: 14px; font-weight: 600; background: var(--card-2); color: var(--muted); }
        .state-pill.in-crop { background: #e3f4e1; color: #1e6b16; }
        .state-pill.out-crop { background: #fff4e5; color: #9a4b00; }
        .table-wrap { max-height: 460px; }
        td select, td input { min-height: 44px; font-size: 15px; padding: 0 8px; }
        .row-actions { display: flex; gap: 6px; }
        .row-actions button { width: auto; min-height: 44px; padding: 0 14px; font-size: 15px; }
        .apply { display: grid; gap: 8px; margin-top: 12px; }
    </style>
</head>
<body>
    {{ office_topbar('Manual feed entry') }}
    <div class="wrap">
        {% if status_msg %}<div class="msg auto-dismiss {% if not status_ok %}error{% endif %}">{{ status_msg }}</div>{% endif %}
        <div class="hint" style="margin: 0 4px 16px">Normal in-crop silo feeding is recorded automatically from the weigh cells. Use this page for feed the weigh cells can't see.</div>
        <div class="cols">
            <section>
                <h2 class="section-title">Record shed feed</h2>
                <form class="card form" method="post" action="{{ url_for('office_feed_stock_allocate_view') }}">
                    <div class="form-row">
                        <div class="full">
                            <label class="field" for="manual_feed_shed_no">Shed</label>
                            <select id="manual_feed_shed_no" name="shed_no">
                                <option value="">Select active shed</option>
                                {% for target in active_targets %}
                                <option value="{{ target.shed_no }}" {% if preselected_shed_no == target.shed_no %}selected{% endif %}>{{ target.shed_name }} · {{ target.crop_code }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div><label class="field" for="manual_feed_kg">Feed (kg)</label><input id="manual_feed_kg" type="number" step="0.1" min="0" name="kg" inputmode="decimal" value=""></div>
                        <div><label class="field" for="manual_feed_note">Note</label><input id="manual_feed_note" type="text" name="note" value="" placeholder="Floor fed / moved from Shed 2"></div>
                    </div>
                    <button class="primary" type="submit">Record feed</button>
                </form>
            </section>
            <section style="margin-top:0">
                <h2 class="section-title">Record bin fill-up</h2>
                <form class="card form" method="post" action="{{ url_for('office_feed_stock_bin_fill_view') }}">
                    <div class="form-row">
                        <div class="full">
                            <label class="field" for="bin_fill_shed_no">Shed / bin</label>
                            <select id="bin_fill_shed_no" name="shed_no">
                                <option value="">Farm / unspecified</option>
                                {% for shed in shed_options %}
                                <option value="{{ shed.shed_no }}">{{ shed.shed_name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div><label class="field" for="bin_fill_kg">Feed (kg)</label><input id="bin_fill_kg" type="number" step="0.1" min="0" name="kg" inputmode="decimal" value=""></div>
                        <div><label class="field" for="bin_fill_note">Note</label><input id="bin_fill_note" type="text" name="note" value="" placeholder="Delivery / bin fill-up"></div>
                    </div>
                    <button class="primary" type="submit">Record fill-up</button>
                </form>
            </section>
        </div>

        <section>
            <h2 class="section-title">Feed movements (from the bin weigh cells)</h2>
            <div class="card">
                {% if feed_movement_event_rows %}
                <div class="table-wrap">
                    <table>
                        <thead><tr><th>Time</th><th>Shed</th><th>Movement</th><th>kg</th><th>Crop state</th><th>Crop</th><th>kg after</th></tr></thead>
                        <tbody>
                            {% for row in feed_movement_event_rows %}
                            <tr>
                                <td>{{ row.ts_label }}</td>
                                <td>{{ row.shed_name }}</td>
                                <td>{{ row.movement_label }}</td>
                                <td>{{ row.kg_label }}</td>
                                <td><span class="state-pill {{ row.crop_state_class }}">{{ row.crop_state_label }}</span></td>
                                <td>{{ row.crop_label }}</td>
                                <td>{{ row.feed_kg_after_label }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <div class="hint">No feed movement recorded yet.</div>
                {% endif %}
                {% if feed_movement_rows %}
                <div class="apply">
                    {% for row in feed_movement_rows %}
                    {% if row.can_apply %}
                    <form method="post" action="{{ url_for('office_pre_crop_feed_apply_view') }}">
                        <input type="hidden" name="shed_no" value="{{ row.shed_no }}">
                        <button type="submit">Add {{ row.out_of_crop_feed_out_label }} kg out-of-crop feed to {{ row.shed_name }}</button>
                    </form>
                    {% endif %}
                    {% endfor %}
                </div>
                {% endif %}
            </div>
        </section>

        <section>
            <h2 class="section-title">Feed activity history</h2>
            <div class="card">
                {% if transaction_rows %}
                <div class="table-wrap">
                    <table>
                        <thead><tr><th>Time</th><th>Type</th><th>Shed</th><th>Crop</th><th>Feed kg</th><th>Note</th><th></th></tr></thead>
                        <tbody>
                            {% for row in transaction_rows %}
                            <tr>
                                <td>{{ row.ts_label }}</td>
                                <td>
                                    {% if row.can_edit %}
                                    <select name="kind" form="{{ row.form_id }}">
                                        <option value="bin_fill" {% if row.display_kind == "bin_fill" %}selected{% endif %}>Bin fill-up</option>
                                        <option value="shed_allocation" {% if row.display_kind == "shed_allocation" %}selected{% endif %}>Shed feed</option>
                                    </select>
                                    {% else %}{{ row.kind_label }}{% endif %}
                                </td>
                                <td>
                                    {% if row.can_edit %}
                                    <select name="shed_no" form="{{ row.form_id }}">
                                        <option value="">--</option>
                                        {% for shed in shed_options %}
                                        <option value="{{ shed.shed_no }}" {% if row.shed_no == shed.shed_no %}selected{% endif %}>{{ shed.shed_name }}</option>
                                        {% endfor %}
                                    </select>
                                    {% else %}{{ row.shed_label }}{% endif %}
                                </td>
                                <td>{{ row.crop_label }}</td>
                                <td>{% if row.can_edit %}<input type="number" step="0.1" min="0" name="kg" value="{{ row.feed_kg_value }}" form="{{ row.form_id }}">{% else %}{{ row.feed_kg_label }}{% endif %}</td>
                                <td>{% if row.can_edit %}<input type="text" name="note" value="{{ row.note }}" form="{{ row.form_id }}">{% else %}{{ row.note if row.note else "--" }}{% endif %}</td>
                                <td>
                                    <div class="row-actions">
                                        {% if row.can_edit %}
                                        <form id="{{ row.form_id }}" method="post" action="{{ url_for('office_feed_stock_edit_view') }}">
                                            <input type="hidden" name="tx_id" value="{{ row.tx_id }}">
                                            <button type="submit">Update</button>
                                        </form>
                                        {% endif %}
                                        <form method="post" action="{{ url_for('office_feed_stock_delete_view') }}" onsubmit="return confirm('Delete this feed entry?');">
                                            <input type="hidden" name="tx_id" value="{{ row.tx_id }}">
                                            <button class="danger" type="submit">Delete</button>
                                        </form>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <div class="hint">No feed activity recorded yet.</div>
                {% endif %}
            </div>
        </section>
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
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Office Settings</title>
    {{ office_page_head }}
    <style>
        .list { border-radius: 14px; background: var(--card); overflow: hidden; }
        .item { display: flex; align-items: center; gap: 12px; min-height: 50px; padding: 0 18px; color: var(--text); text-decoration: none; font-size: 18px; font-weight: 500; border-top: 1px solid var(--track); }
        .item:first-child { border-top: 0; }
        .item:hover { background: var(--card-2); }
        .item > span:first-child { flex: 1 1 auto; }
        .item-sub { font-size: 15px; color: var(--muted); text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 55%; }
        .chev { color: var(--muted); font-size: 22px; line-height: 1; }
        .row { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; font-size: 16px; }
        .row-label { color: var(--muted); }
        .status { font-size: 18px; font-weight: 600; }
        .btns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        details summary { cursor: pointer; color: var(--muted); font-size: 15px; min-height: 32px; display: flex; align-items: center; }
        details .row { margin-top: 6px; font-size: 15px; }
        .mono { font-family: ui-monospace, Menlo, monospace; font-size: 14px; overflow-wrap: anywhere; }
        .checks { display: grid; gap: 8px; }
        .checks label { display: flex; align-items: center; gap: 10px; font-size: 16px; }
        .checks input { width: 22px; height: 22px; }
        .fields { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .fields .full { grid-column: 1 / -1; }
        .recipient { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-top: 1px solid var(--track); }
        .recipient span { flex: 1; overflow-wrap: anywhere; }
        .recipient button { width: auto; min-height: 44px; padding: 0 16px; }
        #settingsNotifyToggle.notify-on { background: #e3f4e1; border-color: #9fd39a; color: #1e6b16; }
        #settingsNotifyToggle.notify-blocked { background: #fdecec; border-color: #e3a0a0; color: #8f1f1f; }
        .notify-status { font-size: 14px; color: var(--muted); }
        .table-wrap { margin-top: 8px; max-height: 420px; }
    </style>
</head>
<body>
    {{ office_topbar('Settings') }}
    <div class="wrap">
        {% if status_msg %}<div class="msg auto-dismiss {% if not status_ok %}error{% endif %}">{{ status_msg }}</div>{% endif %}
        <div class="cols">
            <div class="col">
                <section>
                    <h2 class="section-title">Office</h2>
                    <nav class="list" aria-label="Office pages">
                        <a class="item" href="{{ url_for('office_feed_stock_view') }}"><span>Manual feed entry</span><span class="item-sub">Deliveries and allocations</span><span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('office_farm_health_view') }}"><span>Farm health</span><span class="item-sub">Controllers and sync</span><span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('office_crop_reports_view') }}"><span>Crop reports</span><span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('office_events_view') }}"><span>Event log</span><span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('office_versions_view') }}"><span>Versions</span><span class="chev">›</span></a>
                    </nav>
                </section>

                <section>
                    <h2 class="section-title">Backups</h2>
                    <nav class="list" aria-label="Backups">
                        <a class="item" href="{{ url_for('create_office_backup_view') }}"><span>Create backup now</span><span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('download_latest_office_backup_view') }}"><span>Download latest backup</span><span class="item-sub">{{ latest_backup_name }}</span><span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('restore_office_backup_view') }}"><span>Restore a backup</span><span class="chev">›</span></a>
                        <a class="item" href="{{ url_for('collect_controller_backups_now_view') }}"><span>Collect controller backups</span><span class="chev">›</span></a>
                    </nav>
                </section>

                <section>
                    <h2 class="section-title">Backup details</h2>
                    <div class="card" style="display:grid; gap:8px">
                        <div class="row"><span class="row-label">Automatic backups</span><span style="text-align:right">{{ backup_retention_text }}</span></div>
                        <div class="row"><span class="row-label">Latest</span><span class="mono">{{ latest_backup_name }}</span></div>
                        <details>
                            <summary>Backup folder</summary>
                            <div class="mono">{{ backup_dir }}</div>
                        </details>
                        <details>
                            <summary>Shed controller backups</summary>
                            <div class="table-wrap">
                                <table>
                                    <thead><tr><th>Controller</th><th>Controller backup</th><th>Status</th><th>Office copy</th><th>Copy status</th></tr></thead>
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
                </section>
            </div>

            <div class="col">
                <section>
                    <h2 class="section-title">Software</h2>
                    <div class="card" style="display:grid; gap:12px">
                        <div class="row"><span class="status">{{ update_status.status }}</span></div>
                        <div class="row"><span class="row-label">Last checked</span><span>{{ update_checked_at }}</span></div>
                        <div class="btns">
                            <form method="post" action="{{ url_for('office_check_update_view') }}"><button type="submit">Check for update</button></form>
                            {% if update_status.update_available %}
                            <form method="post" action="{{ url_for('office_apply_update_view') }}"><button class="primary" type="submit">Install update</button></form>
                            {% endif %}
                        </div>
                        <details>
                            <summary>Version details</summary>
                            <div class="row"><span class="row-label">Branch</span><span class="mono">{{ update_status.branch }}</span></div>
                            <div class="row"><span class="row-label">Installed</span><span class="mono">{{ update_status.local_commit }}</span></div>
                            <div class="row"><span class="row-label">Latest</span><span class="mono">{{ update_status.remote_commit }}</span></div>
                        </details>
                    </div>
                </section>

                <section>
                    <h2 class="section-title">Notifications</h2>
                    <div class="card" style="display:grid; gap:10px">
                        <div class="hint">Alarm alerts in this browser while the dashboard is open.</div>
                        <button id="settingsNotifyToggle" class="notify-btn" type="button">Enable notifications</button>
                        <div id="settingsNotifyStatus" class="notify-status"></div>
                    </div>
                </section>

                <section>
                    <h2 class="section-title">Email</h2>
                    <div class="card" style="display:grid; gap:12px">
                        <form method="post" action="{{ url_for('office_save_email_settings_view') }}" style="display:grid; gap:12px">
                            <div class="checks">
                                <label><input type="checkbox" name="report_email_enabled" value="1" {% if email_settings.report_email_enabled %}checked{% endif %}> Send emails (crop reports)</label>
                                <label><input type="checkbox" name="report_smtp_use_tls" value="1" {% if email_settings.report_smtp_use_tls %}checked{% endif %}> Use TLS</label>
                                <label><input type="checkbox" name="report_smtp_use_ssl" value="1" {% if email_settings.report_smtp_use_ssl %}checked{% endif %}> Use SSL</label>
                            </div>
                            <div class="fields">
                                <div class="full"><label class="field" for="report_email_from">From address</label><input id="report_email_from" type="text" name="report_email_from" value="{{ email_settings.report_email_from }}"></div>
                                <div><label class="field" for="report_smtp_host">SMTP host</label><input id="report_smtp_host" type="text" name="report_smtp_host" value="{{ email_settings.report_smtp_host }}"></div>
                                <div><label class="field" for="report_smtp_port">SMTP port</label><input id="report_smtp_port" type="text" name="report_smtp_port" value="{{ email_settings.report_smtp_port }}"></div>
                                <div><label class="field" for="report_smtp_username">SMTP username</label><input id="report_smtp_username" type="text" name="report_smtp_username" value="{{ email_settings.report_smtp_username }}"></div>
                                <div><label class="field" for="report_smtp_password">SMTP password</label><input id="report_smtp_password" type="password" name="report_smtp_password" value="{{ email_settings.report_smtp_password }}"></div>
                            </div>
                            <button class="primary" type="submit">Save email settings</button>
                        </form>
                        <details open>
                            <summary>Recipients</summary>
                            <form class="inline" method="post" action="{{ url_for('office_add_email_recipient_view') }}" style="margin-top:6px">
                                <div><label class="field" for="new_recipient_email">Add recipient</label><input id="new_recipient_email" type="email" name="recipient_email" value="" placeholder="name@example.com"></div>
                                <button type="submit">Add</button>
                            </form>
                            {% for recipient in email_settings.report_recipients %}
                            <div class="recipient">
                                <span>{{ recipient }}</span>
                                <form method="post" action="{{ url_for('office_remove_email_recipient_view') }}">
                                    <input type="hidden" name="recipient_email" value="{{ recipient }}">
                                    <button class="danger" type="submit">Remove</button>
                                </form>
                            </div>
                            {% else %}
                            <div class="hint" style="margin-top:6px">No recipients saved yet.</div>
                            {% endfor %}
                        </details>
                    </div>
                </section>
            </div>
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
    {{ office_page_head }}
    {{ office_compat_css }}
</head>
<body>
    {{ office_topbar('Versions') }}
    <div class="wrap">
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
    {{ office_page_head }}
    {{ office_compat_css }}
</head>
<body>
    {{ office_topbar('Farm health') }}
    <div class="wrap">
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
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }}</title>
    {{ office_page_head }}
    <style>
        .links { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
        .link-card { display: flex; flex-direction: column; gap: 4px; padding: 14px 18px; border-radius: 14px; background: var(--card); color: var(--text); text-decoration: none; }
        .link-card b { font-size: 19px; font-weight: 600; color: var(--navy); }
        .link-card span { font-size: 14px; color: var(--muted); }
        .link-card:hover { box-shadow: 0 0 0 2px var(--navy); }
        .pens { display: grid; gap: 12px; }
        .pen { border-radius: 14px; background: var(--card); padding: 16px 18px; border-left: 6px solid var(--green); }
        .pen-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .pen-name { font-size: 26px; font-weight: 600; color: var(--navy); }
        .pen-birds { margin-left: auto; text-align: right; }
        .plan-box { background: var(--card); border-radius: 14px; padding: 14px 18px 18px; }
        .plan-ends { display: flex; justify-content: space-between; font-size: 14px; font-weight: 600; color: var(--muted); margin-bottom: 6px; }
        .plan-shed { position: relative; height: 230px; border: 6px solid #6b5a3a; border-radius: 6px;
            background-color: #c9a458;
            background-image:
                repeating-linear-gradient(28deg, rgba(255,236,170,0.35) 0px, rgba(255,236,170,0.35) 2px, transparent 2px, transparent 9px),
                repeating-linear-gradient(-34deg, rgba(120,88,30,0.28) 0px, rgba(120,88,30,0.28) 2px, transparent 2px, transparent 13px),
                repeating-linear-gradient(72deg, rgba(240,214,140,0.4) 0px, rgba(240,214,140,0.4) 1px, transparent 1px, transparent 17px); }
        .plan-door { position: absolute; top: 50%; width: 10px; height: 90px; margin-top: -45px; background: repeating-linear-gradient(45deg, #f08a12 0 8px, #ffffff 8px 16px); }
        .door-left .plan-door { left: -14px; } .door-right .plan-door { right: -14px; }
        .plan-count { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
        .plan-count input { width: 90px; min-height: 48px; font-size: 20px; }
        .plan-count button { width: auto; min-height: 48px; padding: 0 18px; }
        .plan-row { position: absolute; inset: 0; display: flex; }
        .plan-cell { flex: 1 1 0; min-width: 0; display: flex; align-items: center; justify-content: center; text-decoration: none; color: var(--text);
            border: 0; border-radius: 0; background: transparent; padding: 0; min-height: 0; width: auto; font: inherit; cursor: pointer; }
        .plan-cell + .plan-cell { border-left: 3px dashed #5a4722; }
        .plan-cell.empty { background: rgba(255,255,255,0.18); }
        .plan-cell.empty .plan-card { background: rgba(255,255,255,0.75); border: 2px dashed var(--navy); }
        .plan-cell.empty .plan-card b { font-size: 34px; line-height: 1; }
        .plan-cell.empty:hover .plan-card { background: #ffffff; }
        .plan-cell.filled:hover .plan-card { box-shadow: 0 0 0 3px var(--navy); }
        .plan-card { display: flex; flex-direction: column; align-items: center; max-width: calc(100% - 12px); padding: 10px 14px; border-radius: 12px; background: rgba(255,255,255,0.95); text-align: center; }
        .plan-card b { font-size: 24px; color: var(--navy); line-height: 1.05; }
        .plan-card span { font-size: 15px; color: var(--soft); white-space: nowrap; }
        .plan-card small { font-size: 12px; color: var(--muted); font-weight: 600; }
        .modal { position: fixed; inset: 0; z-index: 50; display: none; align-items: center; justify-content: center; padding: 16px; background: rgba(13,43,74,0.55); }
        .modal.open { display: flex; }
        .modal-card { width: 100%; max-width: 560px; max-height: calc(100vh - 32px); overflow-y: auto; padding: 22px; border-radius: 16px; background: var(--card); display: flex; flex-direction: column; gap: 14px; }
        .shed-choices { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
        .shed-choice input { position: absolute; opacity: 0; pointer-events: none; }
        .shed-choice span { display: flex; align-items: center; justify-content: center; min-height: 52px; border-radius: 12px; border: 1px solid #c5d0dc; background: var(--card-2); font-size: 18px; font-weight: 600; cursor: pointer; }
        .shed-choice input:checked + span { background: var(--navy); border-color: var(--navy); color: #ffffff; }
        .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .pen-birds b { font-size: 28px; font-weight: 600; color: var(--navy); }
        .pen-birds span { display: block; font-size: 13px; color: var(--muted); }
        .pen-meta { margin: 2px 0 12px; font-size: 15px; color: var(--muted); }
        .pen-form { display: grid; grid-template-columns: 1.3fr 1.3fr 1fr 1fr 1fr; gap: 10px; align-items: end; }
        input[type="datetime-local"] { width: 100%; min-height: 60px; padding: 0 12px; border-radius: 12px; border: 1px solid #c5d0dc; background: var(--card-2); color: var(--text); font-family: inherit; font-size: 17px; }
        .list { border-radius: 14px; background: var(--card); overflow: hidden; }
        .row { display: grid; grid-template-columns: 1fr 1.2fr 1.3fr 0.8fr 0.8fr 0.8fr; gap: 8px; align-items: center; padding: 10px 14px; border-top: 1px solid var(--track); }
        .row.saved-row { grid-template-columns: 1fr 180px 140px; }
        .row button { font-size: 16px; padding: 0 6px; }
        .row:first-child { border-top: 0; }
        .row-name { font-size: 20px; font-weight: 600; color: var(--text); }
        .row-name small { display: block; font-size: 14px; font-weight: 500; color: var(--muted); }
        .row input, .row button { min-height: 54px; }
        @media (max-width: 1100px) {
            .links { grid-template-columns: 1fr 1fr; }
            .pen-form { grid-template-columns: 1fr 1fr 1fr; }
            .pen-form .field-wrap { grid-column: span 3; }
            .row { grid-template-columns: 1fr 1fr; }
            .row-name, .row .field-wrap { grid-column: 1 / -1; }
        }
    </style>
</head>
<body>
    {{ office_topbar(shed_name) }}
    <div class="wrap">
        {% if status_msg %}<div class="msg auto-dismiss {% if not status_ok %}error{% endif %}">{{ status_msg }}</div>{% endif %}

        <div class="stats">
            <div class="stat"><div class="stat-label">Birds in {{ shed_name }}</div><div class="stat-value cond">{{ total_birds }}</div><div class="stat-sub">Placed (live)</div></div>
            <div class="stat"><div class="stat-label">Pens</div><div class="stat-value cond">{{ active_rows|length }}</div><div class="stat-sub">{{ "Active" if active_rows else "None running" }}</div></div>
            <div class="stat"><div class="stat-label">Crop</div><div class="stat-value cond" style="font-size: 24px; padding-top: 6px">{{ active_crop_code }}</div><div class="stat-sub">{{ "Started " ~ crop_started if crop_started else "No active crop" }}</div></div>
        </div>

        <div class="links">
            <a class="link-card" href="{{ url_for('shed_tables_graphs_view', shed_no=shed_no) }}"><b>Feed &amp; water</b><span>Daily totals, click a day for its hours</span></a>
            <a class="link-card" href="{{ url_for('shed_mortality_view', shed_no=shed_no) }}"><b>Mortality</b><span>Record losses and see the log</span></a>
            <a class="link-card" href="{{ url_for('shed_thresholds_view', shed_no=shed_no) }}"><b>Thresholds</b><span>Temperature, humidity, water and feed limits</span></a>
            <a class="link-card" href="{{ url_for('shed_crop_history', shed_no=shed_no) }}"><b>Crop history</b><span>The last crops in this shed</span></a>
        </div>

        <section>
            <h2 class="section-title">Shed plan</h2>
            <div class="plan-box">
                <form class="plan-count" method="post" action="{{ url_for('shed_pen_count', shed_no=shed_no) }}">
                    <label class="field" for="penCount" style="margin:0">Pens in this shed</label>
                    <input id="penCount" type="number" name="pen_count" min="1" max="4" step="1" inputmode="numeric" value="{{ pen_count }}">
                    <button type="submit">Set</button>
                    <span class="hint">Up to 4 pens. Each pen is drawn to its share of the shed's birds. Click an empty pen to fill it.</span>
                </form>
                <div class="plan-ends"><span>Rear end</span><span>Door end</span></div>
                <div class="plan-shed door-right">
                    <div class="plan-door" aria-hidden="true"></div>
                    <div class="plan-row">
                        {% for box in plan_boxes|reverse %}
                        {% if box.pen %}
                        <a class="plan-cell filled" href="#pen-{{ box.pen.dest_shed }}" style="flex-grow: {{ box.weight }}">
                            <span class="plan-card"><b class="cond">{{ box.pen.name }}</b><span>{{ box.pen.placed }} ({{ box.pen.live }})</span>{% if box.pen.own %}<small>Own birds</small>{% endif %}</span>
                        </a>
                        {% else %}
                        <button type="button" class="plan-cell empty" style="flex-grow: {{ box.weight }}" data-box="{{ box.index }}" data-label="{{ box.label }}" data-dest="{{ box.preselect }}" data-own="{{ 1 if box.own_box else 0 }}">
                            <span class="plan-card"><b>+</b><span>{{ 'Own birds' if box.own_box else 'Empty pen' }}</span><small>Click to add</small></span>
                        </button>
                        {% endif %}
                        {% endfor %}
                    </div>
                </div>
            </div>
        </section>

        <section>
            <h2 class="section-title">Birds in this shed</h2>
            {% if active_rows %}
            <div class="pens">
                {% for r in active_rows %}
                <div class="pen" id="pen-{{ r.dest_shed }}">
                    <div class="pen-head">
                        <div class="pen-name cond">For {{ r.dest_shed_label }}</div>
                        <span class="pill on">Active</span>
                        <span class="pill">{{ r.end_label }}</span>
                        <div class="pen-birds"><b class="cond">{{ r.placed_display }} ({{ r.live_display }})</b><span>Placed (live){% if r.entry_mortality > 0 %} · {{ r.entry_mortality }} lost{% endif %}</span></div>
                    </div>
                    <div class="pen-meta">Started {{ r.placement_str }} · Crop {{ r.crop_code }}</div>
                    <form id="entry-form-{{ r.dest_shed }}" class="pen-form" method="post" action="{{ url_for('shed_entry_save', shed_no=shed_no, dest_shed=r.dest_shed) }}">
                        <div class="field-wrap">
                            <label class="field" for="placed{{ r.dest_shed }}">Birds placed</label>
                            <input id="placed{{ r.dest_shed }}" type="number" name="placed_bird_count" min="0" step="1" inputmode="numeric" value="{{ '' if r.placed_bird_count == 0 else r.placed_bird_count }}">
                        </div>
                        <div class="field-wrap">
                            <label class="field" for="placedat{{ r.dest_shed }}">Placed at</label>
                            <input id="placedat{{ r.dest_shed }}" type="datetime-local" name="placement_at" value="{{ r.placement_input_value }}">
                        </div>
                        <button class="primary" type="submit">Save</button>
                        {% if r.can_move %}
                        <button formaction="{{ url_for('shed_entry_move', shed_no=shed_no, dest_shed=r.dest_shed) }}" type="submit" onclick="return confirm('Move these birds from {{ shed_name }} to {{ r.dest_shed_label }}?');">Move to {{ r.dest_shed_label }}</button>
                        {% else %}
                        <button type="button" disabled>Move</button>
                        {% endif %}
                        <button class="danger" formaction="{{ url_for('shed_entry_end', shed_no=shed_no, dest_shed=r.dest_shed) }}" type="submit" onclick="return confirm('End the {{ r.dest_shed_label }} pen in {{ shed_name }}?');">End</button>
                    </form>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <div class="card hint">No birds in {{ shed_name }} at the moment. Enter a count for a shed below and press Start.</div>
            {% endif %}
        </section>

        {% set saved_rows = idle_rows|selectattr('placed_bird_count')|list %}
        {% if saved_rows %}
        <section>
            <h2 class="section-title">Saved, not started</h2>
            <div class="list">
                {% for r in saved_rows %}
                <form class="row saved-row" method="post" action="{{ url_for('shed_entry_end', shed_no=shed_no, dest_shed=r.dest_shed) }}">
                    <div class="row-name cond">For {{ r.dest_shed_label }}<small>{{ r.placed_display }} birds saved</small></div>
                    <button class="go" type="button" data-start="{{ r.dest_shed }}" data-birds="{{ r.placed_bird_count }}">Start…</button>
                    <button class="danger" type="submit" onclick="return confirm('Clear the saved count for {{ r.dest_shed_label }}?');">Clear</button>
                </form>
                {% endfor %}
            </div>
        </section>
        {% endif %}
    </div>
    <div class="modal" id="addPen" role="dialog" aria-modal="true" aria-labelledby="addPenTitle">
        <form class="modal-card" method="post" id="addPenForm">
            <h2 class="cond" id="addPenTitle" style="margin:0; color: var(--navy)">Add a pen</h2>
            <div class="hint" id="addPenWhere"></div>
            <input type="hidden" name="box" id="addPenPosition" value="0">
            <div>
                <label class="field">Which shed are these birds for?</label>
                <div class="shed-choices">
                    {% for r in idle_rows %}
                    <label class="shed-choice" data-own="{{ 1 if r.dest_shed in own_dests else 0 }}"><input type="radio" name="dest_pick" value="{{ r.dest_shed }}" data-action="{{ url_for('shed_entry_start', shed_no=shed_no, dest_shed=r.dest_shed) }}"><span>{{ r.dest_shed_label }}</span></label>
                    {% endfor %}
                </div>
            </div>
            <div class="two">
                <div><label class="field" for="addPenBirds">Birds placed</label><input id="addPenBirds" type="number" name="placed_bird_count" min="1" step="1" inputmode="numeric" required></div>
                <div><label class="field" for="addPenAt">Placed at</label><input id="addPenAt" type="datetime-local" name="placement_at"></div>
            </div>
            <div class="two">
                <button type="button" id="addPenCancel">Cancel</button>
                <button class="go" type="submit">Start pen</button>
            </div>
        </form>
    </div>
<script>
setTimeout(() => { document.querySelectorAll('.auto-dismiss').forEach((el) => { el.style.display = 'none'; }); }, 10000);
(function () {
    const modal = document.getElementById('addPen');
    const form = document.getElementById('addPenForm');
    const where = document.getElementById('addPenWhere');
    const pos = document.getElementById('addPenPosition');
    const at = document.getElementById('addPenAt');
    function nowLocal() {
        const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
        return d.toISOString().slice(0, 16);
    }
    // The rear box only takes the shed's own birds, and the other boxes only visiting
    // birds, so a pen always lands where it was clicked.
    function open(position, label, dest, birds, own) {
        pos.value = position;
        form.querySelectorAll('.shed-choice').forEach((c) => {
            c.style.display = (own === undefined || c.dataset.own === own) ? '' : 'none';
        });
        where.textContent = 'This pen goes ' + label + '. The shed’s own birds always stay at the rear.';
        at.value = nowLocal();
        document.getElementById('addPenBirds').value = birds || '';
        form.querySelectorAll('input[name="dest_pick"]').forEach((r) => { r.checked = dest !== undefined && r.value === String(dest); });
        modal.classList.add('open');
    }
    document.querySelectorAll('.plan-cell.empty').forEach((b) => b.addEventListener('click', () => open(b.dataset.box, b.dataset.label, b.dataset.dest || undefined, undefined, b.dataset.own)));
    document.querySelectorAll('[data-start]').forEach((b) => b.addEventListener('click', () => {
        const choice = form.querySelector('input[name="dest_pick"][value="' + b.dataset.start + '"]');
        const own = choice ? choice.closest('.shed-choice').dataset.own : '0';
        const empties = document.querySelectorAll('.plan-cell.empty[data-own="' + own + '"]');
        const spot = empties.length ? empties[empties.length - 1] : null;   // nearest the door
        open(spot ? spot.dataset.box : 0, spot ? spot.dataset.label : (own === '1' ? 'at the rear' : 'nearest the door'), b.dataset.start, b.dataset.birds);
    }));
    document.getElementById('addPenCancel').addEventListener('click', () => modal.classList.remove('open'));
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.classList.remove('open'); });
    form.addEventListener('submit', (e) => {
        const pick = form.querySelector('input[name="dest_pick"]:checked');
        if (!pick) { e.preventDefault(); alert('Pick which shed these birds are for.'); return; }
        form.action = pick.dataset.action;
    });
})();
</script>
</body>
</html>
"""


MORTALITY_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} Mortality</title>
    {{ office_page_head }}
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
        input[type="date"] { width: 100%; min-height: 60px; padding: 0 14px; border-radius: 12px; border: 1px solid #c5d0dc; background: var(--card-2); color: var(--text); font-family: inherit; font-size: 19px; }
        .stats { grid-template-columns: 1fr 1fr; margin-bottom: 14px; }
        .log { border-radius: 14px; background: var(--card); overflow: hidden; }
        .log-row { display: grid; grid-template-columns: 1.3fr 1fr 0.6fr 1.2fr; gap: 10px; align-items: center; min-height: 50px; padding: 8px 16px; border-top: 1px solid var(--track); font-size: 16px; }
        .log-row:first-child { border-top: 0; }
        .log-row.head { min-height: 40px; font-size: 13px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; background: var(--card-2); }
        .log-row .loss { font-weight: 600; font-size: 18px; color: var(--navy); }
        .log-row .note { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        @media (max-width: 860px) { .cols { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    {{ office_topbar((shed_name) ~ ' mortality') }}
    <div class="wrap">
        {% if status_msg %}<div class="msg auto-dismiss {% if not status_ok %}error{% endif %}">{{ status_msg }}</div>{% endif %}
        <div class="cols">
            <section>
                <h2 class="section-title">Record losses</h2>
                <div class="card">
                    {% if target_rows %}
                    <form class="form" method="post" action="{{ url_for('shed_mortality_add', shed_no=shed_no) }}">
                        <div>
                            <label class="field">Which birds</label>
                            <div class="sheds">
                                {% for row in target_rows %}
                                <label class="shed-opt">
                                    <input type="radio" name="dest_shed" value="{{ row.dest_shed }}" {% if loop.first %}checked{% endif %}>
                                    <span><b class="cond">For {{ row.dest_shed_label }}</b><small>{{ "{:,}".format(row.bird_count|int) }} live</small></span>
                                </label>
                                {% endfor %}
                            </div>
                        </div>
                        <div class="two">
                            <div>
                                <label class="field" for="bird_loss">Birds lost</label>
                                <input id="bird_loss" type="number" name="bird_loss" min="1" step="1" inputmode="numeric" value="" required>
                            </div>
                            <div>
                                <label class="field" for="mortality_date">Day</label>
                                <input id="mortality_date" type="date" name="mortality_date" value="{{ mortality_today }}" max="{{ mortality_today }}">
                            </div>
                        </div>
                        <div>
                            <label class="field" for="note">Note (optional)</label>
                            <input id="note" type="text" name="note" value="" placeholder="e.g. culls, heat">
                        </div>
                        <button class="primary" type="submit">Record mortality</button>
                    </form>
                    {% else %}
                    <div class="hint">No birds in this shed to record losses against. Start a pen on the shed page first.</div>
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


SHED_THRESHOLDS_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} Thresholds</title>
    {{ office_page_head }}
    <style>
        .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
        .limits { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .limits.two { grid-template-columns: repeat(2, 1fr); }
        .guide { display: grid; gap: 8px; }
        .guide div { display: flex; gap: 10px; align-items: baseline; font-size: 15px; color: var(--soft); }
        .guide b { flex: 0 0 74px; }
        @media (max-width: 860px) { .cols { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    {{ office_topbar((shed_name) ~ ' thresholds') }}
    <div class="wrap">
        {% if status_msg %}<div class="msg auto-dismiss {% if not status_ok %}error{% endif %}">{{ status_msg }}</div>{% endif %}
        <form method="post" action="{{ url_for('shed_thresholds_save_view', shed_no=shed_no) }}">
            <div class="cols">
                <div class="col">
                    <section>
                        <h2 class="section-title">Temperature (°C)</h2>
                        <div class="card form">
                            <div class="limits">
                                <div><label class="field" for="temp_low_c">Red below</label><input id="temp_low_c" type="number" step="0.1" inputmode="decimal" name="temp_low_c" value="{{ row.temp_low_c }}"></div>
                                <div><label class="field" for="temp_high_c">Red above</label><input id="temp_high_c" type="number" step="0.1" inputmode="decimal" name="temp_high_c" value="{{ row.temp_high_c }}"></div>
                                <div><label class="field" for="temp_amber_margin_c">Amber margin</label><input id="temp_amber_margin_c" type="number" step="0.1" inputmode="decimal" name="temp_amber_margin_c" value="{{ row.temp_amber_margin_c }}"></div>
                            </div>
                        </div>
                    </section>
                    <section>
                        <h2 class="section-title">Humidity (%RH)</h2>
                        <div class="card form">
                            <div class="limits">
                                <div><label class="field" for="rh_low_pct">Red below</label><input id="rh_low_pct" type="number" step="1" inputmode="numeric" name="rh_low_pct" value="{{ row.rh_low_pct }}"></div>
                                <div><label class="field" for="rh_high_pct">Red above</label><input id="rh_high_pct" type="number" step="1" inputmode="numeric" name="rh_high_pct" value="{{ row.rh_high_pct }}"></div>
                                <div><label class="field" for="rh_amber_margin_pct">Amber margin</label><input id="rh_amber_margin_pct" type="number" step="1" inputmode="numeric" name="rh_amber_margin_pct" value="{{ row.rh_amber_margin_pct }}"></div>
                            </div>
                            <div class="hint">Temperature and humidity limits are also sent to the shed controller.</div>
                        </div>
                    </section>
                </div>
                <div class="col">
                    <section>
                        <h2 class="section-title">Water (L/min)</h2>
                        <div class="card form">
                            <div class="limits two">
                                <div><label class="field" for="water_low_lpm">Red below</label><input id="water_low_lpm" type="number" step="0.01" inputmode="decimal" name="water_low_lpm" value="{{ row.water_low_lpm }}"></div>
                                <div><label class="field" for="water_amber_buffer_lpm">Amber above red by</label><input id="water_amber_buffer_lpm" type="number" step="0.01" inputmode="decimal" name="water_amber_buffer_lpm" value="{{ row.water_amber_buffer_lpm }}"></div>
                            </div>
                        </div>
                    </section>
                    <section>
                        <h2 class="section-title">Feed bin (kg)</h2>
                        <div class="card form">
                            <div class="limits two">
                                <div><label class="field" for="feed_low_kg">Red below</label><input id="feed_low_kg" type="number" step="1" inputmode="numeric" name="feed_low_kg" value="{{ row.feed_low_kg }}"></div>
                                <div><label class="field" for="feed_amber_buffer_kg">Amber above red by</label><input id="feed_amber_buffer_kg" type="number" step="1" inputmode="numeric" name="feed_amber_buffer_kg" value="{{ row.feed_amber_buffer_kg }}"></div>
                            </div>
                        </div>
                    </section>
                    <section>
                        <h2 class="section-title">How the colours work</h2>
                        <div class="card guide">
                            <div><b><span class="pill on">Green</span></b>Comfortably inside the limits.</div>
                            <div><b><span class="pill wait">Amber</span></b>Close to a red limit: inside the amber margin, or within the amber amount above red.</div>
                            <div><b><span class="pill bad">Red</span></b>Outside the limits. The shed tile shows red.</div>
                        </div>
                    </section>
                    <button class="primary" type="submit">Save thresholds</button>
                </div>
            </div>
        </form>
    </div>
<script>
setTimeout(() => { document.querySelectorAll('.auto-dismiss').forEach((el) => { el.style.display = 'none'; }); }, 10000);
</script>
</body>
</html>
"""


BOREHOLE_DETAIL_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Bore Hole</title>
    {{ office_page_head }}
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    {{ day_bars_head|safe }}
    <style>
        .stats { grid-template-columns: repeat(4, 1fr); }
        .stat-value.flow { color: #1676b8; }
        @media (max-width: 860px) { .stats { grid-template-columns: 1fr 1fr; } }
    </style>
</head>
<body>
    {{ office_topbar('Bore hole') }}
    <div class="wrap">
        {% if bh.alarm %}<div class="msg error">{{ bh.alarm }}</div>{% endif %}
        <div class="stats">
            <div class="stat"><div class="stat-label">Status</div><div class="stat-value cond" style="font-size:26px; padding-top:4px"><span class="pill {{ 'bad' if bh.kind == 'alarm' else ('on' if bh.kind == 'ok' else '') }}" style="font-size:18px">{{ bh.status }}</span></div><div class="stat-sub">Updated {{ bh.updated }}</div></div>
            <div class="stat"><div class="stat-label">Flow now</div><div class="stat-value cond flow">{{ bh.water }}{% if bh.water != '--' %} <span style="font-size:18px">L/min</span>{% endif %}</div><div class="stat-sub">Live</div></div>
            <div class="stat"><div class="stat-label">Today</div><div class="stat-value cond">{{ bh.daily }}{% if bh.daily != '--' %} <span style="font-size:18px">L</span>{% endif %}</div><div class="stat-sub">Since 6am</div></div>
            <div class="stat"><div class="stat-label">Last 7 days</div><div class="stat-value cond">{{ bh.weekly }}{% if bh.weekly != '--' %} <span style="font-size:18px">L</span>{% endif %}</div><div class="stat-sub">6am to 6am days</div></div>
        </div>
        <div id="waterBars"></div>
    </div>
{{ day_bars_js|safe }}
<script>
ssDayBars(document.getElementById('waterBars'), {
    title: 'Water', label: 'Water', unit: 'L', color: '#5fd0d8', subtitle: 'Last 45 days.',
    epochs: {{ bar_epochs|tojson }}, values: {{ water_values|tojson }}
});
</script>
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
    {{ office_page_head }}
    {{ office_compat_css }}
</head>
<body>
    {{ office_topbar((shed_name) ~ ' Crop history') }}
    <div class="wrap">

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
    {{ office_page_head }}
    {{ office_compat_css }}
</head>
<body>
    {{ office_topbar((shed_name) ~ ' ' ~ (summary.crop_code) ~ ' End of Crop Summary') }}
    <div class="wrap">

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
                                    <th>Temp High</th>
                                    <th>Temp Low</th>
                                    <th>RH High</th>
                                    <th>RH Low</th>
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
                                    <td>{{ "%.1f"|format(r.temp_max) if r.temp_max is not none else "--" }}</td>
                                    <td>{{ "%.1f"|format(r.temp_min) if r.temp_min is not none else "--" }}</td>
                                    <td>{{ "%.0f"|format(r.rh_max) if r.rh_max is not none else "--" }}</td>
                                    <td>{{ "%.0f"|format(r.rh_min) if r.rh_min is not none else "--" }}</td>
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
    {{ office_page_head }}
    {{ office_compat_css }}
</head>
<body>
    {{ office_topbar('Crop reports') }}
    <div class="wrap">

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


# ---------------------------------------------------------------------------
# Feed / water charts in the shed controller's style: daily bars (6am to 6am) with the
# total written on each bar; click a day to see its 24 hours. Shared by the shed
# feed/water pages, old crop history and the bore hole. Each page loads Chart.js, puts
# {{ day_bars_head|safe }} in its <head> and {{ day_bars_js|safe }} before its script,
# then calls ssDayBars(element, {...}).
# ---------------------------------------------------------------------------
DAY_BARS_HEAD = """
<style>
  .db { display: flex; flex-direction: column; gap: 16px; }
  .db-card { background: #ffffff; border: 1px solid #d5dde6; border-radius: 14px; padding: 16px 18px; }
  .db-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
  .db-title { margin: 0; font-size: 24px; color: #0b3a6b; }
  .db-sub { margin-top: 4px; font-size: 15px; color: #4a6078; }
  .db-back { min-height: 44px; padding: 0 16px; border-radius: 12px; border: 1px solid #c5d0dc; background: #ffffff; color: #0b3a6b; font: inherit; font-weight: 600; cursor: pointer; }
  .db-back[hidden] { display: none !important; }
  .db-chart-wrap { background: #f5f8fb; border: 1px solid #d5dde6; border-radius: 12px; padding: 10px; }
  .db-scroll { overflow-x: auto; overflow-y: hidden; -webkit-overflow-scrolling: touch; }
  .db-inner { position: relative; height: 380px; }
  .db-table-title { margin: 0 0 8px; font-size: 18px; color: #0b3a6b; }
  .db-table-wrap { max-height: 520px; overflow: auto; border: 1px solid #d5dde6; border-radius: 10px; }
  .db table { width: 100%; border-collapse: collapse; font-size: 15px; }
  .db th, .db td { border-bottom: 1px solid #e3e9ef; padding: 9px 10px; text-align: left; color: #0d2b4a; }
  .db th { position: sticky; top: 0; background: #f5f8fb; color: #4a6078; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; }
  .db-day { all: unset; cursor: pointer; color: #1676b8; font-weight: 600; text-decoration: underline; text-underline-offset: 3px; }
  .db-day:focus-visible { outline: 3px solid #f08a12; outline-offset: 2px; }
  .db-empty { color: #4a6078; padding: 12px 0; }
  @media (max-width: 700px) { .db-inner { height: 300px; } .db-title { font-size: 20px; } }
</style>
"""

DAY_BARS_JS = """
<script>
function ssDayBars(root, opts) {
  const DAY_START_HOUR = 6;   // the farm day runs 6am to 6am
  const unit = opts.unit, color = opts.color, label = opts.label;
  const MIN_BAR_PX = 38;      // bars never squeeze below this; the chart scrolls sideways instead
  const pad = (n) => String(n).padStart(2, '0');
  const fmt = (v) => v === null || v === undefined ? '--' : Number(v).toLocaleString('en-GB', { maximumFractionDigits: 1 });
  root.className = 'db';
  root.innerHTML =
    '<div class="db-card"><div class="db-head"><div><h2 class="db-title"></h2><div class="db-sub"></div></div>' +
    '<button type="button" class="db-back" hidden>&larr; All days</button></div>' +
    '<div class="db-chart-wrap"><div class="db-scroll"><div class="db-inner"><canvas></canvas></div></div></div></div>' +
    '<div class="db-card"><h3 class="db-table-title"></h3><div class="db-table-wrap"><table><thead><tr>' +
    '<th class="db-when"></th><th></th><th class="db-more"></th></tr></thead><tbody></tbody></table></div></div>';
  const q = (sel) => root.querySelector(sel);
  q('thead th:nth-child(2)').textContent = label + ' ' + unit;

  // Group the hourly points into farm days.
  const days = [], dayMap = {};
  (opts.epochs || []).forEach((epoch, i) => {
    if (epoch === null || epoch === undefined) return;
    const d6 = new Date((epoch - DAY_START_HOUR * 3600) * 1000);
    const key = d6.getFullYear() + '-' + pad(d6.getMonth() + 1) + '-' + pad(d6.getDate());
    if (!dayMap[key]) {
      const start = new Date(d6.getFullYear(), d6.getMonth(), d6.getDate(), DAY_START_HOUR, 0, 0);
      dayMap[key] = { key: key, start: start, total: 0, seen: 0, hours: {},
        label: start.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short' }) };
      days.push(dayMap[key]);
    }
    const v = opts.values[i];
    if (v !== null && v !== undefined) { dayMap[key].total += Number(v); dayMap[key].seen += 1; }
    dayMap[key].hours[epoch] = v;
  });
  days.sort((a, b) => a.start - b.start);
  if (days.length) days[days.length - 1].partial = (Date.now() - days[days.length - 1].start.getTime()) < 24 * 3600 * 1000;
  const grandTotal = days.reduce((sum, d) => sum + d.total, 0);

  q('.db-title').textContent = opts.title;
  if (!days.length) {
    q('.db-sub').textContent = opts.subtitle || '';
    q('.db-chart-wrap').outerHTML = '<div class="db-empty">No data yet.</div>';
    root.lastElementChild.remove();
    return;
  }

  // Each bar's figure written up the bar: inside when it fits, otherwise just above.
  const barLabels = { id: 'dbBarLabels', afterDatasetsDraw(c) {
    const meta = c.getDatasetMeta(0), data = c.data.datasets[0].data, g = c.ctx;
    g.save(); g.font = '600 13px "Barlow Semi Condensed", Barlow, sans-serif'; g.fillStyle = '#0d2b4a';
    meta.data.forEach((bar, i) => {
      const v = data[i]; if (v === null || v === undefined) return;
      const text = fmt(v), p = bar.getProps(['x', 'y', 'base'], true), h = p.base - p.y;
      const inside = h >= g.measureText(text).width + 10;
      g.save(); g.translate(p.x, inside ? p.y + 5 : p.y - 4); g.rotate(-Math.PI / 2);
      g.textAlign = inside ? 'right' : 'left'; g.textBaseline = 'middle'; g.fillText(text, 0, 0); g.restore();
    });
    g.restore();
  } };

  let chart = null;
  function draw(chartLabels, values, onPick) {
    if (chart) chart.destroy();
    const scroller = q('.db-scroll'), inner = q('.db-inner');
    const needed = chartLabels.length * MIN_BAR_PX + 70;
    inner.style.width = needed > scroller.clientWidth ? needed + 'px' : '100%';
    chart = new Chart(q('canvas'), {
      type: 'bar', plugins: [barLabels],
      data: { labels: chartLabels, datasets: [{ label: label + ' (' + unit + ')', data: values, borderRadius: 4, backgroundColor: color, borderColor: color }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        onClick: (e, els) => { if (onPick && els.length) onPick(els[0].index); },
        onHover: (e, els) => { e.native.target.style.cursor = (onPick && els.length) ? 'pointer' : 'default'; },
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
    q('.db-back').hidden = true;
    q('.db-sub').textContent = (opts.subtitle ? opts.subtitle + ' ' : '') + 'Daily totals, 6am to 6am · ' + fmt(grandTotal) + ' ' + unit + ' in total. Click a day to see its hours.';
    q('.db-table-title').textContent = 'Daily totals';
    q('.db-when').textContent = 'Day';
    q('.db-more').textContent = 'Hours';
    draw(days.map((d) => d.label + (d.partial ? ' (so far)' : '')), days.map((d) => d.seen ? Math.round(d.total * 10) / 10 : null), (i) => showDay(days[i].key));
    const body = q('tbody'); body.innerHTML = '';
    days.slice().reverse().forEach((d) => {
      const tr = document.createElement('tr');
      const when = document.createElement('td'), btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'db-day'; btn.textContent = d.label + (d.partial ? ' (so far)' : '');
      btn.addEventListener('click', () => showDay(d.key));
      when.appendChild(btn);
      const val = document.createElement('td'); val.textContent = d.seen ? fmt(d.total) + ' ' + unit : '--';
      const more = document.createElement('td'); more.textContent = d.seen; more.style.color = '#4a6078';
      tr.append(when, val, more); body.appendChild(tr);
    });
  }

  function showDay(key) {
    const d = dayMap[key]; if (!d) return;
    const slots = [];
    for (let h = 0; h < 24; h++) {
      const t = new Date(d.start.getTime() + h * 3600 * 1000), epoch = Math.round(t.getTime() / 1000);
      slots.push({ label: pad(t.getHours()) + ':00', value: Object.prototype.hasOwnProperty.call(d.hours, epoch) ? d.hours[epoch] : null });
    }
    q('.db-back').hidden = false;
    q('.db-sub').textContent = d.label + ', 6am to 6am' + (d.partial ? ' (so far)' : '') + ' · ' + fmt(d.total) + ' ' + unit + ' in total';
    q('.db-table-title').textContent = 'Hourly, ' + d.label;
    q('.db-when').textContent = 'Hour';
    q('.db-more').textContent = '';
    draw(slots.map((s) => s.label), slots.map((s) => s.value), null);
    const body = q('tbody'); body.innerHTML = '';
    slots.forEach((s) => {
      const tr = document.createElement('tr');
      const when = document.createElement('td'); when.textContent = s.label;
      const val = document.createElement('td'); val.textContent = s.value === null ? '--' : fmt(s.value) + ' ' + unit;
      tr.append(when, val, document.createElement('td')); body.appendChild(tr);
    });
    root.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  q('.db-back').addEventListener('click', showDays);
  if (opts.openLatestDay) showDay(days[days.length - 1].key); else showDays();
}
</script>
"""

app.jinja_env.globals["day_bars_head"] = Markup(DAY_BARS_HEAD)
app.jinja_env.globals["day_bars_js"] = Markup(DAY_BARS_JS)


def hourly_bar_series(rows, key):
    """Epochs and one metric's values from hourly rows, for ssDayBars."""
    epochs, values = [], []
    for row in rows:
        try:
            epochs.append(int(row.get("epoch")))
        except Exception:
            continue
        value = row.get(key)
        values.append(round(float(value), 2) if value is not None else None)
    return epochs, values


PERIOD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} crop {{ crop_code }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #0d2b4a;
            overflow-x: hidden;
        }
        .wrap {
            max-width: 1850px;
            margin: 0 auto;
            padding: 16px;
        }
        a {
            color: #0d2b4a;
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
            color: #0d2b4a;
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
            background: #f5f8fb;
            border: 2px solid #d5dde6;
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
            background: #f5f8fb;
            color: #0d2b4a;
            border: 1px solid #d5dde6;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
        }
        .toolbar button:hover {
            background: #f5f8fb;
        }
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid #d5dde6;
            border-radius: 10px;
            background: #f5f8fb;
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker {
            display: none;
        }
        .collapse[open] summary {
            margin-bottom: 12px;
        }
        .chart-wrap {
            background: #f5f8fb;
            border: 1px solid #d5dde6;
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
            border: 1px solid #d5dde6;
            border-radius: 10px;
            background: #f5f8fb;
            -webkit-overflow-scrolling: touch;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            table-layout: fixed;
        }
        th, td {
            border-bottom: 1px solid #d5dde6;
            padding: 8px 6px;
            text-align: left;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        th {
            color: #0d2b4a;
            position: sticky;
            top: 0;
            background: #f5f8fb;
        }
        td {
            color: #0d2b4a;
        }
        .hint {
            color: #0d2b4a;
            font-size: 12px;
            margin-top: 8px;
        }
        .empty {
            color: #0d2b4a;
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
    {{ day_bars_head|safe }}
</head>
<body>
    {{ office_topbar((shed_name) ~ ' · crop ' ~ (crop_code)) }}
    <div class="wrap">


        <div id="feedBars"></div>
        <div id="waterBars" style="margin-top: 22px"></div>
    </div>

{{ day_bars_js|safe }}
<script>
const cropSubtitle = {{ ('Crop ' ~ crop_code ~ '.')|tojson }};
ssDayBars(document.getElementById('feedBars'), {
    title: 'Feed', label: 'Feed', unit: 'kg', color: '#d9b86a', subtitle: cropSubtitle,
    epochs: {{ bar_epochs|tojson }}, values: {{ feed_values|tojson }}
});
ssDayBars(document.getElementById('waterBars'), {
    title: 'Water', label: 'Water', unit: 'L', color: '#5fd0d8', subtitle: cropSubtitle,
    epochs: {{ bar_epochs|tojson }}, values: {{ water_values|tojson }}
});
</script>
</body>
</html>
"""


METRIC_PERIOD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ shed_name }} {{ metric_title }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; font-family: Arial, sans-serif; background: #5b5b5b; color: #0d2b4a; overflow-x: hidden; }
        .wrap { max-width: 1500px; margin: 0 auto; padding: 16px; }
        a { color: #0d2b4a; text-decoration: none; }
        a:hover { text-decoration: underline; }
        h1 { margin: 0 0 6px 0; font-size: 30px; }
        .sub { color: #0d2b4a; margin-bottom: 16px; font-size: 14px; }
        .topbar { margin-bottom: 14px; }
        .status { margin-bottom: 14px; padding: 10px 12px; border-radius: 10px; background: #f5f8fb; border: 1px solid #d5dde6; }
        .status.ok { border-color: #2f9e3a; color: #0d2b4a; }
        .status.err { border-color: #d64545; color: #b42318; }
        .switches { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
        .switch {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 42px;
            padding: 8px 12px;
            border-radius: 10px;
            border: 1px solid #d5dde6;
            background: #f5f8fb;
            color: #0d2b4a;
        }
        .switch.active {
            border-color: #2f9e3a;
            color: #0d2b4a;
            box-shadow: 0 0 8px rgba(47,158,58,0.19);
        }
        .grid { display: grid; grid-template-columns: 1fr 1.15fr; gap: 14px; }
        .card { background: #f5f8fb; border: 2px solid #d5dde6; border-radius: 12px; padding: 14px; min-width: 0; }
        .card h2 { margin-top: 0; font-size: 20px; }
        .summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; margin-bottom: 16px; }
        .summary-card { background: #f5f8fb; border: 2px solid #d5dde6; border-radius: 12px; padding: 14px; }
        .summary-label { color: #0d2b4a; font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }
        .summary-value { margin-top: 8px; font-size: 28px; font-weight: 700; }
        .summary-note { color: #0d2b4a; font-size: 12px; margin-top: 6px; }
        .action-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: stretch; }
        .action-card {
            background: #f5f8fb;
            border: 1px solid #d5dde6;
            border-radius: 12px;
            padding: 12px;
            min-width: 0;
        }
        .action-card h3 {
            margin: 0 0 6px 0;
            font-size: 18px;
        }
        .action-card-sub {
            color: #0d2b4a;
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
        .field label { color: #0d2b4a; font-size: 14px; }
        input, select {
            width: 100%;
            padding: 10px 12px;
            border-radius: 8px;
            border: 1px solid #d5dde6;
            background: #f5f8fb;
            color: #0d2b4a;
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
            border: 1px solid #d5dde6;
            background: #f5f8fb;
            color: #0d2b4a;
            cursor: pointer;
        }
        .action-row button.full {
            width: auto;
            min-width: 150px;
        }
        .inline-note { margin-top: 8px; }
        .feed-extra-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
        .movement-actions { display: flex; gap: 8px; flex-wrap: wrap; }
        .movement-table { min-width: 760px; }
        .state-pill { display: inline-flex; align-items: center; justify-content: center; min-height: 30px; padding: 6px 10px; border-radius: 999px; border: 1px solid #d5dde6; background: #f5f8fb; font-weight: 700; font-size: 12px; }
        .state-pill.in-crop { border-color: #2f9e3a; color: #0d2b4a; }
        .state-pill.out-crop { border-color: #f08a12; color: #9a4b00; }
        .toolbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
        .toolbar button {
            background: #f5f8fb;
            color: #0d2b4a;
            border: 1px solid #d5dde6;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
        }
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid #d5dde6;
            border-radius: 10px;
            background: #f5f8fb;
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker { display: none; }
        .collapse[open] summary { margin-bottom: 12px; }
        .chart-wrap { background: #f5f8fb; border: 1px solid #d5dde6; border-radius: 10px; padding: 10px; overflow: hidden; }
        .chart-box { position: relative; height: 420px; }
        .table-wrap { max-height: 900px; overflow: auto; border: 1px solid #d5dde6; border-radius: 10px; background: #f5f8fb; -webkit-overflow-scrolling: touch; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
        th, td { border-bottom: 1px solid #d5dde6; padding: 8px 6px; text-align: left; overflow-wrap: anywhere; word-break: break-word; }
        th { color: #0d2b4a; position: sticky; top: 0; background: #f5f8fb; }
        .hint { color: #0d2b4a; font-size: 12px; margin-top: 8px; }
        .empty { color: #0d2b4a; font-size: 14px; padding: 10px 0; }
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
    {{ day_bars_head|safe }}
</head>
<body>
    {{ office_topbar((shed_name) ~ ' ' ~ (metric_title)) }}
    <div class="wrap">

        {% if status_msg %}
        <div class="status auto-dismiss {% if status_ok %}ok{% else %}err{% endif %}">{{ status_msg }}</div>
        {% endif %}

        <div class="log-tabs" role="tablist" aria-label="Log type">
            <a class="log-tab {% if metric == 'feed' %}active{% endif %}" role="tab" aria-selected="{{ 'true' if metric == 'feed' else 'false' }}" href="{{ url_for('shed_metric_period_view', shed_no=shed_no, metric='feed', period='daily') }}">Feed</a>
            <a class="log-tab {% if metric == 'water' %}active{% endif %}" role="tab" aria-selected="{{ 'true' if metric == 'water' else 'false' }}" href="{{ url_for('shed_metric_period_view', shed_no=shed_no, metric='water', period='daily') }}">Water</a>
        </div>

        <div id="metricBars"></div>

        {% if metric == 'feed' %}
        <div class="summary-grid">
            <div class="summary-card">
                <div class="summary-label">Manual Feed Recorded KG</div>
                <div class="summary-value">{{ shed_feed_stock_label }}</div>
                <div class="summary-note">Manual entries added to this shed in the active crop.</div>
            </div>
        </div>

        <div class="card" style="margin-bottom:14px;">
            <h2>Feed Movement Tracker</h2>
            <div class="sub" style="margin-bottom:14px;">Automatic bin movement for this shed. Each detected movement is listed separately with time, kg, and whether it happened in crop or out of crop.</div>
            {% if shed_feed_movement_events %}
            <div class="table-wrap">
                <table class="movement-table">
                    <thead><tr><th>Time</th><th>Movement</th><th>KG</th><th>Crop State</th><th>Crop</th><th>Feed KG After</th></tr></thead>
                    <tbody>
                        {% for row in shed_feed_movement_events %}
                        <tr>
                            <td>{{ row.ts_label }}</td>
                            <td>{{ row.movement_label }}</td>
                            <td>{{ row.kg_label }}</td>
                            <td><span class="state-pill {{ row.crop_state_class }}">{{ row.crop_state_label }}</span></td>
                            <td>{{ row.crop_label }}</td>
                            <td>{{ row.feed_kg_after_label }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="empty">No feed movement lines recorded for this shed yet.</div>
            {% endif %}
            {% if shed_feed_movement %}
            <div class="movement-actions" style="margin-top:12px;">
                {% if shed_feed_movement.can_apply %}
                <form method="post" action="{{ url_for('office_pre_crop_feed_apply_view') }}">
                    <input type="hidden" name="shed_no" value="{{ shed_no }}">
                    <input type="hidden" name="next" value="{{ feed_page_url }}">
                    <button class="full" type="submit">Add Out-Of-Crop To {{ shed_feed_movement.crop_code }}</button>
                </form>
                {% endif %}
                {% if shed_feed_movement.can_clear %}
                <form method="post" action="{{ url_for('office_pre_crop_feed_clear_view') }}">
                    <input type="hidden" name="shed_no" value="{{ shed_no }}">
                    <input type="hidden" name="next" value="{{ feed_page_url }}">
                    <button class="full" type="submit">Clear Movement</button>
                </form>
                {% endif %}
            </div>
            {% endif %}
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

{{ day_bars_js|safe }}
<script>
const augerRunsApiUrl = {{ auger_runs_api_url|tojson }};
let augerRunsSignature = {{ auger_run_rows|tojson }};

ssDayBars(document.getElementById('metricBars'), {
    title: {{ metric_title|tojson }},
    label: {{ metric_title|tojson }},
    unit: {{ bar_unit|tojson }},
    color: {{ metric_chart_color|tojson }},
    subtitle: {{ bars_subtitle|tojson }},
    epochs: {{ bar_epochs|tojson }},
    values: {{ bar_values|tojson }},
    openLatestDay: {{ 'true' if period == 'hourly' else 'false' }}
});

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
    <title>Bore Hole Water</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #5b5b5b;
            color: #0d2b4a;
            overflow-x: hidden;
        }
        .wrap {
            max-width: 1650px;
            margin: 0 auto;
            padding: 16px;
        }
        a {
            color: #0d2b4a;
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
            color: #0d2b4a;
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
            background: #f5f8fb;
            border: 2px solid #d5dde6;
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
            background: #f5f8fb;
            color: #0d2b4a;
            border: 1px solid #d5dde6;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
        }
        .toolbar button:hover {
            background: #f5f8fb;
        }
        .collapse summary {
            cursor: pointer;
            list-style: none;
            padding: 12px 14px;
            border: 1px solid #d5dde6;
            border-radius: 10px;
            background: #f5f8fb;
            font-weight: 700;
        }
        .collapse summary::-webkit-details-marker {
            display: none;
        }
        .collapse[open] summary {
            margin-bottom: 12px;
        }
        .chart-wrap {
            background: #f5f8fb;
            border: 1px solid #d5dde6;
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
            border: 1px solid #d5dde6;
            border-radius: 10px;
            background: #f5f8fb;
            -webkit-overflow-scrolling: touch;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            table-layout: fixed;
        }
        th, td {
            border-bottom: 1px solid #d5dde6;
            padding: 8px 6px;
            text-align: left;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        th {
            color: #0d2b4a;
            position: sticky;
            top: 0;
            background: #f5f8fb;
        }
        td {
            color: #0d2b4a;
        }
        .hint {
            color: #0d2b4a;
            font-size: 12px;
            margin-top: 8px;
        }
        .empty {
            color: #0d2b4a;
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
    {{ day_bars_head|safe }}
</head>
<body>
    {{ office_topbar('Bore Hole Water') }}
    <div class="wrap">


        <div id="waterBars"></div>
    </div>

{{ day_bars_js|safe }}
<script>
ssDayBars(document.getElementById('waterBars'), {
    title: 'Water', label: 'Water', unit: 'L', color: '#5fd0d8', subtitle: 'Last 45 days.',
    epochs: {{ bar_epochs|tojson }}, values: {{ water_values|tojson }},
    openLatestDay: {{ 'true' if period == 'hourly' else 'false' }}
});
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
            color: rgba(13,43,74,0.45);
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

def _num(text):
    try:
        return float(str(text).replace(",", "").strip())
    except Exception:
        return None


def _edge_kind(glow):
    # Old glow class names -> StockSense tile edge: ok / warn / alarm.
    glow = str(glow or "")
    if glow.endswith("-red"):
        return "alarm"
    if glow.endswith("-warn") or glow.endswith("-amber"):
        return "warn"
    return "ok"


def _with_unit(value, unit):
    return "--" if value in [None, "", "--"] else "%s %s" % (value, unit)


def shed_split_text(state, shed_no):
    """'Shed 1 - 8,450 (8,412) · Shed 4 - 5,000 (4,960)' for a shed holding birds for more
    than one destination (or for another shed). Empty when it would just repeat the total."""
    entries = ensure_shed_entry_bucket(state, shed_name_from_number(shed_no))
    pens = []
    for key in sorted(entries.keys(), key=lambda k: int(k) if str(k).isdigit() else 999):
        rec = clean_entry_record(entries.get(key, {}))
        if rec["bird_count"] <= 0 or rec["crop_active"] != 1:
            continue
        placed = rec.get("placed_bird_count") or rec["bird_count"]
        pens.append((str(key), "%s - %s (%s)" % (entry_shed_label(int(key)), fmt_value(placed, "i"), fmt_value(rec["bird_count"], "i"))))
    if not pens or (len(pens) == 1 and pens[0][0] == str(int(shed_no))):
        return ""
    return " · ".join(text for _, text in pens)


def office_home_shed(row, meta, split=""):
    meta = meta if isinstance(meta, dict) else {}
    online = row.get("card_state") == "online"
    active = bool(row.get("has_active_entry"))
    temp_edge = _edge_kind(row.get("temp_glow"))
    rh_edge = _edge_kind(row.get("rh_glow"))
    water_edge = _edge_kind(row.get("water_glow"))
    bin_edge = "warn" if str(row.get("feed_glow", "")).endswith("-red") else "ok"

    if not online and not row.get("has_data"):
        kind, status = "offline", "No data"
    elif not online:
        kind, status = "offline", "Not syncing"
    elif not active:
        kind, status = "empty", "Empty"
    elif row.get("alarm_active"):
        kind, status = "alarm", "Alarm"
    elif water_edge == "alarm":
        kind, status = "alarm", "No water"
    elif bin_edge == "warn":
        kind, status = "warn", "Bin low"
    elif temp_edge != "ok":
        kind, status = ("alarm" if temp_edge == "alarm" else "warn"), "Check temp"
    elif rh_edge != "ok":
        kind, status = ("alarm" if rh_edge == "alarm" else "warn"), "Check humidity"
    else:
        kind, status = "ok", "On target"

    sync_class = row.get("sync_pill_class", "")
    if sync_class == "sync-ok":
        sync_kind, sync_label = "ok", "Sync OK"
    elif sync_class == "sync-stale":
        sync_kind, sync_label = "bad", "Sync stale"
    else:
        sync_kind, sync_label = "bad", "No sync"

    feed_kg = _num(row.get("feed_kg"))
    capacity = _num(meta.get("feed_capacity_kg"))
    bin_pct = None
    if feed_kg is not None and capacity and capacity > 0:
        bin_pct = max(0, min(100, int(round(feed_kg * 100.0 / capacity))))

    augers = []
    for a in row.get("auger_tiles", []) or []:
        parts = [p for p in [a.get("timestamp"), a.get("runtime")] if p not in [None, "", "--"]]
        augers.append({
            "name": str(a.get("label", "")).replace(" Auger", "").replace("Auger ", "") or a.get("label", ""),
            "state": " · ".join(parts) if parts else "--",
            "kind": _edge_kind(a.get("glow")),
        })

    if active:
        birds_line = "%s (%s) birds · Day %s" % (row.get("birds_placed", "--"), row.get("birds_remaining", "--"), row.get("bird_age", "--"))
    else:
        birds_line = "No birds placed"

    idle_text = ""
    if kind == "offline":
        if row.get("updated") in [None, "", "--"]:
            idle_text = "This shed's controller hasn't reported to the office yet."
        else:
            idle_text = "No update from the shed since %s. Check the shed Pi and its network cable." % row.get("updated")
    elif kind == "empty":
        idle_text = "No active crop in this shed. Readings resume when birds are placed."

    return {
        "shed_no": row.get("shed_no"),
        "name": row.get("shed", ""),
        "kind": kind,
        "status": status,
        "sync_kind": sync_kind,
        "sync_label": sync_label,
        # Every shed shows a lights pill; "--" when the shed isn't reporting its lighting.
        "show_lights": True,
        "lights_on": bool(row.get("lighting_on")) and bool(row.get("lighting_visible")) and kind != "offline",
        "lights_label": ("On" if row.get("lighting_on") else "Off") if row.get("lighting_visible") and kind != "offline" else "--",
        "birds_line": birds_line,
        "alloc": row.get("allocation_text", ""),
        "split": split,
        "live": kind not in ["offline", "empty"],
        "idle_text": idle_text,
        "temp": row.get("temp_c", "--"), "temp_hi": row.get("temp_hi", "--"), "temp_lo": row.get("temp_lo", "--"), "temp_edge": temp_edge,
        "rh": row.get("rh_pct", "--"), "rh_hi": row.get("rh_hi", "--"), "rh_lo": row.get("rh_lo", "--"), "rh_edge": rh_edge,
        "water": row.get("water_lpm", "--"), "water_edge": water_edge,
        "bin": row.get("feed_kg", "--"), "bin_pct": bin_pct, "bin_edge": bin_edge,
        "augers": augers,
        "stats": [
            {"label": "Water yday", "value": _with_unit(row.get("water_7to7"), "L")},
            {"label": "Feed yday", "value": _with_unit(row.get("feed_7to7"), "kg")},
            {"label": "L / bird", "value": row.get("l_per_bird", "--")},
            {"label": "kg / bird", "value": row.get("kg_per_bird", "--")},
            {"label": "Mortality", "value": row.get("mortality_display", "--")},
            {"label": "Bin runs out", "value": row.get("runout_est", "--")},
            {"label": "Water total", "value": _with_unit(row.get("total_water_to_date"), "L")},
            {"label": "Feed total", "value": _with_unit(row.get("total_feed_to_date"), "kg")},
        ],
        "has_alarm": bool(row.get("alarm_active")),
        "alarm": row.get("alarm_msg", ""),
        "crop": row.get("crop_id", "--"),
        "updated": row.get("updated", "--"),
    }


def office_home_context(tv=False):
    ctx = build_dashboard_context()
    meta_map = load_controller_meta()
    entries_state = load_shed_entries_state()
    sheds = [
        office_home_shed(r, meta_map.get(str(int(r.get("shed_no") or 0)), {}), shed_split_text(entries_state, int(r.get("shed_no") or 0)))
        for r in ctx.get("sheds", [])
    ]

    ages = []
    for r in ctx.get("sheds", []):
        if r.get("has_active_entry"):
            age = _num(r.get("bird_age"))
            if age is not None:
                ages.append(int(age))
    if not ages:
        crop_day = "--"
    elif min(ages) == max(ages):
        crop_day = "Day %d" % ages[0]
    else:
        crop_day = "Day %d–%d" % (min(ages), max(ages))

    alarms = []
    for s in sheds:
        if s["has_alarm"]:
            alarms.append("%s · %s" % (s["name"], s["alarm"]))
        elif s["kind"] == "offline" and s["status"] == "Not syncing" and s["updated"] not in ["", "--"]:
            alarms.append("%s · not syncing since %s" % (s["name"], s["updated"]))
        elif s["kind"] in ["alarm", "warn"]:
            alarms.append("%s · %s" % (s["name"], s["status"].lower()))
    bh = ctx.get("borehole", {}) or {}
    if bh.get("alarm_active"):
        alarms.append("Bore hole · %s" % bh.get("alarm_msg", ""))

    overall = ctx.get("overall", {}) or {}
    active_sheds = len([s for s in sheds if s["live"]])
    summary = [
        {"label": "Birds on farm", "value": "%s (%s)" % (overall.get("birds_placed", "--"), overall.get("birds_remaining", "--")), "sub": "Placed (live) · %d shed%s" % (active_sheds, "" if active_sheds == 1 else "s"), "tone": "navy"},
        {"label": "Crop day", "value": crop_day, "sub": overall.get("farm_crop_id", "--"), "tone": "navy"},
        {"label": "Water this crop", "value": _with_unit(overall.get("water"), "L"), "sub": "Crop to date", "tone": "blue"},
        {"label": "Feed this crop", "value": _with_unit(overall.get("feed"), "kg"), "sub": "Crop to date", "tone": "green"},
        {"label": "Mortality", "value": overall.get("mortality_display", "--"), "sub": "This crop", "tone": "navy"},
        {"label": "Need a look", "value": str(len(alarms)), "sub": "Alarms and warnings", "tone": "amber" if alarms else "navy"},
    ]

    borehole = {
        "status": "Alarm" if bh.get("alarm_active") else ("Online" if bh.get("tile_state") == "online" else "Not syncing"),
        "kind": "alarm" if bh.get("alarm_active") else ("ok" if bh.get("tile_state") == "online" else "offline"),
        "water": bh.get("water_lpm", "--"),
        "daily": bh.get("daily_water", "--"),
        "weekly": bh.get("weekly_water", "--"),
        "updated": bh.get("updated", "--"),
        "alarm": bh.get("alarm_msg", ""),
    }

    farm_name = farm_identity()[0]
    if farm_name in ["", "Farm"]:
        farm_name = "Cherry Dene Farm Ltd."
    return {
        "tv": tv,
        "farm_name": farm_name,
        "host_ips": ctx.get("host_ips", ""),
        "header_active": ctx.get("header_class") == "active",
        "summary": summary,
        "alarms": alarms,
        "sheds": sheds,
        "borehole": borehole,
    }


# Current weather for the farm (NR15 1BE, Bergh Apton) from Open-Meteo: free, no key.
# Fetched in the background at most every 10 minutes so the home page never waits on it.
WEATHER_LAT, WEATHER_LON = 52.5693, 1.4067
WEATHER_CODES = {
    0: ("Clear", "\u2600\ufe0f"), 1: ("Mainly clear", "\U0001F324\ufe0f"), 2: ("Partly cloudy", "\u26c5"), 3: ("Overcast", "\u2601\ufe0f"),
    45: ("Fog", "\U0001F32B\ufe0f"), 48: ("Freezing fog", "\U0001F32B\ufe0f"),
    51: ("Light drizzle", "\U0001F326\ufe0f"), 53: ("Drizzle", "\U0001F326\ufe0f"), 55: ("Heavy drizzle", "\U0001F327\ufe0f"),
    56: ("Freezing drizzle", "\U0001F327\ufe0f"), 57: ("Freezing drizzle", "\U0001F327\ufe0f"),
    61: ("Light rain", "\U0001F326\ufe0f"), 63: ("Rain", "\U0001F327\ufe0f"), 65: ("Heavy rain", "\U0001F327\ufe0f"),
    66: ("Freezing rain", "\U0001F327\ufe0f"), 67: ("Freezing rain", "\U0001F327\ufe0f"),
    71: ("Light snow", "\U0001F328\ufe0f"), 73: ("Snow", "\U0001F328\ufe0f"), 75: ("Heavy snow", "\u2744\ufe0f"), 77: ("Snow grains", "\U0001F328\ufe0f"),
    80: ("Light showers", "\U0001F326\ufe0f"), 81: ("Showers", "\U0001F327\ufe0f"), 82: ("Heavy showers", "\U0001F327\ufe0f"),
    85: ("Snow showers", "\U0001F328\ufe0f"), 86: ("Heavy snow showers", "\U0001F328\ufe0f"),
    95: ("Thunderstorm", "\u26c8\ufe0f"), 96: ("Thunder and hail", "\u26c8\ufe0f"), 99: ("Thunder and hail", "\u26c8\ufe0f"),
}
_weather_cache = {"data": None, "fetched": 0, "ok_ts": 0, "busy": False}
_weather_lock = threading.Lock()


def _fetch_weather():
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
               "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,is_day"
               "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
               "&wind_speed_unit=mph&timezone=Europe%%2FLondon&forecast_days=1") % (WEATHER_LAT, WEATHER_LON)
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        cur = raw.get("current") or {}
        daily = raw.get("daily") or {}
        code = int(cur.get("weather_code") or 0)
        text, icon = WEATHER_CODES.get(code, ("", "\u2601\ufe0f"))
        if code in (0, 1) and not cur.get("is_day", 1):
            icon = "\U0001F319"
        points = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        wind_dir = points[int(((float(cur.get("wind_direction_10m") or 0) + 22.5) % 360) // 45)]

        def first(key):
            vals = daily.get(key) or []
            return vals[0] if vals else None

        hi, lo, rain = first("temperature_2m_max"), first("temperature_2m_min"), first("precipitation_probability_max")
        data = {
            "temp": "%d\u00b0C" % round(float(cur.get("temperature_2m"))),
            "text": text,
            "icon": icon,
            "wind": "%s %d mph" % (wind_dir, round(float(cur.get("wind_speed_10m") or 0))),
            "range": ("High %d\u00b0 \u00b7 Low %d\u00b0" % (round(hi), round(lo))) if hi is not None and lo is not None else "",
            "rain": ("%d%% rain" % rain) if rain is not None else "",
        }
        with _weather_lock:
            _weather_cache["data"] = data
            _weather_cache["fetched"] = _weather_cache["ok_ts"] = time.time()
    except Exception:
        with _weather_lock:
            _weather_cache["fetched"] = time.time() - 480  # try again in about 2 minutes
    finally:
        with _weather_lock:
            _weather_cache["busy"] = False


def current_weather():
    with _weather_lock:
        stale = time.time() - _weather_cache["fetched"] > 600
        if stale and not _weather_cache["busy"]:
            _weather_cache["busy"] = True
            threading.Thread(target=_fetch_weather, daemon=True).start()
        data = _weather_cache["data"]
        ok_ts = _weather_cache["ok_ts"]
    # Weather last fetched successfully over 3 hours ago is not "current" any more.
    if data and time.time() - ok_ts > 10800:
        return None
    return data


@app.route("/api/weather")
def office_weather_api():
    return jsonify(current_weather() or {})


def render_office_home(tv=False, pc=False):
    ctx = office_home_context(tv=tv)
    ctx["pc"] = pc
    ctx["weather"] = current_weather()
    ctx["cards_html"] = render_template_string(OFFICE_CARDS_HTML, **ctx)
    return render_template_string(OFFICE_HOME_HTML, **ctx)


# Smart TV browsers (Samsung Tizen, LG webOS, Sony/Android TV, Hisense VIDAA, Fire TV...)
# get the TV wall at the plain office address. ?tv=1 / ?tv=0 override it.
SMART_TV_AGENT_RE = re.compile(
    r"smart-?tv|tizen|web0s|webos|netcast|bravia|android tv|googletv|google tv|aft[a-z]|crkey|hbbtv|vidaa|hisense|roku|philipstv|nettv|viera|tv safari",
    re.I,
)


# Fully Kiosk runs in an Android web view ("; wv)" in its browser name); PCs never do.
FULLY_AGENT_RE = re.compile(r"fully|; wv\)", re.I)
# Apps that open links in their own Android web view (Facebook, Instagram, Google app...).
IN_APP_BROWSER_RE = re.compile(r"FBAN|FBAV|FB_IAB|Instagram|GSA/|Line/|Twitter|LinkedInApp|Snapchat", re.I)


PHONE_AGENT_RE = re.compile(r"iphone|ipod|android.*mobile|mobile safari|windows phone|blackberry|opera mini", re.I)


def request_wants_tv():
    choice = str(request.args.get("tv", "") or "").strip()
    if choice in ["1", "0"]:
        return choice == "1"
    return bool(SMART_TV_AGENT_RE.search(request.headers.get("User-Agent", "") or ""))


def office_home_layout():
    """(tv, pc): TVs get the wall, PCs get the wall with menu buttons, phones the stacked cards."""
    # ?tv=0 / ?tv=1 is remembered on that device (cookie), so a wrongly detected screen
    # only needs setting once.
    choice = str(request.args.get("tv", "") or request.cookies.get("ss_tv", "") or "").strip()
    agent = request.headers.get("User-Agent", "") or ""
    if choice == "0":
        return False, False
    fully = FULLY_AGENT_RE.search(agent) and not PHONE_AGENT_RE.search(agent) and not IN_APP_BROWSER_RE.search(agent)
    if choice == "1" or SMART_TV_AGENT_RE.search(agent) or fully:
        return True, False
    if PHONE_AGENT_RE.search(agent):
        return False, False
    return True, True


@app.route("/")
def dashboard():
    tv, pc = office_home_layout()
    resp = Response(render_office_home(tv=tv, pc=pc), mimetype="text/html")
    choice = str(request.args.get("tv", "") or "").strip()
    if choice in ["0", "1"]:
        resp.set_cookie("ss_tv", choice, max_age=5 * 365 * 86400, samesite="Lax")
    return resp


@app.route("/tv")
def tv_dashboard():
    return render_office_home(tv=True)


@app.route("/classic")
def classic_dashboard():
    return render_template_string(HTML, **build_dashboard_context())


@app.route("/api/home-cards")
def office_home_cards_api():
    ctx = office_home_context(tv=request_wants_tv())
    ctx["pc"] = request.args.get("pc") == "1"
    return render_template_string(OFFICE_CARDS_HTML, **ctx)


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
        backup_retention_text=BACKUP_RETENTION_TEXT,
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
        feed_movement_rows=context["feed_movement_rows"],
        feed_movement_event_rows=context["feed_movement_event_rows"],
        shed_options=context["shed_options"],
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


@app.route("/feed-stock/bin-fill", methods=["POST"])
def office_feed_stock_bin_fill_view():
    try:
        shed_no = int(request.form.get("shed_no", "").strip()) if request.form.get("shed_no", "").strip() else None
    except Exception:
        shed_no = None
    try:
        kg = round(float(request.form.get("kg", "").strip()), 3)
    except Exception:
        kg = None
    if shed_no not in SHED_NUMBERS and shed_no is not None:
        return redirect_with_next("office_feed_stock_view", False, "Choose a valid shed")
    if kg is None or kg <= 0:
        return redirect_with_next("office_feed_stock_view", False, "Enter a valid bin fill-up KG")
    note = str(request.form.get("note", "") or "").strip()
    ok = append_feed_stock_transaction("bin_fill", kg, note=note, shed_no=shed_no)
    if ok:
        log_event("office", "feed_bin_fill_recorded", "Feed bin fill-up recorded", shed_no=shed_no, detail="%s KG" % fmt_value(kg, "f1"))
    return redirect_with_next("office_feed_stock_view", ok, "Bin fill-up recorded" if ok else "Bin fill-up entry failed")


@app.route("/feed-stock/edit", methods=["POST"])
def office_feed_stock_edit_view():
    tx_id = str(request.form.get("tx_id", "") or "").strip()
    kind = feed_stock_display_kind(request.form.get("kind", ""))
    if kind not in EDITABLE_FEED_STOCK_KINDS:
        return redirect_with_next("office_feed_stock_view", False, "Choose a valid feed activity type")
    try:
        kg = round(float(request.form.get("kg", "").strip()), 3)
    except Exception:
        kg = None
    delta_kg = feed_stock_delta_for_kind(kind, kg)
    if delta_kg is None:
        return redirect_with_next("office_feed_stock_view", False, "Enter a valid feed KG")

    existing = None
    rows = read_all_json_lines("feed_stock.ndjson")
    i = 0
    while i < len(rows):
        rec = rows[i]
        if isinstance(rec, dict) and feed_stock_record_id(rec, i) == tx_id:
            existing = rec
            break
        i += 1
    if not isinstance(existing, dict):
        return redirect_with_next("office_feed_stock_view", False, "Feed activity entry was not found")

    try:
        shed_no = int(request.form.get("shed_no", "").strip()) if request.form.get("shed_no", "").strip() else None
    except Exception:
        shed_no = None
    if shed_no not in SHED_NUMBERS and shed_no is not None:
        return redirect_with_next("office_feed_stock_view", False, "Choose a valid shed")

    crop_id = None
    if kind == "shed_allocation":
        if shed_no not in SHED_NUMBERS:
            return redirect_with_next("office_feed_stock_view", False, "Choose a shed for shed feed")
        existing_shed_no = None
        try:
            existing_shed_no = int(existing.get("shed_no")) if existing.get("shed_no") not in [None, ""] else None
        except Exception:
            existing_shed_no = None
        if existing_shed_no == shed_no and existing.get("crop_id") not in [None, ""]:
            crop_id = existing.get("crop_id")
        else:
            crop_id = get_active_crop_id_for_shed(shed_name_from_number(shed_no))
        if crop_id in [None, ""]:
            return redirect_with_next("office_feed_stock_view", False, "That shed does not have an active crop to apply feed against", shed_no=shed_no)

    note = str(request.form.get("note", "") or "").strip()
    try:
        ts = int(existing.get("ts") or time.time())
    except Exception:
        ts = int(time.time())
    new_rec = {
        "tx_id": feed_stock_record_id(existing, i),
        "ts": ts,
        "kind": kind,
        "delta_kg": delta_kg,
        "shed_no": shed_no,
        "crop_id": None if crop_id in [None, ""] else int(crop_id),
        "source_crop_id": None,
        "note": note,
    }
    ok = rewrite_feed_stock_transaction(tx_id, new_rec)
    if ok:
        log_event("office", "feed_activity_updated", "Feed activity entry updated", shed_no=shed_no, detail="%s KG" % fmt_value(abs(delta_kg), "f1"))
    return redirect_with_next("office_feed_stock_view", ok, "Feed activity updated" if ok else "Feed activity update failed", shed_no=shed_no)


@app.route("/feed-stock/delete", methods=["POST"])
def office_feed_stock_delete_view():
    tx_id = str(request.form.get("tx_id", "") or "").strip()
    ok = rewrite_feed_stock_transaction(tx_id, None)
    if ok:
        log_event("office", "feed_activity_deleted", "Feed activity entry deleted", detail=tx_id)
    return redirect_with_next("office_feed_stock_view", ok, "Feed activity deleted" if ok else "Feed activity entry was not found")


@app.route("/feed-stock/pre-crop/apply", methods=["POST"])
def office_pre_crop_feed_apply_view():
    try:
        shed_no = int(request.form.get("shed_no", "").strip())
    except Exception:
        shed_no = None
    if shed_no not in SHED_NUMBERS:
        return redirect_with_next("office_feed_stock_view", False, "Choose a valid shed")

    data = load_feed_movement_activity()
    rec = clean_feed_movement_activity_rec(data.get(str(int(shed_no)), {}))
    activity_kg = float(rec.get("out_of_crop_feed_out_kg") or 0.0)
    if activity_kg < FEED_MOVEMENT_APPLY_MIN_KG:
        return redirect_with_next("office_feed_stock_view", False, "No out-of-crop feed movement to add", shed_no=shed_no)

    shed_name = shed_name_from_number(shed_no)
    crop_id = get_active_crop_id_for_shed(shed_name)
    if crop_id in [None, ""]:
        return redirect_with_next("office_feed_stock_view", False, "Start the crop before adding out-of-crop feed", shed_no=shed_no)

    note = "Out-of-crop feeder fill from weigh-cell activity"
    ok = append_feed_stock_transaction("shed_allocation", -activity_kg, note=note, shed_no=shed_no, crop_id=crop_id)
    if ok:
        clear_feed_movement_activity(shed_no, crop_id=crop_id, applied_kg=activity_kg, out_of_crop_only=True)
        log_event(
            "office",
            "out_of_crop_feed_applied",
            "Out-of-crop feed movement added to crop",
            shed_no=shed_no,
            detail="%s KG to %s" % (fmt_value(activity_kg, "f1"), fmt_crop_code(crop_id)),
        )
    return redirect_with_next("office_feed_stock_view", ok, "Out-of-crop feed added to crop" if ok else "Out-of-crop feed add failed", shed_no=shed_no)


@app.route("/feed-stock/pre-crop/clear", methods=["POST"])
def office_pre_crop_feed_clear_view():
    try:
        shed_no = int(request.form.get("shed_no", "").strip())
    except Exception:
        shed_no = None
    if shed_no not in SHED_NUMBERS:
        return redirect_with_next("office_feed_stock_view", False, "Choose a valid shed")
    clear_feed_movement_activity(shed_no)
    log_event("office", "feed_movement_cleared", "Feed movement activity cleared", shed_no=shed_no)
    return redirect_with_next("office_feed_stock_view", True, "Feed movement activity cleared", shed_no=shed_no)


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
                    body { margin:0; font-family:Arial, sans-serif; background: #5b5b5b; color: #0d2b4a; }
                    .wrap { max-width:900px; margin:0 auto; padding:30px 16px; }
                    .panel { background: #f5f8fb; border: 1px solid #d5dde6; border-radius:14px; padding:24px; }
                    h1 { margin:0 0 8px 0; }
                    .sub { color: #0d2b4a; }
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
            "last_seen": format_ts_label(meta.get("received_ts")),
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
        "last_seen": format_ts_label(borehole_meta.get("received_ts")),
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
    shed_display_name = shed_display_name_from_number(shed_no)
    active_crop_id = get_active_crop_id_for_shed(shed_name)
    state = load_shed_entries_state()
    entries = ensure_shed_entry_bucket(state, shed_name)
    entry_rows = build_detail_entry_rows(shed_no, entries)
    for r in entry_rows:
        r["placed_display"] = fmt_value(r.get("placed_bird_count"), "i")
        r["live_display"] = fmt_value(r.get("bird_count"), "i")
    boxes, own_boxes = plan_boxes(state, shed_name)
    rank = {k: i for i, k in enumerate(boxes) if k}
    active_rows = sorted([r for r in entry_rows if r.get("crop_active") == 1], key=lambda r: rank.get(str(r["dest_shed"]), 999))
    home_no = shed_no_for_name(shed_name)
    last_visitor_box = len(boxes) - own_boxes
    for r in active_rows:
        idx = rank.get(str(r["dest_shed"]), 0)
        r["is_own"] = entry_home_shed_no(r["dest_shed"]) == home_no
        if len(boxes) == 1:
            r["end_label"] = "Whole shed"
        elif r["is_own"]:
            r["end_label"] = "Rear end"
        elif idx == 0:
            r["end_label"] = "Nearest the door"
        else:
            r["end_label"] = "Pen %d from the door" % (idx + 1)
    idle_rows = [r for r in entry_rows if r.get("crop_active") != 1]

    # Shed plan: the shed divided into the number of pens set for it, door on the right
    # (as seen from the office), the shed's own birds in the rear box(es). Empty boxes
    # can be clicked to start a pen there.
    by_key = {str(r["dest_shed"]): r for r in active_rows}
    own_choices = [r for r in entry_rows if entry_home_shed_no(r["dest_shed"]) == home_no]
    placed_of = {k: max(int(r.get("placed_bird_count") or 0), int(r.get("bird_count") or 0)) for k, r in by_key.items()}
    filled = [v for v in placed_of.values() if v > 0]
    empty_weight = (sum(filled) / len(filled)) if filled else 1
    plan_boxes_view = []
    for i, key in enumerate(boxes):
        r = by_key.get(key) if key else None
        plan_boxes_view.append({
            "weight": (placed_of.get(key) or empty_weight) if r else empty_weight,
            "index": i,
            "pen": {"name": r["dest_shed_label"], "dest_shed": r["dest_shed"], "placed": r["placed_display"], "live": r["live_display"], "own": r["is_own"]} if r else None,
            "own_box": i >= last_visitor_box,
            "label": "by the door" if i == 0 else ("in the rear (own birds)" if i >= last_visitor_box else "in pen %d from the door" % (i + 1)),
            "preselect": own_choices[0]["dest_shed"] if (i >= last_visitor_box and own_choices) else "",
        })
    placed_total = sum(int(r.get("placed_bird_count") or 0) for r in active_rows)
    live_total = sum(int(r.get("bird_count") or 0) for r in active_rows)
    starts = [r.get("placement_epoch") for r in active_rows if r.get("placement_epoch")]

    status_msg = request.args.get("msg", "")
    status_ok = request.args.get("ok", "1") == "1"

    return render_template_string(
        DETAIL_HTML,
        active_rows=active_rows,
        idle_rows=idle_rows,
        own_dests=[r["dest_shed"] for r in entry_rows if entry_home_shed_no(r["dest_shed"]) == home_no],
        total_birds="%s (%s)" % (fmt_value(placed_total, "i"), fmt_value(live_total, "i")) if active_rows else "--",
        crop_started=datetime.fromtimestamp(int(min(starts))).strftime("%d %b %Y %H:%M") if starts else "",
        plan_boxes=plan_boxes_view,
        pen_count=len(boxes),
        shed_name=shed_display_name,
        shed_storage_name=shed_name,
        shed_display_name=shed_display_name,
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
    return redirect(url_for("shed_metric_period_view", shed_no=shed_no, metric="feed", period="daily"))


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
        metric_chart_color = "#d9b86a"
        value_format = lambda v: "%.2f" % float(v)
    else:
        metric_title = "Water"
        metric_key = "water"
        running_key = "running_water"
        metric_table_label = "Water L"
        running_table_label = "Running Water L"
        metric_axis_title = "Water L"
        metric_chart_label = "Water L"
        metric_chart_color = "#5fd0d8"
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

    hourly_rows = get_hourly_history_for_shed(shed_name, max_points=24 * 45 if showing_out_of_crop else 0, crop_id=active_crop_id, include_manual_feed=True)
    bar_epochs, bar_values = hourly_bar_series(hourly_rows, metric_key)
    bars_subtitle = "Out of crop, last 45 days." if showing_out_of_crop else "Current crop %s." % active_crop_code

    feed_page_url = url_for("shed_metric_period_view", shed_no=shed_no, metric="feed", period=period)
    status_msg = request.args.get("msg", "")
    status_ok = request.args.get("ok", "1") == "1"
    shed_feed_stock_label = fmt_value(0, "f1")
    shed_feed_movement = {}
    shed_feed_movement_events = []
    shed_stock_rows = []
    auger_run_rows = []
    auger_runs_backup_name = ""
    auger_runs_backup_at = ""
    auger_runs_api_url = ""
    if metric == "feed":
        stock_context = build_feed_stock_context(shed_no)
        shed_feed_movement = feed_movement_activity_row_for_shed(shed_no)
        shed_feed_movement_events = feed_movement_event_rows(shed_no=shed_no)
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
        shed_feed_movement=shed_feed_movement,
        shed_feed_movement_events=shed_feed_movement_events,
        auger_run_rows=auger_run_rows,
        auger_runs_backup_name=auger_runs_backup_name,
        auger_runs_backup_at=auger_runs_backup_at,
        auger_runs_api_url=auger_runs_api_url,
        shed_stock_rows=shed_stock_rows,
        bar_epochs=bar_epochs,
        bar_values=bar_values,
        bar_unit="kg" if metric == "feed" else "L",
        bars_subtitle=bars_subtitle,
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
        push_shed_state_to_controller_async(shed_no)
        return redirect(url_for("shed_thresholds_view", shed_no=shed_no, ok=1, msg="Tile thresholds saved. Temperature and humidity limits are sent to the shed controller."))
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
        shed_name=shed_display_name_from_number(shed_no),
        active_crop_id=payload["active_crop_id"],
        active_crop_code=payload["active_crop_code"],
        target_rows=payload["target_rows"],
        history_rows=payload["history_rows"],
        mortality_total=fmt_value(payload["mortality_total"], "i"),
        active_birds=fmt_value(payload["active_birds"], "i"),
        mortality_today=datetime.now().strftime("%Y-%m-%d"),
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
        if not valid_entry_shed(dest_shed) or bird_loss <= 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("shed_mortality_view", shed_no=shed_no, ok=0, msg="Invalid mortality entry"))

    note = str(request.form.get("note", "") or "").strip()
    ok, msg = apply_mortality_to_shed(shed_no, dest_shed, bird_loss, note=note, updated_by="dashboard", date_text=request.form.get("mortality_date", ""))
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
    if not valid_entry_shed(dest_shed) or bird_loss <= 0:
        return jsonify({"ok": False, "message": "Invalid mortality entry"}), 400

    ok, msg = apply_mortality_to_shed(shed_no, dest_shed, bird_loss, note=note, updated_by="controller", date_text=payload.get("date", ""))
    if not ok:
        return jsonify({"ok": False, "message": msg}), 400
    return jsonify({
        "ok": True,
        "message": msg,
        "summary": shed_sync_payload(shed_no).get("summary", {}),
    })


@app.route("/shed/<int:shed_no>/entry/<int:dest_shed>/save", methods=["POST"])
@shed_entries_locked
def shed_entry_save(shed_no, dest_shed):
    if shed_no not in SHED_NUMBERS or not valid_entry_shed(dest_shed):
        abort(404)

    raw = request.form.get("placed_bird_count", request.form.get("bird_count", "")).strip()
    try:
        placed_bird_count = int(raw)
        if placed_bird_count < 0:
            raise ValueError()
    except Exception:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Invalid placed bird count"))

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
    had_active_crop = int(rec.get("crop_active", 0) or 0) == 1 and rec.get("crop_id") is not None
    placement_at_raw = request.form.get("placement_at", "")
    placement_epoch = parse_datetime_local_value(placement_at_raw)
    if str(placement_at_raw or "").strip() and placement_epoch is None:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Invalid placement date"))
    if placement_epoch is not None and placement_epoch > now_ts:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Placement date cannot be in the future"))

    entry_mortality = mortality_total_for_entry(shed_name, rec.get("crop_id"), dest_shed) if had_active_crop else 0

    if placed_bird_count == 0:
        rec["bird_count"] = 0
        rec["placed_bird_count"] = 0
        rec["crop_active"] = 0
        rec["placement_epoch"] = None
        rec["crop_id"] = None
        rec["pens"] = []
    else:
        if had_active_crop and placed_bird_count < entry_mortality:
            return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Placed birds cannot be below recorded mortality"))
        rec["placed_bird_count"] = placed_bird_count
        rec["bird_count"] = placed_bird_count - entry_mortality if had_active_crop else placed_bird_count
        rec["pens"] = []
        if placement_epoch is not None:
            rec["placement_epoch"] = placement_epoch

    rec["updated_ts"] = now_ts
    rec["updated_by"] = "dashboard"

    entries[str(dest_shed)] = rec
    if str(dest_shed) in ended_entries:
        del ended_entries[str(dest_shed)]
    save_shed_entries_state(state)
    if placed_bird_count == 0:
        refresh_farm_crop_current_id(state)
        if had_active_crop:
            prev_rec["updated_ts"] = now_ts
            prev_rec["updated_by"] = "dashboard"
            log_crop_event(shed_name, prev_rec, False)
        log_event("office", "entry_cleared", "Entry saved as zero birds", shed_no=shed_no, detail=entry_shed_label(dest_shed))
    else:
        log_event("office", "entry_saved", "Placed bird count saved", shed_no=shed_no, detail="%s = %d" % (entry_shed_label(dest_shed), placed_bird_count))
        if had_active_crop:
            log_crop_event(shed_name, rec, True)
    push_shed_state_to_controller_async(shed_no)
    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg="Entry saved"))


@app.route("/shed/<int:shed_no>/entry/<int:dest_shed>/start", methods=["POST"])
@shed_entries_locked
def shed_entry_start(shed_no, dest_shed):
    if shed_no not in SHED_NUMBERS or not valid_entry_shed(dest_shed):
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
    if rec.get("crop_active") != 1:
        active_pens = [k for k, r in entries.items() if k != str(dest_shed)
                       and clean_entry_record(r)["crop_active"] == 1 and clean_entry_record(r)["bird_count"] > 0]
        if len(active_pens) >= MAX_PENS_PER_SHED:
            return redirect(url_for("shed_detail", shed_no=shed_no, ok=0,
                                    msg="A shed holds %d pens at most. End one first." % MAX_PENS_PER_SHED))

    raw = str(request.form.get("placed_bird_count", request.form.get("bird_count", "")) or "").strip()
    placement_at_raw = request.form.get("placement_at", "")
    if raw != "":
        try:
            placed_bird_count = int(raw)
            if placed_bird_count < 0:
                raise ValueError()
            rec["placed_bird_count"] = placed_bird_count
            rec["bird_count"] = placed_bird_count
            rec["pens"] = []
            rec["updated_ts"] = int(time.time())
            rec["updated_by"] = "dashboard"
        except Exception:
            return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Invalid placed bird count"))

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

    rec["crop_active"] = 1
    if rec.get("placed_bird_count") in [None, ""] or int(rec.get("placed_bird_count") or 0) < bird_count:
        rec["placed_bird_count"] = bird_count
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
    box_raw = str(request.form.get("box", "") or "").strip()
    set_pen_box(state, shed_name, dest_shed, int(box_raw) if box_raw.isdigit() else 0)
    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)
    log_crop_event(shed_name, rec, True)
    log_event("office", "entry_started", "Entry started", shed_no=shed_no, detail="%s Crop %s" % (entry_shed_label(dest_shed), rec.get("crop_id")))
    push_shed_state_to_controller_async(shed_no)
    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg="Entry started"))


@app.route("/shed/<int:shed_no>/pens", methods=["POST"])
@shed_entries_locked
def shed_pen_count(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    try:
        count = int(str(request.form.get("pen_count", "") or "").strip())
        if count < 1 or count > MAX_PENS_PER_SHED:
            raise ValueError()
    except Exception:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Enter between 1 and %d pens" % MAX_PENS_PER_SHED))
    state = load_shed_entries_state()
    shed_name = shed_name_from_number(shed_no)
    saved = set_pen_count(state, shed_name, count)
    save_shed_entries_state(state)
    push_shed_state_to_controller_async(shed_no)
    msg = "Shed set to %d pens" % saved
    if saved != count:
        msg += " (it has %d pens of birds in it)" % saved
    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg=msg))


@app.route("/shed/<int:shed_no>/entry/<int:dest_shed>/end", methods=["POST"])
@shed_entries_locked
def shed_entry_end(shed_no, dest_shed):
    if shed_no not in SHED_NUMBERS or not valid_entry_shed(dest_shed):
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
    log_event("office", "entry_ended", "Entry ended", shed_no=shed_no, detail=entry_shed_label(dest_shed))
    push_shed_state_to_controller_async(shed_no)

    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg="Entry ended and shed cleared"))


@app.route("/shed/<int:shed_no>/entry/<int:dest_shed>/move", methods=["POST"])
@shed_entries_locked
def shed_entry_move(shed_no, dest_shed):
    if shed_no not in SHED_NUMBERS or not valid_entry_shed(dest_shed):
        abort(404)

    dest_home_shed_no = entry_home_shed_no(dest_shed)
    if dest_home_shed_no not in SHED_NUMBERS:
        abort(404)

    if shed_no == dest_home_shed_no:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Cannot move to same shed"))

    state = load_shed_entries_state()

    from_name = shed_name_from_number(shed_no)
    to_name = shed_name_from_number(dest_home_shed_no)

    from_entries = ensure_shed_entry_bucket(state, from_name)
    to_entries = ensure_shed_entry_bucket(state, to_name)
    from_ended_entries = state.get(from_name, {}).get("ended_entries", {})

    raw_rec = from_entries.get(str(dest_shed))
    if not raw_rec:
        return redirect(url_for("shed_detail", shed_no=shed_no, ok=0, msg="Entry not found"))

    try:
        bird_count = int(raw_rec.get("bird_count", 0) or 0)
    except Exception:
        bird_count = 0

    try:
        crop_active = int(raw_rec.get("crop_active", 0) or 0)
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
    raw_dest_rec = dest_rec
    rec = clean_entry_record(raw_rec)
    dest_rec = clean_entry_record(dest_rec)

    try:
        existing = int(dest_rec.get("bird_count", 0) or 0)
    except Exception:
        existing = 0
    source_mortality = mortality_total_for_entry(from_name, rec.get("crop_id"), dest_shed)
    dest_mortality = mortality_total_for_entry(to_name, dest_rec.get("crop_id"), dest_shed)
    source_has_placed = isinstance(raw_rec, dict) and raw_rec.get("placed_bird_count") not in [None, ""]
    dest_has_placed = isinstance(raw_dest_rec, dict) and raw_dest_rec.get("placed_bird_count") not in [None, ""]
    try:
        source_placed = int(rec.get("placed_bird_count") or 0)
    except Exception:
        source_placed = 0
    try:
        existing_placed = int(dest_rec.get("placed_bird_count") or 0)
    except Exception:
        existing_placed = 0
    if not source_has_placed:
        source_placed = bird_count + source_mortality
    if not dest_has_placed:
        existing_placed = existing + dest_mortality
    try:
        dest_active = int(dest_rec.get("crop_active", 0) or 0)
    except Exception:
        dest_active = 0

    same_crop = str(dest_rec.get("crop_id")) == str(rec.get("crop_id"))
    if existing > 0 and dest_active == 1 and not same_crop:
        return redirect(
            url_for(
                "shed_detail",
                shed_no=shed_no,
                ok=0,
                msg="Destination already has active birds for a different crop",
            )
        )

    dest_rec["bird_count"] = existing + bird_count
    dest_rec["placed_bird_count"] = existing_placed + source_placed
    dest_rec["crop_active"] = 1
    source_epoch = rec.get("placement_epoch")
    dest_epoch = dest_rec.get("placement_epoch")
    try:
        if source_epoch not in [None, ""] and (dest_epoch in [None, ""] or int(source_epoch) < int(dest_epoch)):
            dest_rec["placement_epoch"] = int(source_epoch)
    except Exception:
        pass
    if dest_rec.get("placement_epoch") is None:
        dest_rec["placement_epoch"] = source_epoch or int(time.time())
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
    from_ended_entries[str(dest_shed)] = move_ts

    moved_mortality = move_mortality_history_between_sheds(
        from_name,
        to_name,
        dest_shed,
        rec.get("crop_id"),
    )

    save_shed_entries_state(state)
    refresh_farm_crop_current_id(state)
    log_event("office", "entry_moved", "Entry moved between sheds", shed_no=shed_no, detail="%s moved to %s" % (entry_shed_label(dest_shed), shed_display_name_from_number(dest_home_shed_no)))
    if moved_mortality > 0:
        log_event(
            "office",
            "mortality_moved",
            "Mortality moved with active entry",
            shed_no=shed_no,
            detail="Moved %d mortality rows from %s to %s for %s" % (moved_mortality, from_name, to_name, entry_shed_label(dest_shed)),
        )
    push_shed_state_to_controller_async(shed_no)
    push_shed_state_to_controller_async(dest_home_shed_no)
    return redirect(url_for("shed_detail", shed_no=shed_no, ok=1, msg="Entry moved to %s" % shed_display_name_from_number(dest_home_shed_no)))


@app.route("/api/shed/<int:shed_no>/sync", methods=["GET"])
def shed_sync_get(shed_no):
    if shed_no not in SHED_NUMBERS:
        abort(404)
    auth_error = require_controller_token(str(shed_no))
    if auth_error:
        return auth_error
    return jsonify(shed_sync_payload(shed_no))


@shed_entries_locked
def adopt_controller_pen_order(shed_no, incoming):
    # Pens added with the + at an end of the shed on the controller.
    if not isinstance(incoming, dict) or not isinstance(incoming.get("order"), list):
        return
    try:
        controller_ts = int(incoming.get("updated_ts") or 0)
        # Put the controller's time on the office clock, in case the Pi's clock is out.
        if incoming.get("now"):
            controller_ts += int(time.time()) - int(incoming.get("now"))
    except Exception:
        return
    order = [str(k) for k in incoming["order"]]
    state = load_shed_entries_state()
    bucket = state.get(shed_name_from_number(shed_no))
    if not isinstance(bucket, dict) or order == bucket.get("pen_order") or controller_ts <= int(bucket.get("pen_order_ts") or 0) + 2:
        return
    bucket["pen_order"] = order
    bucket["pen_order_ts"] = controller_ts
    bucket["pen_slot_of"] = {}
    save_shed_entries_state(state)


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
    adopt_controller_pen_order(shed_no, payload.get("pen_order"))
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
    try:
        bucket_hours = int(request.args.get("bucket", "6") or 6)
    except Exception:
        bucket_hours = 6
    if bucket_hours == 1:
        # Plain hourly points for the whole crop (shed controller feed / water pages).
        rows = get_hourly_history_for_shed(shed_name, max_points=24 * 70, crop_id=active_crop_id, include_manual_feed=True)
    else:
        rows = get_hourly_history_for_shed(shed_name, max_points=168, crop_id=active_crop_id, include_manual_feed=True)
        rows = aggregate_history_rows_by_hours(rows, bucket_hours=6)

    return jsonify({
        "shed_no": shed_no,
        "shed": shed_name,
        "crop_id": active_crop_id,
        "crop_code": fmt_crop_code(active_crop_id, active_crop.get("placement_epoch")),
        "rows": rows,
    })


@app.route("/api/shed/<int:shed_no>/current-crop/daily", methods=["GET"])
def shed_current_crop_daily_api(shed_no):
    # Completed days of the active crop: feed and water (6am-6am) and the temperature
    # and humidity high and low (midnight to midnight). Foundation for the Trends page.
    if shed_no not in SHED_NUMBERS:
        abort(404)

    shed_name = shed_name_from_number(shed_no)
    active_crop_id = get_active_crop_id_for_shed(shed_name)
    active_crop = active_crop_record_for_shed(shed_name)
    rows = get_daily_history_for_shed(shed_name, max_days=0, crop_id=active_crop_id, include_manual_feed=True)
    return jsonify({
        "shed_no": shed_no,
        "shed": shed_name,
        "crop_id": active_crop_id,
        "crop_code": fmt_crop_code(active_crop_id, active_crop.get("placement_epoch")),
        "placement_epoch": active_crop.get("placement_epoch"),
        "rows": rows,
    })


@app.route("/borehole")
def borehole_detail():
    bh = office_home_context(tv=False).get("borehole", {})
    rows = get_borehole_hourly_history(max_points=24 * 45)
    bar_epochs, water_values = hourly_bar_series(rows, "water")
    return render_template_string(BOREHOLE_DETAIL_HTML, bh=bh, bar_epochs=bar_epochs, water_values=water_values)


@app.route("/borehole/<period>")
def borehole_period_view(period):
    if period not in ["hourly", "daily"]:
        abort(404)

    rows = get_borehole_hourly_history(max_points=24 * 45)
    bar_epochs, water_values = hourly_bar_series(rows, "water")

    return render_template_string(
        BOREHOLE_PERIOD_HTML,
        period=period,
        bar_epochs=bar_epochs,
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
    rows = get_hourly_history_for_shed(shed_name, max_points=0, crop_id=crop_id, include_manual_feed=True)
    crop_start_epoch = None
    if rows:
        try:
            crop_start_epoch = int(rows[0].get("epoch"))
        except Exception:
            crop_start_epoch = None
    bar_epochs, feed_values = hourly_bar_series(rows, "feed")
    _, water_values = hourly_bar_series(rows, "water")

    return render_template_string(
        PERIOD_HTML,
        shed_name=shed_name,
        shed_no=shed_no,
        period=period,
        crop_code=fmt_crop_code(crop_id, crop_start_epoch),
        bar_epochs=bar_epochs,
        feed_values=feed_values,
        water_values=water_values,
    )


if __name__ == "__main__":
    ensure_data_dir()
    with _event_log_lock:
        compact_json_line_log("events.ndjson", EVENT_LOG_MAX_BYTES, EVENT_LOG_KEEP_LINES)
        compact_json_line_log(
            "notification_events.ndjson",
            NOTIFICATION_LOG_MAX_BYTES,
            NOTIFICATION_LOG_KEEP_LINES,
        )
    start_office_background_workers()
    app.run(host="0.0.0.0", port=8090)
