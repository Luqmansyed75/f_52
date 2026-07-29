"""

Mic
 ↓
VAD
 ↓
Qwen ASR
 ↓
Wake Word
 ↓
Groq
 ↓
Piper TTS
"""

import config

from audio.audio_io import MicListener
from audio.vad import SileroVAD
from asr.asr import QwenASR
from llm.llm import GroqLLM
from tts.tts_router import TTSRouter

# -----------------------------
# Wake Words
# -----------------------------

WAKE_WORDS = [
    "assistant",
    "hey assistant",
    "proxy",
    "hey proxy",
]


def detect_wake_word(text: str):
    if not text:
        return False, ""

    original = text.strip()
    lower = original.lower()

    for wake in sorted(WAKE_WORDS, key=len, reverse=True):
        idx = lower.find(wake)

        if idx != -1:
            cleaned = (
                original[:idx] +
                original[idx + len(wake):]
            ).strip(" ,.!?")

            return True, cleaned

    return False, original


# -----------------------------
# Load Everything
# -----------------------------

print("Loading models...")

vad = SileroVAD()
mic = MicListener(vad)

asr = QwenASR()

llm = GroqLLM()

tts = TTSRouter()

history = [
    {
        "role": "system",
        "content": config.SYSTEM_PROMPT
    }
]

print("\n✅ Ready!\n")


# -----------------------------
# Main Loop
# -----------------------------

try:

    while True:

        audio = mic.listen_until_pause()

        if audio.size == 0:
            continue

        print("\n🎤 Processing...\n")

        text = asr.transcribe(audio)

        print("📝 Transcript :", repr(text))

        if not text:
            continue

        triggered, query = detect_wake_word(text)

        if not triggered:
            print("❌ Wake word not detected.")
            continue

        print("✅ Wake word detected!")
        print("💬 Query :", query)

        def on_sentence(sentence):

            print("🤖", sentence)

            tts.speak(sentence)

        response = llm.stream_reply(
            prompt=query,
            conversation_history=history,
            on_sentence=on_sentence,
        )

        history.append(
            {
                "role": "user",
                "content": query,
            }
        )

        history.append(
            {
                "role": "assistant",
                "content": response,
            }
        )

except KeyboardInterrupt:

    print("\nStopping...")

finally:

    mic.close()
    tts.close()