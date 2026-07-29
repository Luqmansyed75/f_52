"""
Barge-in / interruption support.

Runs a background thread that listens to the mic via VAD WHILE the AI
is speaking. If it detects sustained user speech, it sets an
interrupt_event that tts.py checks between audio chunks to stop
playback early.

KNOWN LIMITATION: without an AEC (acoustic echo cancellation) or a
headset, the mic will pick up the AI's own voice from the speakers,
which can cause false interrupts. This module reduces (does not
eliminate) that risk via:
  - a grace period after TTS starts (ignore the first N ms — the AI's
    own opening audio is loudest/most likely to leak into the mic)
  - requiring several consecutive speech-positive VAD frames before
    declaring a real interrupt (filters out short echo blips)
Test with headphones first to confirm the interrupt logic itself works
before tuning these thresholds for a speaker setup.
"""

import threading
import time
import numpy as np
import torch

import config


class InterruptWatcher:
    def __init__(self, vad, mic_stream):
        self.vad = vad
        self.mic_stream = mic_stream
        self.interrupt_event = threading.Event()
        self._stop_watching = threading.Event()
        self._thread = None

        # Tunable safeguards against false triggers from speaker bleed.
        self.grace_period_sec = 0.4
        self.consecutive_frames_required = 4  # ~128ms of sustained speech at 32ms/frame

    def start(self):
        self.interrupt_event.clear()
        self._stop_watching.clear()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_watching.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _watch(self):
        self.vad.reset()
        start_time = time.time()
        consecutive_speech_frames = 0

        while not self._stop_watching.is_set():
            try:
                data = self.mic_stream.read(config.CHUNK, exception_on_overflow=False)
            except Exception:
                break

            if time.time() - start_time < self.grace_period_sec:
                continue  # skip grace period, don't even run VAD yet

            audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            audio_tensor = torch.from_numpy(audio_np)
            speech_prob = self.vad.speech_probability(audio_tensor, config.RATE)

            if speech_prob > config.VAD_SPEECH_THRESHOLD:
                consecutive_speech_frames += 1
            else:
                consecutive_speech_frames = 0

            if consecutive_speech_frames >= self.consecutive_frames_required:
                print("\n[⚡ Interrupt detected]")
                self.interrupt_event.set()
                return