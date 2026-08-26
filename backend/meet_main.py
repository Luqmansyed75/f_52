"""
Meet-mode entrypoint for the AI Meeting Representative.

Features:
  - SessionStateMachine tracking (STARTING -> JOINING -> CONNECTED -> LEAVING -> STOPPED)
  - Background Heartbeat sender to meet-container (every 5s)
  - WebSocketSource audio streaming
  - Silero VAD + Segmenter + Groq Whisper ASR (3-key load balancer)
  - Barge-in InterruptWatcher
  - Qdrant VectorStore RAG + Conversation Memory
  - Groq Llama streaming LLM + PromptBuilder
  - Piper / Kokoro Neural TTS over WebSocket
  - Voice-activated and command-based meeting exit
"""

import asyncio
import json
import logging
import os
import struct
import threading
import time
import urllib.error
import urllib.request
from queue import Empty, Queue

import config
from asr.asr import WhisperASR
from audio.barge_in import InterruptWatcher
from audio.sources.websocket_source import WebSocketSource
from audio.vad import SileroVAD
from core.event_bus import EventBus, RESPONSE_GENERATED, TRANSCRIPT_CREATED
from core.session_state import SessionState, SessionStateMachine
from core.observability import TurnTracker, LatencyAggregator
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
# Global Session State Machine
# ---------------------------------------------------------------------------
sm = SessionStateMachine()

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
MEET_SERVICE_URL = os.environ.get("MEET_SERVICE_URL", "http://meet-container:5001")
MEET_SERVICE_WS  = os.environ.get("MEET_SERVICE_WS",  "ws://meet-container:5001/audio")
MEET_URL         = os.environ.get("MEET_URL", "")

EXIT_PHRASES = [
    "leave the meeting",
    "leave the call",
    "leave meeting",
    "leave now",
    "exit the meeting",
    "exit the call",
    "you can leave",
    "bye bye",
    "goodbye",
    "hang up",
    "disconnect",
]

# ---------------------------------------------------------------------------
# Meet-container HTTP helpers & Heartbeat
# ---------------------------------------------------------------------------

def _http_post(path: str, body: dict, timeout: float = 30.0) -> dict:
    url = f"{MEET_SERVICE_URL}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def join_meeting(meet_url: str) -> str:
    """Tell meet-container to join the meeting. Returns session_id."""
    logger.info(f"[{sm.session_id}] Joining meeting: {meet_url}")
    try:
        result = _http_post("/join", {"meet_url": meet_url})
        session_id = result.get("session_id", "")
        logger.info(f"[{sm.session_id}] Joined. session_id={session_id} lifecycle={result.get('lifecycle')}")
        return session_id
    except urllib.error.HTTPError as e:
        if e.code == 409:
            logger.info(f"[{sm.session_id}] Bot is already in the meeting room (409 Conflict). Continuing...")
            return "reused"
        raise


def leave_meeting() -> None:
    """Tell meet-container to leave the meeting."""
    try:
        _http_post("/leave", {}, timeout=10.0)
        logger.info(f"[{sm.session_id}] 🚪 Left meeting successfully.")
    except Exception as e:
        logger.warning(f"[{sm.session_id}] leave_meeting failed: {e}")


def _heartbeat_loop(stop_event: threading.Event) -> None:
    """Background thread sending heartbeats every 5 seconds to meet-container."""
    logger.info(f"[{sm.session_id}] Heartbeat sender thread active.")
    consecutive_failures = 0

    while not stop_event.is_set():
        if stop_event.wait(5.0):
            break

        if sm.is_terminal():
            break

        try:
            _http_post(
                "/heartbeat",
                {"session_id": sm.session_id, "state": sm.current_state.value},
                timeout=3.0,
            )
            if consecutive_failures > 0:
                logger.info(f"[{sm.session_id}] Heartbeat to meet-container recovered.")
                if sm.current_state == SessionState.DEGRADED:
                    sm.transition_to(SessionState.CONNECTED, reason="heartbeat_recovered")
            consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            if consecutive_failures >= 3 and sm.current_state == SessionState.CONNECTED:
                logger.warning(
                    f"[{sm.session_id}] Heartbeat failed {consecutive_failures} times ({e}). Setting state to DEGRADED."
                )
                sm.transition_to(SessionState.DEGRADED, reason="heartbeat_failed")


# ---------------------------------------------------------------------------
# WebSocket TTS sink
# ---------------------------------------------------------------------------

class WebSocketTTSSink:
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
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=5)

    def send_pcm(self, pcm_bytes: bytes) -> None:
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

    logger.info(f"[{sm.session_id}] Starting AI Meeting Representative (Meet mode)...")
    load_start = time.perf_counter()

    segment_queue: Queue = Queue(maxsize=20)
    transcript_queue: Queue = Queue(maxsize=20)

    vad = SileroVAD()
    watcher_vad = SileroVAD()
    ring_buffer = RingBuffer()

    meeting_ended_event = threading.Event()
    heartbeat_stop_event = threading.Event()

    def on_session_started(session_id: str) -> None:
        logger.info(f"[{sm.session_id}] WebSocket audio session established: {session_id}")
        if sm.current_state in {SessionState.JOINING, SessionState.RECONNECTING, SessionState.DEGRADED}:
            sm.transition_to(SessionState.CONNECTED, reason="websocket_stream_ready")

    def on_meeting_ended(reason: str) -> None:
        logger.info(f"[{sm.session_id}] Meeting ended by remote: {reason}")
        if sm.can_transition_to(SessionState.LEAVING):
            sm.transition_to(SessionState.LEAVING, reason=f"remote_ended_{reason}")
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
    latency_agg = LatencyAggregator(window_size=20)

    load_end = time.perf_counter()
    logger.info(f"[{sm.session_id}] Model + service loading: {load_end - load_start:.3f}s")

    # Start Heartbeat watchdog pinger thread
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(heartbeat_stop_event,),
        daemon=True,
        name="heartbeat-pinger",
    )
    heartbeat_thread.start()

    event_queue: Queue[dict] = Queue()
    worker_stop = threading.Event()

    assembler = TranscriptAssembler(bus=bus)

    def handle_transcript(payload: dict) -> None:
        event_queue.put(payload)

    bus.subscribe(config.SUBJECT_SPEECH_STARTED, lambda p: session_manager.refresh_activity())
    bus.subscribe(config.SUBJECT_LLM_STARTED,    lambda p: session_manager.refresh_activity())
    bus.subscribe(config.SUBJECT_LLM_FINISHED,   lambda p: session_manager.refresh_activity())

    def _barge_in_monitor():
        while not worker_stop.is_set():
            if watcher.interrupt_event.wait(timeout=0.5):
                try:
                    bus.publish(config.SUBJECT_BARGE_IN, {"timestamp": time.time()})
                except Exception:
                    pass
                session_manager.refresh_activity()
                watcher.interrupt_event.clear()

    threading.Thread(target=_barge_in_monitor, daemon=True, name="barge-in-monitor").start()

    def worker() -> None:
        def process_payload(payload: dict) -> None:
            event = RawTranscriptEvent.model_validate(payload)
            text = event.text.strip()
            if not text:
                return

            # --- Observability: start turn tracking ---
            tracker = TurnTracker()
            tracker.mark("audio_received")
            tracker.set_metadata("text_len", str(len(text)))
            asr_latency = payload.get("latency", 0.0)
            tracker.set_metadata("asr_latency", f"{asr_latency:.3f}s")

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

            # Check for user exit intent
            text_lower = text.lower()
            is_exit_command = any(phrase in text_lower for phrase in EXIT_PHRASES)

            if not session_manager.should_respond(mention) and not is_exit_command:
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

            tracker.mark("rag_retrieved")
            turn_interrupted = {"flag": False}
            first_sentence_logged = {"done": False}

            def on_sentence(sentence: str) -> None:
                if turn_interrupted["flag"]:
                    return

                if not first_sentence_logged["done"]:
                    tracker.mark("llm_first_sentence")
                    tracker.mark("tts_started")
                    first_sentence_logged["done"] = True
                # Signal meet-container: bot is now SPEAKING
                ws_source.set_speaking(True)

                # Send TTS audio over WebSocket
                tts.piper.speak_to_websocket(
                    sentence,
                    ws_source=ws_source,
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
                ws_source.set_speaking(False)

            tracker.mark("tts_complete")

            if turn_interrupted["flag"]:
                logger.info(f"[{sm.session_id}] User interrupted assistant.")
                session_manager.refresh_activity()
                tracker.set_metadata("interrupted", "true")
                tracker.mark("turn_complete")
                tracker.log_summary()
                latency_agg.record_turn(tracker)
                return

            if response_text is None:
                logger.warning(f"[{sm.session_id}] LLM stream_reply failed.")
                tracker.mark("turn_complete")
                tracker.log_summary()
                latency_agg.record_turn(tracker)
                return
            db.insert_response(
                payload_session_id,
                response_text,
                triggering_utterance_id=utterance_id,
            )
            conversation_memory.add_assistant(response_text)
            tracker.mark("turn_complete")
            tracker.log_summary()
            latency_agg.record_turn(tracker)
            latency_agg.log_stats()

            bus.publish(
                RESPONSE_GENERATED,
                ResponseGeneratedEvent(
                    session_id=payload_session_id,
                    triggering_utterance_id=utterance_id,
                    response_text=response_text,
                    timestamp=time.time(),
                ).model_dump(),
            )

            # If user requested exit or LLM said goodbye, execute meeting leave
            if is_exit_command or any(w in response_text.lower() for w in ["leaving the meeting", "goodbye", "bye!"]):
                logger.info(f"[{sm.session_id}] 🔴 Voice exit triggered. Waiting 2.0s for TTS playback...")
                time.sleep(2.0)
                if sm.can_transition_to(SessionState.LEAVING):
                    sm.transition_to(SessionState.LEAVING, reason="voice_leave_command")
                leave_meeting()
                meeting_ended_event.set()

        def _on_session_expired(payload: dict) -> None:
            conversation_memory.clear()
            logger.info(f"[{sm.session_id}] Session expired. Conversation cleared.")

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
    worker_thread = threading.Thread(target=worker, daemon=True, name="llm-worker")
    worker_thread.start()

    # --- Join meeting via HTTP ---
    sm.transition_to(SessionState.JOINING, reason="requesting_join")
    try:
        join_meeting(MEET_URL)
    except Exception as e:
        logger.error(f"[{sm.session_id}] Failed to join meeting: {e}")
        sm.transition_to(SessionState.STOPPED, reason=f"join_failed_{e}")
        bus.close()
        db.close()
        return

    # --- Start audio pipeline ---
    ws_source.start_stream()
    segmenter.start_segmenter()
    asr_worker.start_worker()

    logger.info(f"[{sm.session_id}] --- 🟢 MEET MODE READY ---")

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
        logger.info(f"[{sm.session_id}] Interrupted by user.")
    finally:
        if sm.can_transition_to(SessionState.LEAVING):
            sm.transition_to(SessionState.LEAVING, reason="shutdown")

        heartbeat_stop_event.set()
        worker_stop.set()
        worker_thread.join(timeout=2)

        asr_worker.stop_worker()
        segmenter.stop_segmenter()
        ws_source.stop_stream()
        watcher.stop()
        tts.close()
        leave_meeting()
        bus.close()
        db.close()

        sm.transition_to(SessionState.STOPPED, reason="shutdown_complete")
        logger.info(f"[{sm.session_id}] Meet mode shutdown complete.")


if __name__ == "__main__":
    start_meeting()