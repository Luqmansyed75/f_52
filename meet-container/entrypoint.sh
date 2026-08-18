#!/bin/bash
set -euo pipefail

cleanup() {
    echo "[entrypoint] Cleaning up..."
    if [[ -n "${PA_PID:-}" ]]; then
        kill "${PA_PID}" 2>/dev/null || true
        wait "${PA_PID}" 2>/dev/null || true
    fi
    if [[ -n "${XVFB_PID:-}" ]]; then
        kill "${XVFB_PID}" 2>/dev/null || true
        wait "${XVFB_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "[entrypoint] Starting Xvfb on :99..."
Xvfb :99 -screen 0 1280x720x24 -ac &
XVFB_PID=$!
sleep 1

echo "[entrypoint] Starting PulseAudio..."
mkdir -p /root/.config/pulse
pulseaudio \
    --exit-idle-time=-1 \
    --log-target=stderr \
    --log-level=notice \
    --daemonize=false &
PA_PID=$!
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

echo "[entrypoint] Starting meet_service..."
exec python3 /app/meet_service.py