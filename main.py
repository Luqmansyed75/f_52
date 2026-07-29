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
from asr.asr import WhisperASR
from audio.audio_io import MicListener
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




def start_meeting() -> None:
    """Start the always-listening meeting representative."""
    print("Loading models and services... this takes a moment.")
    load_start = time.perf_counter()

    vad = SileroVAD()
    watcher_vad = SileroVAD()
    mic = MicListener(vad)
    asr = WhisperASR()
    llm = LLMRouter()
    tts = TTSRouter()
    watcher = InterruptWatcher(watcher_vad, mic.open_secondary_stream())

    db = Database()
    vector_store = VectorStore()
    bus = EventBus()
    session_manager = SessionManager(timeout_seconds=10)
    conversation_memory = ConversationMemory(max_turns=10)
    prompt_builder = PromptBuilder()
    session_id = db.create_session()

    load_end = time.perf_counter()
    print(f"\n✅ Model + service loading time: {load_end - load_start:.3f} sec\n")


    event_queue: Queue[dict] = Queue()
    worker_stop = threading.Event()

    def handle_transcript(payload: dict) -> None:
        event_queue.put(payload)

    def worker() -> None:
       while not worker_stop.is_set():

            if session_manager.check_timeout():
                conversation_memory.clear()
                print("[Session] Conversation expired.")

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

            if not session_manager.should_respond(mention):
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

            turn_interrupted = {"flag": False}

            def on_sentence(sentence: str) -> None:
                if turn_interrupted["flag"]:
                    return
                watcher.start()
                tts.speak(sentence, interrupt_event=watcher.interrupt_event)
                watcher.stop()
                if watcher.interrupt_event.is_set():
                    turn_interrupted["flag"] = True


            meeting_context = context

            conversation_memory.add_user(text)
            messages = prompt_builder.build(
                            user_query=text,
                            conversation_history=conversation_memory.get_messages(),
                            meeting_context=meeting_context,
            )

            response_text = llm.stream_reply(
                messages,
                on_sentence=on_sentence,
            )

            db.insert_response(
                payload_session_id,
                response_text,
                triggering_utterance_id=utterance_id,
            )

            conversation_memory.add_assistant(response_text)

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
            full_audio=user_audio
            sf.write("assets/debug.wav", full_audio, config.RATE)
            duration = len(full_audio) / config.RATE
            print(f"[Audio] Duration: {duration:.2f} sec")
            print(full_audio.min())
            print(full_audio.max())
            print(full_audio.mean())
            print(np.abs(full_audio).mean())
                        

            if user_audio.size == 0:
                continue

            print("[📝 Transcribing...]")
            asr_start = time.perf_counter()
            user_text = asr.transcribe(user_audio)
            print(f"Transcript: {repr(user_text)}")
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