import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from audio_bridge import AudioBridge
from meet_automation import MeetAutomation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("meet_service")

HEARTBEAT_TIMEOUT_SECONDS = 30.0


class JoinRequest(BaseModel):
    meet_url: str


class HeartbeatPayload(BaseModel):
    session_id: Optional[str] = ""
    state: Optional[str] = "CONNECTED"


class ServerState:
    def __init__(self):
        self.session_id: Optional[str] = None
        self.current_url: Optional[str] = None
        self.is_joined: bool = False
        self.automation: Optional[MeetAutomation] = None
        self.bridge: Optional[AudioBridge] = None
        self.backend_ws: Optional[WebSocket] = None
        self.last_heartbeat_time: float = time.time()
        self.lock = asyncio.Lock()


state = ServerState()


async def heartbeat_watchdog_loop():
    """Monitors heartbeat from backend. If backend crashes/dies, auto-leaves the meeting."""
    logger.info("Heartbeat watchdog loop started.")
    while True:
        await asyncio.sleep(5.0)
        if not state.is_joined:
            continue

        elapsed = time.time() - state.last_heartbeat_time
        if elapsed > HEARTBEAT_TIMEOUT_SECONDS:
            logger.error(
                f"🚨 BACKEND HEARTBEAT LOST! No ping for {elapsed:.1f}s (threshold: {HEARTBEAT_TIMEOUT_SECONDS}s). "
                f"Emergency auto-leave triggered to prevent zombie bot in Google Meet."
            )
            async with state.lock:
                if state.is_joined:
                    try:
                        if state.bridge:
                            await state.bridge.stop()
                            state.bridge = None
                        if state.automation:
                            await state.automation.leave()
                        state.is_joined = False
                        state.current_url = None
                        state.session_id = None
                        logger.info("Emergency auto-leave completed successfully.")
                    except Exception as e:
                        logger.exception(f"Failed to execute emergency auto-leave: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("meet_service starting up...")
    state.automation = MeetAutomation()
    await state.automation.start()
    watchdog_task = asyncio.create_task(heartbeat_watchdog_loop())
    yield
    logger.info("meet_service shutting down...")
    watchdog_task.cancel()
    if state.bridge:
        await state.bridge.stop()
    if state.automation:
        await state.automation.stop()


# Initialize FastAPI app with lifespan
app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "is_joined": state.is_joined,
        "session_id": state.session_id,
        "time_since_last_heartbeat": round(time.time() - state.last_heartbeat_time, 2),
    }


@app.post("/heartbeat")
async def receive_heartbeat(payload: HeartbeatPayload = None):
    """Updates heartbeat timestamp when backend pings."""
    state.last_heartbeat_time = time.time()
    return {"status": "ok", "last_heartbeat": state.last_heartbeat_time}


@app.post("/join")
async def join_meeting(req: JoinRequest):
    async with state.lock:
        state.last_heartbeat_time = time.time()
        if state.is_joined and state.current_url == req.meet_url:
            logger.info(f"Already inside {req.meet_url}, reusing session {state.session_id}")
            return {"status": "ok", "session_id": state.session_id, "reused": True}

        if state.is_joined:
            logger.info("Leaving previous meeting before joining new one...")
            if state.bridge:
                await state.bridge.stop()
                state.bridge = None
            await state.automation.leave()
            state.is_joined = False

        state.session_id = str(uuid.uuid4())
        state.current_url = req.meet_url
        logger.info(f"Joining: {req.meet_url} (session={state.session_id})")

        success = await state.automation.join(req.meet_url)
        if not success:
            state.current_url = None
            state.session_id = None
            raise HTTPException(status_code=500, detail="Failed to join Google Meet room")

        state.is_joined = True
        state.last_heartbeat_time = time.time()
        logger.info("Joined meeting successfully.")
        return {"status": "ok", "session_id": state.session_id}


@app.post("/leave")
async def leave_meeting():
    async with state.lock:
        if not state.is_joined:
            return {"status": "ok", "message": "Not in a meeting"}

        if state.bridge:
            await state.bridge.stop()
            state.bridge = None

        await state.automation.leave()
        state.is_joined = False
        state.current_url = None
        state.session_id = None
        logger.info("Left meeting.")
        return {"status": "ok"}


async def _handle_audio_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("Backend WebSocket connected.")
    state.backend_ws = websocket
    state.last_heartbeat_time = time.time()

    async def ws_sender(data: bytes):
        try:
            await websocket.send_bytes(data)
        except Exception:
            pass

    state.bridge = AudioBridge(ws_sender=ws_sender)
    await state.bridge.start()

    # Send handshake session_started control frame
    try:
        await websocket.send_text(
            json.dumps({
                "type": "session_started",
                "session_id": state.session_id or "default-session",
                "sample_rate": 16000,
                "channels": 1,
            })
        )
    except Exception:
        pass

    try:
        while True:
            msg = await websocket.receive()
            state.last_heartbeat_time = time.time()

            if "bytes" in msg and msg["bytes"]:
                data = msg["bytes"]
                if state.bridge:
                    await state.bridge.play(data)
            elif "text" in msg and msg["text"]:
                try:
                    payload = json.loads(msg["text"])
                    mtype = payload.get("type")
                    if mtype == "bot_state_changed":
                        speaking = payload.get("speaking", False)
                        if state.bridge:
                            state.bridge.set_speaking(speaking)
                except Exception as e:
                    logger.warning(f"Error handling WS control frame: {e}")
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        logger.info("Backend WebSocket disconnected cleanly.")
    finally:
        state.backend_ws = None
        if state.bridge:
            await state.bridge.stop()
            state.bridge = None


@app.websocket("/audio")
async def audio_websocket_default(websocket: WebSocket):
    await _handle_audio_websocket(websocket)


@app.websocket("/ws/audio")
async def audio_websocket_alt(websocket: WebSocket):
    await _handle_audio_websocket(websocket)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MEET_SERVICE_PORT", 5001))
    uvicorn.run(app, host="0.0.0.0", port=port)