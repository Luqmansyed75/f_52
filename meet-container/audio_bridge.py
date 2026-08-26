"""
AudioBridge — PulseAudio ↔ WebSocket

Capture path (meeting → backend):
    parecord from meet_out.monitor
      → chunk into 20ms / 640-byte frames
      → prepend 4-byte big-endian sequence number
      → call ws_sender(frame)
    Suppressed when bot is SPEAKING (echo gate)

Playback path (backend → meeting):
    receive binary frames over WebSocket
      → strip 4-byte sequence header per 644-byte frame
      → write clean PCM into bot_in via pacat
"""

import asyncio
import logging
import struct
import time
from typing import Callable, Optional

logger = logging.getLogger("audio_bridge")

FRAME_BYTES = 640        # 20ms @ 16kHz mono int16
MSG_BYTES = 644          # 4-byte header + 640-byte PCM
RATE = 16000
CHANNELS = 1
FORMAT = "s16le"
CAPTURE_DEVICE = "meet_out.monitor"
PLAYBACK_DEVICE = "bot_in"


class AudioBridge:
    def __init__(
        self,
        capture_device: str = CAPTURE_DEVICE,
        playback_device: str = PLAYBACK_DEVICE,
        ws_sender: Optional[Callable] = None,
    ):
        self.capture_device = capture_device
        self.playback_device = playback_device
        self.ws_sender = ws_sender

        self._capture_proc: Optional[asyncio.subprocess.Process] = None
        self._playback_proc: Optional[asyncio.subprocess.Process] = None
        self._capture_task: Optional[asyncio.Task] = None
        self._seq: int = 0
        self._speaking: bool = False
        self._running: bool = False

        self._frames_sent: int = 0
        self._frames_suppressed: int = 0
        self._frames_played: int = 0
        self._start_time: float = 0.0

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._start_time = time.monotonic()
        self._seq = 0
        self._frames_sent = 0
        self._frames_suppressed = 0
        self._frames_played = 0

        await self._start_playback_proc()
        await self._start_capture_proc()
        self._capture_task = asyncio.create_task(self._capture_loop())
        logger.info(f"AudioBridge started. capture={self.capture_device} playback={self.playback_device}")

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False

        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass
            self._capture_task = None

        await self._stop_proc(self._capture_proc, "capture")
        self._capture_proc = None

        await self._stop_proc(self._playback_proc, "playback")
        self._playback_proc = None

        elapsed = time.monotonic() - self._start_time
        logger.info(f"AudioBridge stopped after {elapsed:.1f}s. sent={self._frames_sent} played={self._frames_played}")

    def set_speaking(self, speaking: bool) -> None:
        if speaking != self._speaking:
            logger.info(f"Echo gate: speaking={speaking}")
        self._speaking = speaking

    async def play(self, data: bytes) -> None:
        """Extract clean PCM from WebSocket payloads, stripping sequence headers from ALL concatenated frames."""
        if not self._running:
            return

        proc = self._playback_proc
        if proc is None or proc.stdin is None:
            return

        clean_pcm = bytearray()
        idx = 0

        # Unpack each 644-byte frame [4-byte seq header][640-byte PCM]
        while idx + MSG_BYTES <= len(data):
            clean_pcm.extend(data[idx + 4 : idx + MSG_BYTES])
            idx += MSG_BYTES

        # Fallback for raw unheadered PCM (exact multiples of 640 bytes)
        if idx == 0 and len(data) % FRAME_BYTES == 0:
            clean_pcm.extend(data)

        if not clean_pcm:
            return

        try:
            proc.stdin.write(bytes(clean_pcm))
            await proc.stdin.drain()
            self._frames_played += len(clean_pcm) // FRAME_BYTES
        except (BrokenPipeError, ConnectionResetError):
            await self._restart_playback_proc()
        except Exception as e:
            logger.warning(f"play() error: {e}")

    async def _start_capture_proc(self) -> None:
        self._capture_proc = await asyncio.create_subprocess_exec(
            "parecord",
            f"--device={self.capture_device}",
            "--raw",
            f"--format={FORMAT}",
            f"--rate={RATE}",
            f"--channels={CHANNELS}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _start_playback_proc(self) -> None:
        self._playback_proc = await asyncio.create_subprocess_exec(
            "pacat",
            f"--device={self.playback_device}",
            "--raw",
            f"--format={FORMAT}",
            f"--rate={RATE}",
            f"--channels={CHANNELS}",
            "--latency-msec=150",
            "--process-time-msec=20",
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _restart_playback_proc(self) -> None:
        await self._stop_proc(self._playback_proc, "playback")
        self._playback_proc = None
        if self._running:
            await self._start_playback_proc()

    async def _stop_proc(self, proc: Optional[asyncio.subprocess.Process], name: str) -> None:
        if proc is None:
            return
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        except Exception:
            pass

    async def _capture_loop(self) -> None:
        buf = bytearray()
        try:
            while self._running:
                proc = self._capture_proc
                if proc is None or proc.stdout is None:
                    await asyncio.sleep(0.1)
                    continue

                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(FRAME_BYTES * 4), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if not chunk:
                    if self._running:
                        await self._stop_proc(self._capture_proc, "capture")
                        await self._start_capture_proc()
                    continue

                buf.extend(chunk)

                while len(buf) >= FRAME_BYTES:
                    frame_pcm = bytes(buf[:FRAME_BYTES])
                    buf = buf[FRAME_BYTES:]

                    if self._speaking:
                        self._frames_suppressed += 1
                        self._seq += 1
                        continue

                    header = struct.pack(">I", self._seq)
                    self._seq += 1

                    if self.ws_sender:
                        try:
                            await self.ws_sender(header + frame_pcm)
                            self._frames_sent += 1
                        except Exception:
                            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Capture loop error: {e}", exc_info=True)