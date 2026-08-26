"""
WebSocketSource — replaces MicListener for Meet mode.

Connects to meet-container ws://host:port/audio
Receives binary frames: [4-byte big-endian seq][640 bytes PCM 16kHz mono int16]
Strips header, writes raw PCM into RingBuffer in 1024-byte chunks
(matching MicListener's chunk size so Segmenter/VAD see identical frame sizes)

Hard-Boundary Reconnection & Graceful Shutdown:
- Flushes RingBuffer on disconnect and reconnect
- Discards stale staging audio fragments
- Dispatches on_reconnect and on_disconnect callbacks
- Clean asyncio teardown with zero runtime tracebacks
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

# meet-container sends 640-byte PCM frames + 4-byte header = 644 bytes total
WS_PCM_BYTES = 640
WS_MSG_BYTES = 644

HEARTBEAT_INTERVAL = 5.0
RECONNECT_DELAY = 2.0
MAX_RECONNECT_DELAY = 30.0


class WebSocketSource:
    """
    Drop-in replacement for MicListener with hard-boundary reconnect handling
    and graceful shutdown lifecycle.
    """

    def __init__(
        self,
        uri: str,
        ring_buffer,
        on_session_started: Optional[Callable[[str], None]] = None,
        on_meeting_ended: Optional[Callable[[str], None]] = None,
        on_reconnect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
    ):
        self.uri = uri
        self.ring_buffer = ring_buffer
        self.on_session_started = on_session_started
        self.on_meeting_ended = on_meeting_ended
        self.on_reconnect = on_reconnect
        self.on_disconnect = on_disconnect

        self._running = False
        self._speaking = False
        self._session_id = ""
        self._ws = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        # Internal staging buffer for slicing into 1024-byte chunks
        self._staging_buf = bytearray()
        self._buf_lock = threading.Lock()

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
        """Stop the receive loop and close the WebSocket cleanly."""
        self._running = False

        if self._loop and self._loop.is_running():
            # Close active websocket cleanly inside loop before shutting down
            if self._ws:
                try:
                    asyncio.run_coroutine_threadsafe(self._close_ws(), self._loop)
                except Exception:
                    pass

        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

        self._flush_boundary("shutdown")

        elapsed = time.monotonic() - self._connect_time if self._connect_time else 0
        logger.info(
            f"WebSocketSource stopped after {elapsed:.1f}s. "
            f"received={self._frames_received} "
            f"written={self._frames_written} "
            f"reconnects={self._reconnect_count}"
        )

    async def _close_ws(self) -> None:
        """Helper to close websocket gracefully."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

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
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send_control({"type": "bot_state_changed", "state": state}),
                    self._loop,
                )
            except Exception:
                pass

    def session_id(self) -> str:
        return self._session_id

    # ------------------------------------------------------------------
    # Reconnect Hard Boundary Management
    # ------------------------------------------------------------------

    def _flush_boundary(self, reason: str) -> None:
        """
        Hard boundary execution: flushes local staging buffer and RingBuffer
        so audio before the disconnect/event never corrupts post-reconnect speech.
        """
        with self._buf_lock:
            self._staging_buf.clear()

        if hasattr(self.ring_buffer, "clear"):
            try:
                self.ring_buffer.clear()
            except Exception as e:
                logger.warning(f"Error clearing RingBuffer: {e}")
        elif hasattr(self.ring_buffer, "reset"):
            try:
                self.ring_buffer.reset()
            except Exception as e:
                logger.warning(f"Error resetting RingBuffer: {e}")

        logger.info(f"Hard boundary flush executed (reason: {reason}). Stale audio discarded.")

    # ------------------------------------------------------------------
    # Internal — asyncio loop in thread
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_loop())
        except (asyncio.CancelledError, RuntimeError):
            pass
        except Exception as e:
            if self._running:
                logger.error(f"WebSocketSource loop crashed: {e}", exc_info=True)
        finally:
            try:
                # Cancel pending tasks cleanly
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            self._loop.close()

    async def _connect_loop(self) -> None:
        delay = RECONNECT_DELAY
        is_initial_connect = True

        while self._running:
            try:
                logger.info(f"Connecting to {self.uri} ...")
                async with websockets.connect(
                    self.uri,
                    max_size=None,
                    ping_interval=None,
                    ping_timeout=None,
                ) as ws:
                    self._ws = ws
                    self._connect_time = time.monotonic()
                    delay = RECONNECT_DELAY

                    if not is_initial_connect:
                        logger.info("Reconnected to WebSocket audio stream. Applying hard boundary reset.")
                        self._flush_boundary("reconnected")
                        if self.on_reconnect:
                            try:
                                self.on_reconnect()
                            except Exception as e:
                                logger.exception(f"Error in on_reconnect callback: {e}")
                    else:
                        is_initial_connect = False

                    logger.info("WebSocket connected successfully.")
                    await self._session_loop(ws)

            except websockets.ConnectionClosed:
                if self._running:
                    logger.warning("WebSocket connection closed by remote.")
            except OSError as e:
                if self._running:
                    logger.warning(f"WebSocket connection failed: {e}")
            except Exception as e:
                if self._running:
                    logger.error(f"WebSocket error: {e}", exc_info=True)
            finally:
                self._ws = None
                if self._running:
                    self._flush_boundary("disconnected")
                    if self.on_disconnect:
                        try:
                            self.on_disconnect()
                        except Exception as e:
                            logger.exception(f"Error in on_disconnect callback: {e}")

            if not self._running:
                break

            self._reconnect_count += 1
            logger.info(f"Reconnecting in {delay}s ... (attempt {self._reconnect_count})")
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
            delay = min(delay * 2, MAX_RECONNECT_DELAY)

    async def _session_loop(self, ws) -> None:
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
        try:
            async for message in ws:
                if not self._running:
                    break

                if isinstance(message, bytes):
                    msg_len = len(message)
                    if msg_len < 4:
                        continue

                    clean_pcm = bytearray()
                    if msg_len >= WS_MSG_BYTES and msg_len % WS_MSG_BYTES == 0:
                        idx = 0
                        while idx + WS_MSG_BYTES <= msg_len:
                            clean_pcm.extend(message[idx + 4 : idx + WS_MSG_BYTES])
                            idx += WS_MSG_BYTES
                    else:
                        clean_pcm.extend(message[4:])

                    self._frames_received += 1

                    with self._buf_lock:
                        self._staging_buf.extend(clean_pcm)
                        while len(self._staging_buf) >= MIC_CHUNK_BYTES:
                            chunk = bytes(self._staging_buf[:MIC_CHUNK_BYTES])
                            self._staging_buf = self._staging_buf[MIC_CHUNK_BYTES:]
                            self.ring_buffer.write(chunk)
                            self._frames_written += 1
                    continue

                if isinstance(message, str):
                    await self._handle_control(message)
                    continue
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass

    async def _handle_control(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type", "")
        if msg_type == "session_started":
            self._session_id = msg.get("session_id", "")
            logger.info(f"session_started received. session_id={self._session_id}")
            if self.on_session_started:
                self.on_session_started(self._session_id)
        elif msg_type == "meeting_ended":
            reason = msg.get("reason", "unknown")
            logger.info(f"meeting_ended received. reason={reason}")
            if self.on_meeting_ended:
                self.on_meeting_ended(reason)

    async def _heartbeat_loop(self, ws) -> None:
        while self._running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
            except asyncio.CancelledError:
                break
            if not self._running:
                break
            await self._send_control({"type": "heartbeat", "ts": time.time()})

    async def _send_control(self, msg: dict) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps(msg))
        except Exception:
            pass