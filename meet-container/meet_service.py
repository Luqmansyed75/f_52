"""
meet-container — FastAPI service

HTTP endpoints:
    POST /join      { "meet_url": "https://meet.google.com/xxx" }
    POST /leave
    GET  /status

WebSocket:
    /audio
    Binary frames:  [4-byte big-endian seq][640 bytes PCM 16kHz mono int16]
    Control frames: JSON strings
        <- {"type": "session_started", "session_id": "..."}
        <- {"type": "bot_state_changed", "state": "LISTENING"|"THINKING"|"SPEAKING"}
        <- {"type": "heartbeat", "ts": 1234567890.123}
        -> {"type": "stream_stopped"}   (backend signals it's done speaking)
"""

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from enum import Enum

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from audio_bridge import AudioBridge
from meet_automation import MeetAutomation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("meet_service")


class JoinRequest(BaseModel):
    meet_url: str


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class BotLifecycle(str, Enum):
    IDLE = "IDLE"
    JOINING = "JOINING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    LEAVING = "LEAVING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class BotConvState(str, Enum):
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"


# ---------------------------------------------------------------------------
# Shared service state
# ---------------------------------------------------------------------------

class ServiceState:
    def __init__(self):
        self.lifecycle: BotLifecycle = BotLifecycle.IDLE
        self.conv_state: BotConvState = BotConvState.LISTENING
        self.session_id: str = ""
        self.meet_url: str = ""
        self.ws_client: WebSocket | None = None
        self.bridge: AudioBridge | None = None
        self.automation: MeetAutomation | None = None
        self.heartbeat_task: asyncio.Task | None = None
        self.last_backend_heartbeat: float = 0.0
        self.lock: asyncio.Lock = asyncio.Lock()

    def to_dict(self) -> dict:
        return {
            "lifecycle": self.lifecycle.value,
            "conv_state": self.conv_state.value,
            "session_id": self.session_id,
            "meet_url": self.meet_url,
            "backend_connected": self.ws_client is not None,
            "last_backend_heartbeat": self.last_backend_heartbeat,
        }


state = ServiceState()


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("meet_service starting up")
    state.automation = MeetAutomation()
    await state.automation.start()
    yield
    logger.info("meet_service shutting down")
    await _do_leave(reason="shutdown")
    if state.automation:
        await state.automation.stop()


app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _send_control(ws: WebSocket, msg: dict) -> None:
    try:
        await ws.send_text(json.dumps(msg))
    except Exception as e:
        logger.warning(f"_send_control failed: {e}")


async def _do_leave(reason: str = "requested") -> None:
    async with state.lock:
        if state.lifecycle in (BotLifecycle.IDLE, BotLifecycle.STOPPED):
            return

        logger.info(f"Leaving meeting. reason={reason}")
        state.lifecycle = BotLifecycle.LEAVING

        if state.bridge:
            await state.bridge.stop()
            state.bridge = None

        if state.automation:
            await state.automation.leave()

        if state.heartbeat_task:
            state.heartbeat_task.cancel()
            try:
                await state.heartbeat_task
            except asyncio.CancelledError:
                pass
            state.heartbeat_task = None

        if state.ws_client:
            try:
                await _send_control(
                    state.ws_client,
                    {"type": "meeting_ended", "reason": reason}
                )
                await state.ws_client.close()
            except Exception:
                pass
            state.ws_client = None

        state.session_id = ""
        state.meet_url = ""
        state.lifecycle = BotLifecycle.IDLE
        state.conv_state = BotConvState.LISTENING
        logger.info("Left meeting cleanly.")


async def _heartbeat_loop() -> None:
    """Send heartbeat to backend every 5s.
    If backend has not responded for 30s while CONNECTED → auto-leave."""
    HEARTBEAT_INTERVAL = 5.0
    BACKEND_TIMEOUT = 30.0

    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)

            ws = state.ws_client
            if ws is None:
                continue

            await _send_control(
                ws,
                {
                    "type": "heartbeat",
                    "ts": time.time(),
                    "lifecycle": state.lifecycle.value,
                    "conv_state": state.conv_state.value,
                },
            )

            if (
                state.lifecycle == BotLifecycle.CONNECTED
                and state.last_backend_heartbeat > 0
                and (time.time() - state.last_backend_heartbeat) > BACKEND_TIMEOUT
            ):
                logger.error(
                    f"Backend heartbeat lost for >{BACKEND_TIMEOUT}s. Auto-leaving."
                )
                asyncio.create_task(_do_leave(reason="backend_timeout"))
                break

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Heartbeat loop error: {e}")


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/status")
async def status():
    return JSONResponse(state.to_dict())


@app.post("/join")
async def join(body: JoinRequest):
    meet_url = body.meet_url.strip()
    if not meet_url:
        return JSONResponse({"error": "meet_url required"}, status_code=400)

    async with state.lock:
        if state.lifecycle not in (BotLifecycle.IDLE, BotLifecycle.STOPPED):
            return JSONResponse(
                {"error": f"Cannot join — current state: {state.lifecycle.value}"},
                status_code=409,
            )

        state.lifecycle = BotLifecycle.JOINING
        state.meet_url = meet_url
        state.session_id = str(uuid.uuid4())

    logger.info(f"Joining: {meet_url}  session={state.session_id}")

    try:
        await state.automation.join(meet_url)
        async with state.lock:
            state.lifecycle = BotLifecycle.CONNECTED
        logger.info("Joined meeting successfully.")
        return JSONResponse(
            {
                "ok": True,
                "session_id": state.session_id,
                "lifecycle": state.lifecycle.value,
            }
        )
    except Exception as e:
        logger.error(f"Join failed: {e}")
        async with state.lock:
            state.lifecycle = BotLifecycle.FAILED
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/leave")
async def leave():
    await _do_leave(reason="requested")
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# WebSocket /audio
# ---------------------------------------------------------------------------

@app.websocket("/audio")
async def audio_ws(websocket: WebSocket):
    await websocket.accept()
    logger.info("Backend WebSocket connected.")

    async with state.lock:
        if state.ws_client is not None:
            logger.warning("Replacing existing WebSocket client.")
            try:
                await state.ws_client.close()
            except Exception:
                pass

        state.ws_client = websocket
        state.last_backend_heartbeat = time.time()

        if state.bridge is None:
            state.bridge = AudioBridge(
                capture_device="meet_out.monitor",
                playback_device="bot_in",
                ws_sender=_ws_send_binary,
            )
            await state.bridge.start()

        if state.heartbeat_task is None or state.heartbeat_task.done():
            state.heartbeat_task = asyncio.create_task(_heartbeat_loop())

    session_id = state.session_id or str(uuid.uuid4())
    await _send_control(
        websocket,
        {
            "type": "session_started",
            "session_id": session_id,
            "ts": time.time(),
        },
    )
    logger.info(f"Sent session_started. session_id={session_id}")

    try:
        while True:
            data = await websocket.receive()

            if data.get("type") == "websocket.disconnect":
                logger.info("WebSocket disconnect message received.")
                break

            if "bytes" in data and data["bytes"] is not None:
                await _handle_incoming(websocket, data["bytes"])
                continue

            if "text" in data and data["text"] is not None:
                await _handle_incoming(websocket, data["text"])
                continue

    except Exception as e:
        logger.warning(f"WebSocket handler error: {e}")
    finally:
        async with state.lock:
            if state.ws_client is websocket:
                state.ws_client = None
                if state.bridge:
                    await state.bridge.stop()
                    state.bridge = None
        logger.info("WebSocket handler cleaned up.")


async def _ws_send_binary(data: bytes) -> None:
    ws = state.ws_client
    if ws is None:
        return
    try:
        await ws.send_bytes(data)
    except Exception as e:
        logger.warning(f"_ws_send_binary failed: {e}")


async def _handle_incoming(websocket: WebSocket, message) -> None:
    # --- Binary frame: TTS audio from backend → play into bot_in ---
    if isinstance(message, bytes):
        if len(message) < 4:
            logger.warning(f"Short binary frame: {len(message)} bytes, ignoring.")
            return

        pcm = message[4:]

        if state.bridge:
            await state.bridge.play(pcm)
        return

    # --- Control frame (JSON text) ---
    if isinstance(message, str):
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(f"Non-JSON text frame: {message[:80]}")
            return

        msg_type = msg.get("type", "")

        if msg_type == "heartbeat":
            state.last_backend_heartbeat = time.time()

        elif msg_type == "bot_state_changed":
            new_state = msg.get("state", "")
            try:
                state.conv_state = BotConvState(new_state)
                logger.info(f"Conv state → {state.conv_state.value}")
                if state.bridge:
                    state.bridge.set_speaking(state.conv_state == BotConvState.SPEAKING)
            except ValueError:
                logger.warning(f"Unknown conv state: {new_state}")

        elif msg_type == "stream_stopped":
            state.conv_state = BotConvState.LISTENING
            logger.info("Backend stream_stopped → back to LISTENING")
            if state.bridge:
                state.bridge.set_speaking(False)

        else:
            logger.debug(f"Unhandled control frame type: {msg_type}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("MEET_SERVICE_PORT", "5001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")