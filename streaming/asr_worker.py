import threading
import time
from queue import Queue, Empty

import numpy as np

from asr.asr import WhisperASR
import config
from core.logger import get_asr_logger

logger = get_asr_logger()

class ASRWorker(threading.Thread):
    """
    Consumes speech segments and produces transcripts.
    """

    def __init__(
        self,
        asr: WhisperASR,
        segment_queue: Queue,
        transcript_queue: Queue,
        sample_rate=config.RATE
    ):
        super().__init__(daemon=True)

        self.asr = asr
        self.segment_queue = segment_queue
        self.transcript_queue = transcript_queue

        self._running = False
        self.sample_rate = sample_rate

    def start_worker(self):
        self._running = True
        self.start()

    def stop_worker(self):
        self._running = False

        if self.is_alive():
            self.join(timeout=2)

    def run(self):

        while self._running:

            try:
                audio = self.segment_queue.get(timeout=0.1)

            except Empty:
                continue

            try:

                if audio.size == 0:
                    continue

                duration = len(audio) / self.sample_rate

                print(
                    f"[ASRWorker] Processing "
                    f"{duration:.2f}s segment..."
                )
                logger.debug("Processing %.2fs segment...", duration)

                start = time.perf_counter()

                text = self.asr.transcribe(audio)

                latency = time.perf_counter() - start

                print(
                    f"[ASRWorker] "
                    f"{latency:.2f}s "
                    f"-> {repr(text)}"
                )
                logger.info("Transcribed (%.2fs): %s", latency, text)

                if not text.strip():
                    continue

                self.transcript_queue.put(
                    {
                        "text": text,
                        "audio": audio,
                        "latency": latency,
                        "timestamp": time.time(),
                    }
                )

            except Exception as e:

                print(f"[ASRWorker] {e}")
                logger.error("ASR worker error: %s", e, exc_info=True)