import asyncio
import json
import logging
import os
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


class JoinRequest(BaseModel):
    meet_url: str


class ServerState:
    def __init__(self):
        self.session_id: Optional[str] = None
        self.current_url: Optional[str] = None
        self.is_joined: bool = False
        self.automation: Optional[MeetAutomation] = None
        self.bridge: Optional[AudioBridge] = None
        self.backend_ws: Optional[WebSocket] = None
        self.lock = asyncio.Lock()


state = ServerState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("meet_service starting up...")
    state.automation = MeetAutomation()
    await state.automation.start()
    yield
    logger.info("meet_service shutting down...")
    if state.bridge:
        await state.bridge.stop()
    if state.automation:
        await state.automation.stop()


# Initialize FastAPI app with lifespan
app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "is_joined": state.is_joined, "session_id": state.session_id}


@app.post("/join")
async def join_meeting(req: JoinRequest):
    async with state.lock:
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


@app.websocket("/audio")
async def audio_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("Backend WebSocket connected.")
    state.backend_ws = websocket

    async def ws_sender(data: bytes):
        try:
            await websocket.send_bytes(data)
        except Exception:
            pass

    state.bridge = AudioBridge(ws_sender=ws_sender)
    await state.bridge.start()

    # Send handshake session_started control frame
    await websocket.send_text(
        json.dumps({
            "type": "session_started",
            "session_id": state.session_id or "default-session",
            "sample_rate": 16000,
            "channels": 1,
        })
    )

    try:
        while True:
            msg = await websocket.receive()
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
    except (WebSocketDisconnect, asyncio.CancelledError):
        logger.info("Backend WebSocket disconnected.")
    finally:
        state.backend_ws = None
        if state.bridge:
            await state.bridge.stop()
            state.bridge = None


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MEET_SERVICE_PORT", 5001))
    uvicorn.run(app, host="0.0.0.0", port=port)