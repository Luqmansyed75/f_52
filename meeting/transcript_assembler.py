"""
TranscriptAssembler

Listens for raw ASR transcript events and assembles them into
final "turn" transcripts using configurable timing heuristics.

Behavior
 - Merge consecutive ASR chunks for the same session when gaps are
   short (config.END_OF_TURN_MAX_GAP).
 - Wait for config.END_OF_TURN_TIMEOUT seconds of inactivity after the
   last chunk before emitting a ready transcript.
 - Emit events: SpeechStarted, TranscriptReady, TurnCompleted.
 - Suppress near-duplicate transcripts emitted repeatedly.

This keeps the audio pipeline unchanged while providing a cleaner
boundary for downstream LLM processing.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

import config
from core.event_bus import EventBus


class _AssemblyState:
    def __init__(self):
        self.chunks: List[Dict] = []
        self.first_ts: Optional[float] = None
        self.last_ts: Optional[float] = None
        self.timer: Optional[threading.Timer] = None
        self.last_emitted_text: Optional[str] = None
        self.last_emitted_at: float = 0.0


class TranscriptAssembler:
    """Assembles raw ASR transcripts into completed turn transcripts."""

    def __init__(self, bus: EventBus):
        self.bus = bus

        # per-session assembly state
        self._states: Dict[str, _AssemblyState] = {}
        self._lock = threading.Lock()
        # recent emitted transcripts per session (text, timestamp)
        # kept bounded by pruning on updates to avoid memory leaks
        self._recent_emitted: Dict[str, tuple[str, float]] = {}

        self.bus.subscribe(config.SUBJECT_TRANSCRIPT_CREATED, self._on_raw_transcript, durable="assembler")

    def _on_raw_transcript(self, payload: dict) -> None:
        """Handler invoked for each raw ASR transcript event."""
        session_id = payload.get("session_id")
        text = payload.get("text", "").strip()
        ts = payload.get("timestamp", time.time())

        if not text:
            return

        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                state = _AssemblyState()
                self._states[session_id] = state

            finalize_prev = False
            prev_state: Optional[_AssemblyState] = None

            # If there is an existing chunk, check gap to decide whether
            # to finalize the previous turn first.
            if state.chunks and state.last_ts is not None:
                gap = ts - state.last_ts
                if gap > config.END_OF_TURN_MAX_GAP:
                    # detach prev state so we can finalize without holding lock
                    finalize_prev = True
                    prev_state = state
                    # remove from dict to avoid race with _finalize_turn
                    try:
                        del self._states[session_id]
                    except Exception:
                        pass
                    # cancel previous state's timer to avoid duplicate firing
                    if prev_state.timer is not None:
                        try:
                            prev_state.timer.cancel()
                        except Exception:
                            pass
                        prev_state.timer = None
                    # create a fresh state for the new turn
                    state = _AssemblyState()
                    self._states[session_id] = state

            # If this is the first chunk for the (new) turn, emit SpeechStarted
            if not state.chunks:
                try:
                    self.bus.publish(
                        config.SUBJECT_SPEECH_STARTED,
                        {"session_id": session_id, "timestamp": ts},
                    )
                except Exception:
                    pass

            # Merge: append chunk
            state.chunks.append({"text": text, "ts": ts})
            if state.first_ts is None:
                state.first_ts = ts
            state.last_ts = ts

            # Cancel previous finalize timer and start a new one
            if state.timer is not None:
                try:
                    state.timer.cancel()
                except Exception:
                    pass
                state.timer = None

            state.timer = threading.Timer(config.END_OF_TURN_TIMEOUT, self._finalize_turn, args=(session_id,))
            state.timer.daemon = True
            state.timer.start()

        # Finalize previous turn outside lock if gap exceeded
        if finalize_prev and prev_state is not None:
            try:
                self._emit_and_clear_state(prev_state, session_id)
            except Exception:
                pass

    def _finalize_turn(self, session_id: str) -> None:
        """Called when we believe the user has finished a turn."""
        # Pop the state so it can be finalized without holding the lock
        with self._lock:
            state = self._states.pop(session_id, None)

        if state is None or not state.chunks:
            return

        # Delegate to helper that finalizes a detached state
        try:
            self._emit_and_clear_state(state, session_id)
        except Exception:
            pass
    def _emit_and_clear_state(self, state: _AssemblyState, session_id: str) -> None:
        """Emit TranscriptReady and TurnCompleted for the provided state.

        This helper runs without holding the main lock and will perform
        cleanup of timers held on the state object.
        """
        texts = [c["text"] for c in state.chunks]
        assembled = " ".join(t for t in texts if t).strip()

        now = time.time()

        # Duplicate suppression using recent emissions map (bounded)
        with self._lock:
            recent = self._recent_emitted.get(session_id)
            if recent is not None:
                recent_text, recent_ts = recent
                if assembled == recent_text and (now - recent_ts) < config.DUPLICATE_TRANSCRIPT_WINDOW:
                    # cancel timer and drop state
                    if state.timer is not None:
                        try:
                            state.timer.cancel()
                        except Exception:
                            pass
                        state.timer = None
                    return

        try:
            self.bus.publish(
                config.SUBJECT_TRANSCRIPT_READY,
                {
                    "session_id": session_id,
                    "text": assembled,
                    "speaker": "unknown",
                    "timestamp": state.last_ts or now,
                    "asr_seconds": 0.0,
                },
            )
        except Exception:
            pass

        # Record last emitted in recent map and prune old entries
        with self._lock:
            self._recent_emitted[session_id] = (assembled, now)
            # prune entries older than 5 minutes to keep the map bounded
            cutoff = now - 300
            keys_to_del = [k for k, v in self._recent_emitted.items() if v[1] < cutoff]
            for k in keys_to_del:
                try:
                    del self._recent_emitted[k]
                except Exception:
                    pass

        # Emit TurnCompleted
        try:
            self.bus.publish(
                config.SUBJECT_TURN_COMPLETED,
                {"session_id": session_id, "timestamp": now, "text": assembled},
            )
        except Exception:
            pass

        # cancel timer and clear
        if state.timer is not None:
            try:
                state.timer.cancel()
            except Exception:
                pass
            state.timer = None
