"""
Text-to-speech module for Hindi/Telugu — wraps Meta's MMS-TTS
(VITS-based, loaded via transformers — no compilation/build tools
needed, unlike Coqui/AI4Bharat's Indic-TTS).

Install: pip install transformers torch (already in requirements.txt)
"""

import numpy as np
import torch
import pyaudio
from transformers import VitsModel, AutoTokenizer
from core.logger import get_tts_logger
from core.error_handler import handle_errors

logger = get_tts_logger()


MMS_TTS_MODELS = {
    "hi": "facebook/mms-tts-hin",
    "te": "facebook/mms-tts-tel",
}


class MMSTTS:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.device == "cpu":
            print("[mms_tts] No CUDA GPU detected — running on CPU (will be slower).")

        self.models = {}
        self.tokenizers = {}

        for language, model_id in MMS_TTS_MODELS.items():
            print(f"[mms_tts] Loading {model_id} for '{language}'...")
            self.tokenizers[language] = AutoTokenizer.from_pretrained(model_id)
            self.models[language] = VitsModel.from_pretrained(model_id).to(self.device)

        self.pa = pyaudio.PyAudio()

    @handle_errors(logger)
    def speak(self, text: str, language: str = "hi"):
        model = self.models.get(language)
        tokenizer = self.tokenizers.get(language)

        if not model or not tokenizer:
            print(f"[mms_tts] No model loaded for language '{language}' — skipping.")
            return

        print(f"🤖 AI ({language}): {text}")

        inputs = tokenizer(text, return_tensors="pt").to(self.device)

        with torch.no_grad():
            output = model(**inputs).waveform

        audio_np = output.squeeze().cpu().numpy()
        audio_int16 = (audio_np * 32767).clip(-32768, 32767).astype(np.int16)
        sample_rate = model.config.sampling_rate

        stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            output=True,
        )
        stream.write(audio_int16.tobytes())
        stream.stop_stream()
        stream.close()

    def close(self):
        self.pa.terminate()
