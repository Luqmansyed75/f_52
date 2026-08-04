"""
Routes each spoken sentence to Piper.

The speak(text) interface stays unchanged so main.py can keep using the
router without any other changes.
"""

from tts.tts import PiperTTS
import time
from core.logger import get_tts_logger

logger = get_tts_logger()


class TTSRouter:
    def __init__(self):
        self.piper = PiperTTS()

    def speak(self, text: str, interrupt_event=None):
        start = time.perf_counter()

        self.piper.speak(text, interrupt_event=interrupt_event)

        end = time.perf_counter()

        print("\n------ TTS LATENCY ------")
        print(f"TTS Total       : {end-start:.3f} sec")
        print("-------------------------\n")
        logger.info("TTS Router Total Latency: %.3f sec", end-start)

    def close(self):
        self.piper.close()