#!/bin/bash
set -eu

URL="${1:-http://127.0.0.1:8091}"

xset s off
xset -dpms
xset s noblank

unclutter -idle 0.5 -root >/dev/null 2>&1 &

if command -v onboard >/dev/null 2>&1; then
  export GTK_IM_MODULE=onboard
  onboard >/dev/null 2>&1 &
fi

chromium-browser \
  --kiosk \
  --incognito \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --check-for-update-interval=31536000 \
  --overscroll-history-navigation=0 \
  "$URL"
