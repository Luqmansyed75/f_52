"""
WebSocketSource — replaces MicListener for Meet mode.

Connects to meet-container ws://host:port/audio
Receives binary frames: [4-byte big-endian seq][640 bytes PCM 16kHz mono int16]
Strips header, writes raw PCM into RingBuffer in 512-byte chunks
(matching MicListener's chunk size so Segmenter/VAD see identical frame sizes)

Also handles:
- Control frames (JSON): session_started, heartbeat, meeting_ended
- Sends heartbeat back every 5s
- Sends bot_state_changed when speaking state changes
- Reconnects automatically on disconnect
"""

import asyncio
import json
import logging
import threading
import time
from typing import Callable, Optional

import websockets

logger = logging.getLogger("websocket_source")

# Must match MicListener chunk size so Segmenter/VAD see identical frame sizes
MIC_CHUNK_BYTES = 1024

# meet-container sends 640-byte PCM frames (20ms @ 16kHz mono int16)
WS_FRAME_PCM_BYTES = 640

HEARTBEAT_INTERVAL = 5.0
RECONNECT_DELAY = 2.0
MAX_RECONNECT_DELAY = 30.0


class WebSocketSource:
    """
    Drop-in replacement for MicListener.

    Usage:
        source = WebSocketSource(
            uri="ws://meet-container:5001/audio",
            ring_buffer=ring_buffer,
            on_session_started=callback,   # optional
            on_meeting_ended=callback,     # optional
        )
        source.start_stream()
        ...
        source.stop_stream()

    To signal bot speaking state (suppresses capture echo gate):
        source.set_speaking(True)
        source.set_speaking(False)
    """

    def __init__(
        self,
        uri: str,
        ring_buffer,
        on_session_started: Optional[Callable[[str], None]] = None,
        on_meeting_ended: Optional[Callable[[str], None]] = None,
    ):
        self.uri = uri
        self.ring_buffer = ring_buffer
        self.on_session_started = on_session_started
        self.on_meeting_ended = on_meeting_ended

        self._running = False
        self._speaking = False
        self._session_id = ""
        self._ws = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        # Stats
        self._frames_received = 0
        self._frames_written = 0
        self._reconnect_count = 0
        self._connect_time = 0.0

    # ------------------------------------------------------------------
    # Public API — mirrors MicListener
    # ------------------------------------------------------------------

    def start_stream(self) -> None:
        """Start the WebSocket receive loop in a background thread."""
        if self._running:
            logger.warning("WebSocketSource.start_stream() called while already running.")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="websocket-source",
        )
        self._thread.start()
        logger.info(f"WebSocketSource started. uri={self.uri}")

    def stop_stream(self) -> None:
        """Stop the receive loop and close the WebSocket."""
        self._running = False

        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        elapsed = time.monotonic() - self._connect_time if self._connect_time else 0
        logger.info(
            f"WebSocketSource stopped after {elapsed:.1f}s. "
            f"received={self._frames_received} "
            f"written={self._frames_written} "
            f"reconnects={self._reconnect_count}"
        )

    def set_speaking(self, speaking: bool) -> None:
        """
        Signal bot speaking state to meet-container.
        When speaking=True, meet-container suppresses sending captured audio
        (echo gate). We also send a control frame to meet-container.
        """
        if speaking == self._speaking:
            return

        self._speaking = speaking
        state = "SPEAKING" if speaking else "LISTENING"
        logger.info(f"Bot state → {state}")

        if self._loop and self._ws and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._send_control({"type": "bot_state_changed", "state": state}),
                self._loop,
            )

    def session_id(self) -> str:
        return self._session_id

    # ------------------------------------------------------------------
    # Internal — asyncio loop in thread
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_loop())
        except Exception as e:
            logger.error(f"WebSocketSource loop crashed: {e}", exc_info=True)
        finally:
            self._loop.close()

    async def _connect_loop(self) -> None:
        delay = RECONNECT_DELAY

        while self._running:
            try:
                logger.info(f"Connecting to {self.uri} ...")
                async with websockets.connect(
                    self.uri,
                    max_size=None,
                    ping_interval=None,   # we handle heartbeats manually
                    ping_timeout=None,
                ) as ws:
                    self._ws = ws
                    self._connect_time = time.monotonic()
                    delay = RECONNECT_DELAY  # reset backoff on success
                    logger.info("WebSocket connected.")

                    await self._session_loop(ws)

            except websockets.ConnectionClosed as e:
                logger.warning(f"WebSocket closed: {e}")
            except OSError as e:
                logger.warning(f"WebSocket connection failed: {e}")
            except Exception as e:
                logger.error(f"WebSocket error: {e}", exc_info=True)
            finally:
                self._ws = None

            if not self._running:
                break

            self._reconnect_count += 1
            logger.info(f"Reconnecting in {delay}s ... (attempt {self._reconnect_count})")
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_RECONNECT_DELAY)

    async def _session_loop(self, ws) -> None:
        """
        Run heartbeat sender and frame receiver concurrently.
        Returns when either task finishes (disconnect, stop, error).
        """
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
        receive_task = asyncio.create_task(self._receive_loop(ws))

        try:
            done, pending = await asyncio.wait(
                [heartbeat_task, receive_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        except asyncio.CancelledError:
            heartbeat_task.cancel()
            receive_task.cancel()

    async def _receive_loop(self, ws) -> None:
        """Receive frames from meet-container and route to RingBuffer."""
        buf = bytearray()

        async for message in ws:
            if not self._running:
                break

            # --- Binary frame: PCM audio ---
            if isinstance(message, bytes):
                if len(message) < 4:
                    logger.warning(f"Short binary frame: {len(message)} bytes, skipping.")
                    continue

                # Strip 4-byte sequence header
                pcm = message[4:]
                self._frames_received += 1

                # Flush into RingBuffer in MIC_CHUNK_BYTES chunks
                # This makes Segmenter/VAD see identical frame sizes as MicListener
                buf.extend(pcm)
                while len(buf) >= MIC_CHUNK_BYTES:
                    chunk = bytes(buf[:MIC_CHUNK_BYTES])
                    buf = buf[MIC_CHUNK_BYTES:]
                    self.ring_buffer.write(chunk)
                    self._frames_written += 1

                continue

            # --- Control frame: JSON text ---
            if isinstance(message, str):
                await self._handle_control(message)
                continue

    async def _handle_control(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Non-JSON control frame: {raw[:80]}")
            return

        msg_type = msg.get("type", "")

        if msg_type == "session_started":
            self._session_id = msg.get("session_id", "")
            logger.info(f"session_started. session_id={self._session_id}")
            if self.on_session_started:
                self.on_session_started(self._session_id)

        elif msg_type == "heartbeat":
            # meet-container is alive — nothing to do, we send our own heartbeat
            pass

        elif msg_type == "meeting_ended":
            reason = msg.get("reason", "unknown")
            logger.info(f"meeting_ended. reason={reason}")
            if self.on_meeting_ended:
                self.on_meeting_ended(reason)

        elif msg_type == "bot_state_changed":
            # echo from meet-container confirming our state change
            pass

        else:
            logger.debug(f"Unhandled control frame: {msg_type}")

    async def _heartbeat_loop(self, ws) -> None:
        """Send heartbeat to meet-container every 5s."""
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if not self._running:
                break
            await self._send_control({"type": "heartbeat", "ts": time.time()})

    async def _send_control(self, msg: dict) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps(msg))
        except Exception as e:
            logger.warning(f"_send_control failed: {e}")