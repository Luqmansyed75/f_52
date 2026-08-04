"""
Main entry point for the always-listening meeting representative.

Mic -> VAD -> ASR -> TranscriptCreated event -> storage + mention
detection -> retrieval -> Groq -> Piper with barge-in.
"""
import threading
import time
from queue import Empty, Queue
import soundfile as sf
import numpy as np


import config
from schemas import ResponseGeneratedEvent, RawTranscriptEvent, MentionDetectedEvent
from asr.asr import WhisperASR
from core.logger import get_app_logger, get_performance_logger, get_error_logger
from core.error_handler import safe_execute

app_logger = get_app_logger()
perf_logger = get_performance_logger()
error_logger = get_error_logger()
# from audio.audio_io import MicListener
from audio.barge_in import InterruptWatcher
from memory.db import Database
from core.event_bus import EventBus, RESPONSE_GENERATED, TRANSCRIPT_CREATED
from llm.llm_router import LLMRouter
from meeting.mention_detector import is_mention
from meeting.session_manager import SessionManager
from memory.conversation_memory import ConversationMemory
from llm.prompt_builder import PromptBuilder
from llm.retrieval import retrieve_context
from tts.tts_router import TTSRouter
from audio.vad import SileroVAD
from memory.vector_store import VectorStore
from streaming.ring_buffer import RingBuffer
from streaming.mic_listener import MicListener
from streaming.segmenter import Segmenter
from streaming.asr_worker import ASRWorker




def start_meeting() -> None:
    """Start the always-listening meeting representative."""
    app_logger.info("Starting AI Meeting Representative...")
    print("Loading models and services... this takes a moment.")
    load_start = time.perf_counter()
    segment_queue = Queue(maxsize=20)
    transcript_queue = Queue(maxsize=20)
    vad = SileroVAD()
    watcher_vad = SileroVAD()
    ring_buffer=RingBuffer()
    mic = MicListener(
    ring_buffer=ring_buffer,
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
    llm = None
    tts = TTSRouter()
    watcher = InterruptWatcher(
    watcher_vad,
    ring_buffer,
    )

    db = Database()
    vector_store = VectorStore()
    bus = EventBus()
    session_manager = SessionManager(timeout_seconds=config.SESSION_INACTIVITY_SECONDS, bus=bus)
    # create llm/router after bus so it can publish lifecycle events
    llm = LLMRouter(bus=bus)
    conversation_memory = ConversationMemory(max_turns=10)
    prompt_builder = PromptBuilder()
    session_id = db.create_session()

    load_end = time.perf_counter()
    print(f"\n✅ Model + service loading time: {load_end - load_start:.3f} sec\n")
    perf_logger.info("Model + service loading time: %.3f sec", load_end - load_start)


    event_queue: Queue[dict] = Queue()
    worker_stop = threading.Event()

    from meeting.transcript_assembler import TranscriptAssembler

    assembler = TranscriptAssembler(bus=bus)

    def handle_transcript(payload: dict) -> None:
        event_queue.put(payload)

    bus.subscribe(config.SUBJECT_SPEECH_STARTED, lambda p: session_manager.refresh_activity())

    bus.subscribe(config.SUBJECT_LLM_STARTED, lambda p: session_manager.refresh_activity())
    bus.subscribe(config.SUBJECT_LLM_FINISHED, lambda p: session_manager.refresh_activity())

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
                print(f"[main] Vector store write failed: {exc}")
                error_logger.error("Vector store write failed: %s", exc, exc_info=True)

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

            def on_sentence(sentence):
                if turn_interrupted["flag"]:
                    return

                tts.speak(
                    sentence,
                    interrupt_event=watcher.interrupt_event,
                )

                if watcher.interrupt_event.is_set():
                    turn_interrupted["flag"] = True

            meeting_context = context

            conversation_memory.add_user(text)
            messages = prompt_builder.build(
                user_query=text,
                conversation_history=conversation_memory.get_messages(),
                meeting_context=meeting_context,
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

            if turn_interrupted["flag"]:
                app_logger.info("User interrupted assistant.")
                session_manager.refresh_activity()
                return

            if response_text is None:
                app_logger.warning("LLM stream_reply failed. Skipping response storage.")
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
            app_logger.info("[Session] Conversation expired.")

        bus.subscribe(config.SUBJECT_SESSION_EXPIRED, _on_session_expired, durable="session_watcher")

        while not worker_stop.is_set():
            try:
                payload = event_queue.get(timeout=0.25)
            except Empty:
                continue
            process_payload(payload)

    bus.subscribe(config.SUBJECT_TRANSCRIPT_READY, handle_transcript, durable="meeting_transcript_consumer")
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

    mic.start_stream()

    segmenter.start_segmenter()

    asr_worker.start_worker()
    print("--- 🟢 SYSTEM READY. Start talking! ---")
    app_logger.info("SYSTEM READY. Listening for speech...")

    try:
        while True:
            try:
                transcript = transcript_queue.get(timeout=0.25)
            except Empty:
                continue

            user_text = transcript.get("text", "").strip()
            timestamp = transcript.get("timestamp", time.time())
            latency = transcript.get("latency", 0.0)

            if not user_text:
                continue

            bus.publish(
                TRANSCRIPT_CREATED,
                RawTranscriptEvent(
                    session_id=session_id,
                    text=user_text,
                    timestamp=timestamp,
                    speaker="unknown",
                    asr_seconds=latency,
                ).model_dump(),
            )


    except KeyboardInterrupt:
        print("\n--- 🛑 System Terminated ---")
        app_logger.info("System Terminated by user.")

    finally:
        worker_stop.set()

        try:
            worker_thread.join(timeout=2)
        finally:
            asr_worker.stop_worker()
            segmenter.stop_segmenter()
            mic.stop_stream()

            watcher.stop()
            tts.close()
            bus.close()
            db.close()


if __name__ == "__main__":
    start_meeting()