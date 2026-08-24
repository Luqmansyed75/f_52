"""
Routes each spoken sentence to Kokoro (Neural TTS).

Compatible with both:
- main.py (local mic mode using .speak())
- meet_main.py (Google Meet mode using .speak_to_websocket() or .piper.speak_to_websocket())
"""

import time
from tts.tts import KokoroTTS
from core.logger import get_tts_logger

logger = get_tts_logger()


class TTSRouter:
    def __init__(self):
        self.kokoro = KokoroTTS()
        # Alias for backwards compatibility with meet_main.py
        self.piper = self.kokoro

    def speak(self, text: str, interrupt_event=None):
        """Local playback mode."""
        start = time.perf_counter()
        self.kokoro.speak(text, interrupt_event=interrupt_event)
        end = time.perf_counter()

        print("\n------ TTS LATENCY ------")
        print(f"TTS Total       : {end-start:.3f} sec")
        print("-------------------------\n")
        logger.info("TTS Router Total Latency: %.3f sec", end - start)

    def speak_to_websocket(self, text: str, ws_source, interrupt_event=None):
        """Google Meet streaming mode over WebSocket."""
        start = time.perf_counter()
        self.kokoro.speak_to_websocket(
            text,
            ws_source=ws_source,
            interrupt_event=interrupt_event,
        )
        end = time.perf_counter()
        logger.info("TTS WebSocket Stream Latency: %.3f sec", end - start)

    def close(self):
        self.kokoro.close()