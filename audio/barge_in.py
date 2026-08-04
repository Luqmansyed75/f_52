import threading
import time

import numpy as np
import torch

import config


class InterruptWatcher:
    """
    Watches live microphone audio coming from the RingBuffer.

    This does NOT open another microphone stream.
    """

    def __init__(self, vad, ring_buffer):
        self.vad = vad
        self.ring_buffer = ring_buffer

        self.interrupt_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread = None
        self.consumer = None

        self.grace_period_sec = 0.4
        self.consecutive_frames_required = 4

    def start(self):

        if self._thread is not None and self._thread.is_alive():
            return

        self.interrupt_event.clear()
        self._stop_event.clear()
        
        if not self.consumer:
            self.consumer = self.ring_buffer.subscribe()

        self._thread = threading.Thread(
            target=self._watch,
            daemon=True,
        )
        self._thread.start()

    def stop(self):

        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=1)

        self._thread = None
        
        if self.consumer:
            self.ring_buffer.unsubscribe(self.consumer)
            self.consumer = None

    def _watch(self):

        self.vad.reset()

        start_time = time.time()

        consecutive = 0

        while not self._stop_event.is_set():

            frame = self.consumer.read(timeout=0.1)

            if frame is None:
                continue

            if time.time() - start_time < self.grace_period_sec:
                continue

            audio = (
                np.frombuffer(frame, dtype=np.int16)
                .astype(np.float32)
                / 32768.0
            )

            speech_prob = self.vad.speech_probability(
                torch.from_numpy(audio),
                config.RATE,
            )

            if speech_prob > config.VAD_SPEECH_THRESHOLD:
                consecutive += 1
            else:
                consecutive = 0

            if consecutive >= self.consecutive_frames_required:

                print("\n[⚡ Barge-In Detected]")

                self.interrupt_event.set()
                return