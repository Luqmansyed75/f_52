"""
Routes each spoken sentence to Piper.

The speak(text) interface stays unchanged so main.py can keep using the
router without any other changes.
"""

from tts.tts import PiperTTS
import time


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

    def close(self):
        self.piper.close()