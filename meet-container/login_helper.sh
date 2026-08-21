#!/bin/bash
set -e

echo "[login-helper] Cleaning up stale locks..."
rm -f /chrome-profile/Singleton* /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true

echo "[login-helper] Starting Xvfb display :99..."
Xvfb :99 -screen 0 1280x800x24 -ac &
export DISPLAY=:99
sleep 1

echo "[login-helper] Starting Window Manager..."
fluxbox &
sleep 1

echo "[login-helper] Starting x11vnc..."
x11vnc -display :99 -nopw -listen 127.0.0.1 -xkb -forever -shared -bg

echo "[login-helper] Starting noVNC web server on 0.0.0.0:6080..."
# Ensure index.html exists for root URL navigation
ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html 2>/dev/null || true
websockify --web /usr/share/novnc 0.0.0.0:6080 127.0.0.1:5900 &
sleep 1

echo "=========================================================="
echo "  ✅ Login Server is LIVE!"
echo "  Open this link in your Windows browser:"
echo "  👉 http://localhost:6080/vnc.html"
echo "=========================================================="

exec google-chrome-stable \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --user-data-dir=/chrome-profile \
    --no-first-run \
    --disable-default-apps \
    "https://accounts.google.com/signin"