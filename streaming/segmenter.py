import threading
import time
from queue import Queue,Empty
import numpy as np
import torch

import config
from audio.vad import SileroVAD


class Segmenter(threading.Thread):
    def __init__(
        self,
        vad: SileroVAD,
        ring_buffer,
        segment_queue: Queue,
        sample_rate: int = config.RATE,
        vad_threshold: float = 0.60,
        silence_timeout: float = 1.0,
        min_speech_seconds: float = 0.40,
        max_segment_seconds: float = 5.0,
    ):
        super().__init__(daemon=True)

        self.vad = vad
        self.ring_buffer = ring_buffer
        self.consumer = self.ring_buffer.subscribe()
        self.segment_queue = segment_queue

        self.sample_rate = sample_rate
        self.vad_threshold = vad_threshold
        self.silence_timeout = silence_timeout
        self.min_speech_seconds = min_speech_seconds
        self.max_segment_seconds = max_segment_seconds

        self.chunk_samples = 512
        self.chunk_duration = self.chunk_samples / self.sample_rate

        self.state = "IDLE"

        self.current_frames = []
        self.segment_start_time = None
        self.last_speech_time = None

        self._running = False

    def start_segmenter(self):
        self._running = True
        self.start()

    def stop_segmenter(self):
        self._running = False
        self.ring_buffer.unsubscribe(self.consumer)

        if self.is_alive():
            self.join(timeout=2)

    def run(self):

        while self._running:

            frame = self.consumer.read(timeout=0.1)
            if frame is None:
                continue

            prob = self._speech_probability(frame)

            if self.state == "IDLE":

                if prob >= self.vad_threshold:

                    self.vad.reset()

                    self.state = "RECORDING"

                    self.current_frames = [frame]

                    now = time.perf_counter()

                    self.segment_start_time = now
                    self.last_speech_time = now

            else:

                self.current_frames.append(frame)

                now = time.perf_counter()

                if prob >= self.vad_threshold:
                    self.last_speech_time = now

                segment_duration = now - self.segment_start_time
                silence_duration = now - self.last_speech_time

                if segment_duration >= self.max_segment_seconds:
                    self._emit_segment()

                    # Immediately begin a new segment with the current frame
                    self.state = "RECORDING"
                    self.current_frames = [frame]
                    self.segment_start_time = now
                    self.last_speech_time = now
                    continue

                if silence_duration >= self.silence_timeout:

                    if segment_duration >= self.min_speech_seconds:
                        self._emit_segment()
                    else:
                        self._reset()

    def _speech_probability(self, frame: bytes) -> float:

        audio = np.frombuffer(
            frame,
            dtype=np.int16,
        ).astype(np.float32)

        audio /= 32768.0

        tensor = torch.from_numpy(audio)

        with torch.inference_mode():
            return self.vad.speech_probability(
                tensor,
                self.sample_rate,
            )

    def _emit_segment(self):

        audio = b"".join(self.current_frames)

        audio = np.frombuffer(
            audio,
            dtype=np.int16,
        ).astype(np.float32)

        audio /= 32768.0

        self.segment_queue.put(audio)

        self._reset()

    def _reset(self):

        self.vad.reset()

        self.state = "IDLE"

        self.current_frames.clear()

        self.segment_start_time = None

        self.last_speech_time = None