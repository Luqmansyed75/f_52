"""
Speech-to-text module — supports high-speed Groq Whisper API (sub-second)
with Sliding-Window Multi-Key Load Balancing and Circuit Breaker failover,
plus automatic fallback to local Faster-Whisper.
"""

import collections
import io
import os
import re
import threading
import time
import wave
import numpy as np
import requests

import config
from core.logger import get_asr_logger

logger = get_asr_logger()


class KeyTracker:
    """Tracks sliding-window rate limits and health for a single Groq API key."""

    def __init__(self, key: str, max_rpm: int = 18):
        self.key = key
        self.max_rpm = max_rpm
        self.timestamps: collections.deque = collections.deque()
        self.quarantine_until: float = 0.0
        self.total_success: int = 0
        self.total_errors: int = 0

    def clean_old_timestamps(self, now: float) -> None:
        window_start = now - 60.0
        while self.timestamps and self.timestamps[0] < window_start:
            self.timestamps.popleft()

    @property
    def current_rpm(self) -> int:
        self.clean_old_timestamps(time.time())
        return len(self.timestamps)

    def is_available(self, now: float) -> bool:
        if now < self.quarantine_until:
            return False
        self.clean_old_timestamps(now)
        return len(self.timestamps) < self.max_rpm

    def record_success(self, now: float) -> None:
        self.timestamps.append(now)
        self.total_success += 1

    def quarantine(self, duration_sec: float = 60.0) -> None:
        self.quarantine_until = time.time() + duration_sec
        self.total_errors += 1


class WhisperASR:
    def __init__(self, model_name: str = None):
        self.backend = os.environ.get("ASR_BACKEND", "groq").lower()
        self.model_name = model_name or getattr(config, "ASR_MODEL_ID", "whisper-large-v3-turbo")
        self.model = None
        self._lock = threading.Lock()

        # Initialize API keys (supports comma-separated list or single key)
        raw_keys = os.environ.get("GROQ_API_KEYS") or os.environ.get("GROQ_API_KEY") or getattr(config, "GROQ_API_KEY", "")
        key_list = [k.strip() for k in raw_keys.split(",") if k.strip()]

        self.key_trackers = [KeyTracker(k, max_rpm=18) for k in key_list]

        if self.backend == "groq" and not self.key_trackers:
            print("[ASR] ⚠️ No Groq API keys found. Falling back to local Faster-Whisper.")
            self.backend = "local"

        if self.backend == "groq":
            print(f"[ASR] 🚀 Using Groq Whisper API with {len(self.key_trackers)} active key(s) (Sliding-Window Balancer)")
            logger.info(f"Initialized Groq Whisper API with {len(self.key_trackers)} key(s)")
        else:
            self._init_local_whisper()

    def _init_local_whisper(self):
        import torch
        from faster_whisper import WhisperModel

        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

        print(f"[ASR] Loading local Faster-Whisper ({self.model_name})...")
        print(f"[ASR] Device       : {device}")
        print(f"[ASR] Compute Type : {compute_type}")

        start = time.perf_counter()
        self.model = WhisperModel(
            self.model_name,
            device=device,
            compute_type=compute_type,
        )
        elapsed = time.perf_counter() - start
        print(f"[ASR] Model loaded in {elapsed:.3f} sec")
        logger.info(f"Faster-Whisper model loaded in {elapsed:.3f}s (device={device}, compute={compute_type})")

    def _select_best_key(self) -> KeyTracker:
        """Select the key with the lowest load in the current 60s sliding window."""
        with self._lock:
            now = time.time()
            available = [t for t in self.key_trackers if t.is_available(now)]

            if available:
                # Pick the key with the minimum requests in the last 60 seconds
                available.sort(key=lambda t: len(t.timestamps))
                return available[0]

            # If all keys are at capacity, pick the one that will become available earliest
            print("[ASR] ⚠️ All Groq keys at rate ceiling. Waiting for oldest key slot...")
            logger.warning("All Groq API keys at rate ceiling")
            self.key_trackers.sort(key=lambda t: t.timestamps[0] if t.timestamps else t.quarantine_until)
            return self.key_trackers[0]

    def transcribe(self, audio_np: np.ndarray) -> str:
        """
        Parameters
        ----------
        audio_np : np.ndarray
            Float32 or int16 mono PCM audio sampled at 16kHz.

        Returns
        -------
        str
            Transcribed text.
        """
        if self.backend == "groq":
            return self._transcribe_groq(audio_np)
        else:
            return self._transcribe_local(audio_np)

    def _transcribe_groq(self, audio_np: np.ndarray) -> str:
        start = time.perf_counter()
        try:
            # 1. Normalize float32 PCM (-1.0 to 1.0) to int16 bytes
            if audio_np.dtype == np.float32 or audio_np.dtype == np.float64:
                audio_int16 = (np.clip(audio_np, -1.0, 1.0) * 32767).astype(np.int16)
            else:
                audio_int16 = audio_np.astype(np.int16)

            # Skip ultra-short noise bursts (< 0.4s) to conserve API quotas
            if len(audio_int16) < 16000 * 0.4:
                return ""

            # 2. Build in-memory 16kHz mono WAV file
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(16000)
                wf.writeframes(audio_int16.tobytes())

            wav_bytes = wav_buffer.getvalue()

            # 3. Call Groq Whisper API with circuit breaker failover
            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            data = {
                "model": "whisper-large-v3-turbo",
                "temperature": "0.0",
                "response_format": "json",
                "language": "en",
            }

            # Attempt transcription with failover across available keys
            attempts = len(self.key_trackers)
            for attempt in range(max(1, attempts)):
                tracker = self._select_best_key()
                headers = {"Authorization": f"Bearer {tracker.key}"}
                files = {"file": ("audio.wav", wav_bytes, "audio/wav")}

                try:
                    resp = requests.post(url, headers=headers, files=files, data=data, timeout=8)
                    
                    if resp.status_code == 429:
                        print(f"[ASR] ⚠️ Key ...{tracker.key[-6:]} hit 429 Rate Limit. Quarantining 60s.")
                        logger.warning(f"Key ...{tracker.key[-6:]} rate limited. Quarantining.")
                        tracker.quarantine(60.0)
                        continue

                    resp.raise_for_status()
                    tracker.record_success(time.time())

                    raw_text = resp.json().get("text", "").strip()
                    text = _collapse_repetition(raw_text)

                    latency = time.perf_counter() - start
                    key_hint = f"...{tracker.key[-6:]}"
                    print(f"[ASR] Key: {key_hint} | RPM: {tracker.current_rpm}/18 | Latency: {latency:.3f}s")
                    logger.info(f"Groq ASR text (key={key_hint}, latency={latency:.3f}s): {text}")
                    return text

                except requests.exceptions.RequestException as req_err:
                    print(f"[ASR] ⚠️ Key ...{tracker.key[-6:]} request error: {req_err}")
                    logger.warning(f"Groq API error on key ...{tracker.key[-6:]}: {req_err}")
                    tracker.quarantine(30.0)

            # If all API attempts fail, fallback to local if initialized
            if self.model is not None:
                return self._transcribe_local(audio_np)
            return ""

        except Exception as e:
            latency = time.perf_counter() - start
            print(f"[ASR] Groq transcription error ({latency:.3f}s): {e}")
            logger.error(f"Groq ASR fatal error: {e}")
            if self.model is not None:
                return self._transcribe_local(audio_np)
            return ""

    def _transcribe_local(self, audio_np: np.ndarray) -> str:
        if self.model is None:
            self._init_local_whisper()

        start = time.perf_counter()
        if audio_np.dtype != np.float32:
            audio_np = audio_np.astype(np.float32) / 32768.0

        segments, info = self.model.transcribe(
            audio_np,
            language="en",
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
        )

        text = " ".join(segment.text.strip() for segment in segments).strip()
        text = _collapse_repetition(text)

        latency = time.perf_counter() - start
        print(f"[ASR] Local Whisper Latency: {latency:.3f} sec")
        logger.info(f"Local ASR text (latency={latency:.3f}s): {text}")
        return text


def _collapse_repetition(text: str, min_repeats: int = 3) -> str:
    """Collapse repetitive hallucinations."""
    if not text:
        return text

    sentences = re.split(r'(?<=[.!?])\s+', text)
    collapsed = []
    i = 0
    while i < len(sentences):
        current = sentences[i]
        repeat_count = 1
        j = i + 1
        while j < len(sentences) and sentences[j].strip().lower() == current.strip().lower():
            repeat_count += 1
            j += 1

        collapsed.append(current)
        if repeat_count >= min_repeats:
            print(f"[ASR] Collapsed {repeat_count}x repeated sentence: '{current}'")
            logger.warning(f"Collapsed {repeat_count}x repeated sentence: '{current}'")
        i = j

    return " ".join(collapsed).strip()