#!/bin/bash
set -e

echo "[entrypoint] Cleaning up stale locks and processes..."
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
rm -f /chrome-profile/Singleton* /chrome-profile/.org.chromium.Chromium.* 2>/dev/null || true
rm -rf /root/.config/pulse /var/run/pulse /tmp/pulse-* 2>/dev/null || true
pulseaudio --kill 2>/dev/null || true
sleep 1

echo "[entrypoint] Starting Xvfb on :99..."
Xvfb :99 -screen 0 1280x800x24 -ac &
export DISPLAY=:99
sleep 2

echo "[entrypoint] Starting PulseAudio..."
mkdir -p /root/.config/pulse
pulseaudio \
    --exit-idle-time=-1 \
    --log-target=stderr \
    --log-level=notice \
    --daemonize=false &
sleep 3

echo "[entrypoint] Loading PulseAudio modules..."
pactl load-module module-null-sink sink_name=meet_out sink_properties=device.description=meet_out format=s16le rate=48000 channels=2 >/dev/null || true
pactl load-module module-null-sink sink_name=bot_in sink_properties=device.description=bot_in format=s16le rate=48000 channels=2 >/dev/null || true
pactl load-module module-virtual-source source_name=meet_mic master=bot_in.monitor source_properties=device.description=meet_mic >/dev/null || true

echo "[entrypoint] Setting defaults..."
pactl set-default-sink meet_out || true
pactl set-default-source meet_mic || true

echo "[entrypoint] Verifying PulseAudio devices..."
pactl list sinks short
pactl list sources short

echo "[entrypoint] PulseAudio defaults:"
pactl info | grep -E "Default Sink|Default Source" || true

echo "[entrypoint] Starting meet_service using virtual environment..."
# Explicitly use /opt/venv/bin/python3 to avoid system python conflicts
exec /opt/venv/bin/python3 /app/meet_service.py