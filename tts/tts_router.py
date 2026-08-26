"""
TTSRouter — chooses between PiperTTS (fast ~30ms) and KokoroTTS (neural).
Select via environment variable: TTS_ENGINE=piper or TTS_ENGINE=kokoro
"""

import os
from tts.tts import KokoroTTS, PiperTTS


class TTSRouter:
    def __init__(self):
        self.engine_type = os.environ.get("TTS_ENGINE", "piper").lower()

        if self.engine_type == "kokoro":
            self.engine = KokoroTTS()
            if not self.engine._initialized:
                print("[TTSRouter] Kokoro not available. Falling back to Piper.")
                self.engine = PiperTTS()
                self.engine_type = "piper"
        else:
            print("[TTSRouter] 🚀 Using Piper C++ TTS Engine (Ultra-Fast ~30ms)")
            self.engine = PiperTTS()

        # Alias for backwards compatibility
        self.piper = self.engine

    def speak(self, text: str, interrupt_event=None):
        self.engine.speak(text, interrupt_event=interrupt_event)

    def speak_to_websocket(self, text: str, ws_source, interrupt_event=None):
        self.engine.speak_to_websocket(text, ws_source=ws_source, interrupt_event=interrupt_event)

    def close(self):
        self.engine.close()