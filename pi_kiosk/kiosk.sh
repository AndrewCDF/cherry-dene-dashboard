#!/bin/bash
set -u

URL="${1:-http://127.0.0.1:8091}"

sleep 5

if command -v xset >/dev/null 2>&1; then
  xset s off || true
  xset -dpms || true
  xset s noblank || true
fi

if command -v unclutter >/dev/null 2>&1; then
  unclutter -idle 0.5 >/dev/null 2>&1 &
fi

if command -v onboard >/dev/null 2>&1; then
  export GTK_IM_MODULE=onboard
fi

if command -v chromium >/dev/null 2>&1; then
  BROWSER_BIN="chromium"
elif command -v chromium-browser >/dev/null 2>&1; then
  BROWSER_BIN="chromium-browser"
else
  echo "No Chromium browser binary found." >&2
  exit 1
fi

"$BROWSER_BIN" \
  --kiosk \
  --incognito \
  --password-store=basic \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --check-for-update-interval=31536000 \
  --overscroll-history-navigation=0 \
  "$URL"
