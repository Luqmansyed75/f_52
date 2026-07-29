"""
Main entry point for the always-listening meeting representative.

Mic -> VAD -> ASR -> TranscriptCreated event -> storage + mention
detection -> retrieval -> Groq -> Piper with barge-in.
"""

import json
import threading
import time
from queue import Empty, Queue

import config
from asr.asr import QwenASR
from audio.audio_io import MicListener
from audio.barge_in import InterruptWatcher
from memory.db import Database
from core.event_bus import EventBus, RESPONSE_GENERATED, TRANSCRIPT_CREATED
from llm.llm_router import LLMRouter
from meeting.mention_detector import is_mention
from llm.retrieval import retrieve_context
from tts.tts_router import TTSRouter
from audio.vad import SileroVAD
from memory.vector_store import VectorStore


def _format_prompt(query_text: str, context: str) -> str:
    if context:
        return (
            "Use the session context below to answer the question. "
            "If the context is insufficient, say so briefly.\n\n"
            f"Session context:\n{context}\n\n"
            f"Question: {query_text}"
        )
    return f"Question: {query_text}"


def start_meeting() -> None:
    """Start the always-listening meeting representative."""
    print("Loading models and services... this takes a moment.")
    load_start = time.perf_counter()

    vad = SileroVAD()
    watcher_vad = SileroVAD()
    mic = MicListener(vad)
    asr = QwenASR()
    llm = LLMRouter()
    tts = TTSRouter()
    watcher = InterruptWatcher(watcher_vad, mic.stream)

    db = Database()
    vector_store = VectorStore()
    bus = EventBus()
    session_id = db.create_session()

    load_end = time.perf_counter()
    print(f"\n✅ Model + service loading time: {load_end - load_start:.3f} sec\n")

    history = [{"role": "system", "content": config.SYSTEM_PROMPT}]
    event_queue: Queue[dict] = Queue()
    worker_stop = threading.Event()

    def handle_transcript(payload: dict) -> None:
        event_queue.put(payload)

    def worker() -> None:
        while not worker_stop.is_set():
            try:
                payload = event_queue.get(timeout=0.25)
            except Empty:
                continue

            text = payload.get("text", "").strip()
            if not text:
                continue

            speaker = payload.get("speaker", "unknown")
            created_at = payload.get("timestamp")
            payload_session_id = payload.get("session_id", session_id)

            utterance_id = db.insert_utterance(
                payload_session_id,
                text,
                speaker=speaker,
                is_mention=is_mention(text),
            )

            try:
                vector_store.upsert_utterance(utterance_id, payload_session_id, text)
            except Exception as exc:
                print(f"[main] Vector store write failed: {exc}")

            if not is_mention(text):
                continue

            bus.publish(
                config.SUBJECT_MENTION_DETECTED,
                {
                    "session_id": payload_session_id,
                    "utterance_id": utterance_id,
                    "text": text,
                    "timestamp": created_at,
                },
            )

            context = retrieve_context(
                db,
                vector_store,
                payload_session_id,
                text,
                top_k=5,
            )
            prompt = _format_prompt(text, context)

            turn_interrupted = {"flag": False}

            def on_sentence(sentence: str) -> None:
                if turn_interrupted["flag"]:
                    return
                watcher.start()
                tts.speak(sentence, interrupt_event=watcher.interrupt_event)
                watcher.stop()
                if watcher.interrupt_event.is_set():
                    turn_interrupted["flag"] = True

            response_text = llm.stream_reply(prompt, history, on_sentence=on_sentence)

            db.insert_response(
                payload_session_id,
                response_text,
                triggering_utterance_id=utterance_id,
            )

            history.append({"role": "user", "content": f"User: {text}"})
            history.append({"role": "assistant", "content": response_text})

            bus.publish(
                RESPONSE_GENERATED,
                {
                    "session_id": payload_session_id,
                    "triggering_utterance_id": utterance_id,
                    "response_text": response_text,
                    "timestamp": time.time(),
                },
            )

    bus.subscribe(TRANSCRIPT_CREATED, handle_transcript, durable="meeting_transcript_consumer")
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

    print("--- 🟢 SYSTEM READY. Start talking! ---")

    try:
        while True:
            listen_start = time.perf_counter()
            user_audio = mic.listen_until_pause()
            listen_end = time.perf_counter()
            len(user_audio)
            len(user_audio)/16000
            user_audio.min()
            user_audio.max()

            if user_audio.size == 0:
                continue

            print("[📝 Transcribing...]")
            asr_start = time.perf_counter()
            user_text = asr.transcribe(user_audio)
            asr_end = time.perf_counter()
            

            if not user_text:
                continue

            bus.publish(
                TRANSCRIPT_CREATED,
                {
                    "session_id": session_id,
                    "text": user_text,
                    "timestamp": time.time(),
                    "speaker": "unknown",
                    "listen_seconds": listen_end - listen_start,
                    "asr_seconds": asr_end - asr_start,
                },
            )

    except KeyboardInterrupt:
        print("\n--- 🛑 System Terminated ---")

    finally:
        worker_stop.set()
        mic.close()
        tts.close()
        bus.close()
        db.close()


if __name__ == "__main__":
    start_meeting()