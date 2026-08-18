"""
Meet-mode entrypoint for the AI Meeting Representative.

Differences from main.py:
  - Audio source: WebSocketSource (from meet-container) instead of MicListener
  - Audio sink: TTS audio sent back over WebSocket to meet-container
  - Join/leave: HTTP calls to meet-container
  - Everything else (VAD, ASR, LLM, RAG, memory) is identical
"""

import asyncio
import json
import logging
import os
import struct
import threading
import time
import urllib.request
from queue import Empty, Queue

import config
from asr.asr import WhisperASR
from audio.barge_in import InterruptWatcher
from audio.sources.websocket_source import WebSocketSource
from audio.vad import SileroVAD
from core.event_bus import EventBus, RESPONSE_GENERATED, TRANSCRIPT_CREATED
from llm.llm_router import LLMRouter
from llm.prompt_builder import PromptBuilder
from llm.retrieval import retrieve_context
from meeting.mention_detector import is_mention
from meeting.session_manager import SessionManager
from meeting.transcript_assembler import TranscriptAssembler
from memory.conversation_memory import ConversationMemory
from memory.db import Database
from memory.vector_store import VectorStore
from schemas import MentionDetectedEvent, RawTranscriptEvent, ResponseGeneratedEvent
from streaming.asr_worker import ASRWorker
from streaming.ring_buffer import RingBuffer
from streaming.segmenter import Segmenter
from tts.tts_router import TTSRouter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("meet_main")

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------

MEET_SERVICE_URL = os.environ.get("MEET_SERVICE_URL", "http://meet-container:5001")
MEET_SERVICE_WS  = os.environ.get("MEET_SERVICE_WS",  "ws://meet-container:5001/audio")
MEET_URL         = os.environ.get("MEET_URL", "")


# ---------------------------------------------------------------------------
# Meet-container HTTP helpers
# ---------------------------------------------------------------------------

def _http_post(path: str, body: dict) -> dict:
    url = f"{MEET_SERVICE_URL}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def join_meeting(meet_url: str) -> str:
    """Tell meet-container to join the meeting. Returns session_id."""
    logger.info(f"Joining meeting: {meet_url}")
    result = _http_post("/join", {"meet_url": meet_url})
    session_id = result.get("session_id", "")
    logger.info(f"Joined. session_id={session_id} lifecycle={result.get('lifecycle')}")
    return session_id


def leave_meeting() -> None:
    """Tell meet-container to leave the meeting."""
    try:
        _http_post("/leave", {})
        logger.info("Left meeting.")
    except Exception as e:
        logger.warning(f"leave_meeting failed: {e}")


# ---------------------------------------------------------------------------
# WebSocket TTS sink
# ---------------------------------------------------------------------------

class WebSocketTTSSink:
    """
    Wraps TTSRouter to intercept PCM output and send it over WebSocket
    to meet-container instead of playing locally.

    meet_main passes this to TTSRouter via monkey-patch or subclass.
    Simpler approach: wrap at the speak() call site.
    """

    def __init__(self, ws_source: WebSocketSource):
        self._ws_source = ws_source
        self._seq = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._queue: Queue = Queue()
        self._running = False

    def start(self) -> None:
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="ws-tts-sink",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._queue.put(None)  # sentinel
        if self._thread:
            self._thread.join(timeout=5)

    def send_pcm(self, pcm_bytes: bytes) -> None:
        """Called from TTS thread. Queues PCM for async send."""
        self._queue.put(pcm_bytes)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._sender_loop())

    async def _sender_loop(self) -> None:
        while self._running:
            try:
                pcm = await self._loop.run_in_executor(
                    None,
                    lambda: self._queue.get(timeout=1.0),
                )
            except Exception:
                continue

            if pcm is None:
                break

            ws = self._ws_source._ws
            if ws is None:
                continue

            header = struct.pack(">I", self._seq)
            self._seq += 1

            try:
                await ws.send(header + pcm)
            except Exception as e:
                logger.warning(f"TTS WebSocket send failed: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def start_meeting() -> None:
    if not MEET_URL:
        logger.error("MEET_URL environment variable not set. Exiting.")
        return

    logger.info("Starting AI Meeting Representative (Meet mode)...")
    load_start = time.perf_counter()

    segment_queue: Queue = Queue(maxsize=20)
    transcript_queue: Queue = Queue(maxsize=20)

    vad = SileroVAD()
    watcher_vad = SileroVAD()
    ring_buffer = RingBuffer()

    # --- WebSocket audio source (replaces MicListener) ---
    meeting_ended_event = threading.Event()

    def on_session_started(session_id: str) -> None:
        logger.info(f"WebSocket session established: {session_id}")

    def on_meeting_ended(reason: str) -> None:
        logger.info(f"Meeting ended: {reason}")
        meeting_ended_event.set()

    ws_source = WebSocketSource(
        uri=MEET_SERVICE_WS,
        ring_buffer=ring_buffer,
        on_session_started=on_session_started,
        on_meeting_ended=on_meeting_ended,
    )

    segmenter = Segmenter(
        vad=vad,
        ring_buffer=ring_buffer,
        segment_queue=segment_queue,
    )

    asr = WhisperASR()
    asr_worker = ASRWorker(
        asr=asr,
        segment_queue=segment_queue,
        transcript_queue=transcript_queue,
    )

    tts = TTSRouter()
    ws_tts_sink = WebSocketTTSSink(ws_source)

    watcher = InterruptWatcher(watcher_vad, ring_buffer)

    db = Database()
    vector_store = VectorStore()
    bus = EventBus()
    session_manager = SessionManager(
        timeout_seconds=config.SESSION_INACTIVITY_SECONDS,
        bus=bus,
    )
    llm = LLMRouter(bus=bus)
    conversation_memory = ConversationMemory(max_turns=10)
    prompt_builder = PromptBuilder()
    meet_session_id = db.create_session()

    load_end = time.perf_counter()
    logger.info(f"Model + service loading: {load_end - load_start:.3f}s")

    event_queue: Queue[dict] = Queue()
    worker_stop = threading.Event()

    assembler = TranscriptAssembler(bus=bus)

    def handle_transcript(payload: dict) -> None:
        event_queue.put(payload)

    bus.subscribe(config.SUBJECT_SPEECH_STARTED, lambda p: session_manager.refresh_activity())
    bus.subscribe(config.SUBJECT_LLM_STARTED,    lambda p: session_manager.refresh_activity())
    bus.subscribe(config.SUBJECT_LLM_FINISHED,   lambda p: session_manager.refresh_activity())

    def _barge_in_monitor():
        while True:
            watcher.interrupt_event.wait()
            try:
                bus.publish(config.SUBJECT_BARGE_IN, {"timestamp": time.time()})
            except Exception:
                pass
            session_manager.refresh_activity()
            watcher.interrupt_event.clear()

    threading.Thread(target=_barge_in_monitor, daemon=True).start()

    def worker() -> None:
        def process_payload(payload: dict) -> None:
            event = RawTranscriptEvent.model_validate(payload)
            text = event.text.strip()
            if not text:
                return

            speaker = event.speaker
            created_at = event.timestamp
            payload_session_id = event.session_id

            session_manager.refresh_activity()
            mention = is_mention(text)

            utterance_id = db.insert_utterance(
                payload_session_id,
                text,
                speaker=speaker,
                is_mention=mention,
            )

            try:
                vector_store.upsert_utterance(utterance_id, payload_session_id, text)
            except Exception as exc:
                logger.error(f"Vector store write failed: {exc}", exc_info=True)

            if not session_manager.should_respond(mention):
                return

            bus.publish(
                config.SUBJECT_MENTION_DETECTED,
                MentionDetectedEvent(
                    session_id=payload_session_id,
                    utterance_id=utterance_id,
                    text=text,
                    timestamp=created_at,
                ).model_dump(),
            )

            context = retrieve_context(
                db,
                vector_store,
                payload_session_id,
                text,
                top_k=5,
            )

            turn_interrupted = {"flag": False}

            def on_sentence(sentence: str) -> None:
                if turn_interrupted["flag"]:
                    return

                # Signal meet-container: bot is now SPEAKING
                ws_source.set_speaking(True)

                # Speak via TTS (local piper → pcm)
                # TTSRouter.speak() synthesises and plays locally in mic mode.
                # In meet mode we need PCM bytes → WebSocket.
                # For now: speak locally to get the pipeline working,
                # then wire ws_tts_sink in Phase 3 polish.
                tts.speak(
                    sentence,
                    interrupt_event=watcher.interrupt_event,
                )

                if watcher.interrupt_event.is_set():
                    turn_interrupted["flag"] = True

            conversation_memory.add_user(text)
            messages = prompt_builder.build(
                user_query=text,
                conversation_history=conversation_memory.get_messages(),
                meeting_context=context,
            )

            watcher.interrupt_event.clear()
            watcher.start()

            try:
                response_text = llm.stream_reply(
                    messages,
                    on_sentence=on_sentence,
                )
            finally:
                watcher.stop()
                # Signal meet-container: bot is done SPEAKING
                ws_source.set_speaking(False)

            if turn_interrupted["flag"]:
                logger.info("User interrupted assistant.")
                session_manager.refresh_activity()
                return

            if response_text is None:
                logger.warning("LLM stream_reply failed.")
                return

            db.insert_response(
                payload_session_id,
                response_text,
                triggering_utterance_id=utterance_id,
            )
            conversation_memory.add_assistant(response_text)

            bus.publish(
                RESPONSE_GENERATED,
                ResponseGeneratedEvent(
                    session_id=payload_session_id,
                    triggering_utterance_id=utterance_id,
                    response_text=response_text,
                    timestamp=time.time(),
                ).model_dump(),
            )

        def _on_session_expired(payload: dict) -> None:
            conversation_memory.clear()
            logger.info("Session expired. Conversation cleared.")

        bus.subscribe(
            config.SUBJECT_SESSION_EXPIRED,
            _on_session_expired,
            durable="session_watcher",
        )

        while not worker_stop.is_set():
            try:
                payload = event_queue.get(timeout=0.25)
            except Empty:
                continue
            process_payload(payload)

    bus.subscribe(
        config.SUBJECT_TRANSCRIPT_READY,
        handle_transcript,
        durable="meeting_transcript_consumer",
    )
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

    # --- Join meeting via HTTP ---
    try:
        join_meeting(MEET_URL)
    except Exception as e:
        logger.error(f"Failed to join meeting: {e}")
        bus.close()
        db.close()
        return

    # --- Start audio pipeline ---
    ws_source.start_stream()
    ws_tts_sink.start()
    segmenter.start_segmenter()
    asr_worker.start_worker()

    logger.info("--- 🟢 MEET MODE READY ---")

    try:
        while not meeting_ended_event.is_set():
            try:
                transcript = transcript_queue.get(timeout=0.25)
            except Empty:
                continue

            user_text = transcript.get("text", "").strip()
            timestamp = transcript.get("timestamp", time.time())
            latency   = transcript.get("latency", 0.0)

            if not user_text:
                continue

            bus.publish(
                TRANSCRIPT_CREATED,
                RawTranscriptEvent(
                    session_id=meet_session_id,
                    text=user_text,
                    timestamp=timestamp,
                    speaker="unknown",
                    asr_seconds=latency,
                ).model_dump(),
            )

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        worker_stop.set()
        worker_thread.join(timeout=2)

        asr_worker.stop_worker()
        segmenter.stop_segmenter()
        ws_source.stop_stream()
        ws_tts_sink.stop()
        watcher.stop()
        tts.close()
        leave_meeting()
        bus.close()
        db.close()
        logger.info("Meet mode shutdown complete.")


if __name__ == "__main__":
    start_meeting()