"""
Text-to-speech module — supports:
1. KokoroTTS (Neural, human-like voice, direct in-memory synthesis, fast clause streaming)
2. PiperTTS (Fast offline fallback)

Handles local mic playback and WebSocket streaming to meet-container.
"""

import os
import re
import struct
import time
import numpy as np
import scipy.signal
from core.logger import get_tts_logger
from core.error_handler import handle_errors
import config

logger = get_tts_logger()


class KokoroTTS:
    """Neural in-memory TTS engine using Kokoro-82M ONNX."""

    def __init__(
        self,
        model_path: str = None,
        voices_path: str = None,
        default_voice: str = "af_sarah",
    ):
        self.default_voice = default_voice
        self.kokoro = None
        self._initialized = False

        base = getattr(config, "BASE_DIR", "/app")
        self.model_path = model_path or os.path.join(base, "assets", "kokoro", "kokoro-v0_19.onnx")
        self.voices_path = voices_path or os.path.join(base, "assets", "kokoro", "voices.json")

        self._init_model()

    def _init_model(self):
        try:
            from kokoro_onnx import Kokoro
            if os.path.exists(self.model_path) and os.path.exists(self.voices_path):
                t0 = time.perf_counter()
                self.kokoro = Kokoro(self.model_path, self.voices_path)
                self._initialized = True
                elapsed = time.perf_counter() - t0
                print(f"[TTS] 🚀 Kokoro-82M Neural TTS initialized in {elapsed:.3f}s (voice={self.default_voice})")
                logger.info(f"Kokoro-82M initialized in {elapsed:.3f}s")
            else:
                print(f"[TTS] ⚠️ Kokoro model files missing at {self.model_path}. Fallback to Piper.")
        except Exception as e:
            print(f"[TTS] ⚠️ Kokoro init failed: {e}. Fallback to Piper.")

    def synthesize_pcm16(self, text: str, voice: str = None) -> tuple[bytes, float]:
        """Synthesizes text into 16kHz mono 16-bit PCM bytes in memory."""
        if not self._initialized or self.kokoro is None:
            raise RuntimeError("Kokoro TTS is not initialized")

        v = voice or self.default_voice
        t0 = time.perf_counter()

        samples, sample_rate = self.kokoro.create(
            text,
            voice=v,
            speed=1.0,
            lang="en-us",
        )
        synthesis_time = time.perf_counter() - t0

        # Apply 15% headroom scaling to eliminate digital clipping
        samples = samples * 0.85

        # Polyphase FIR resampling: 24kHz -> 16kHz
        if sample_rate == 24000:
            samples_16k = scipy.signal.resample_poly(samples, 2, 3)
        else:
            num_target_samples = int(len(samples) * 16000 / sample_rate)
            samples_16k = scipy.signal.resample(samples, num_target_samples)

        audio_int16 = (np.clip(samples_16k, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        return audio_int16, synthesis_time

    def speak_to_websocket(
        self,
        text: str,
        ws_source,
        interrupt_event=None,
    ) -> None:
        """Stream audio over WebSocket in fast 20ms frames."""
        import asyncio

        print(f"🤖 AI (Meet - Kokoro): {text}")

        try:
            pcm_data, synth_sec = self.synthesize_pcm16(text)
        except Exception as e:
            logger.error(f"Kokoro synthesis failed: {e}, text='{text}'")
            return

        ws = ws_source._ws
        loop = ws_source._loop

        if ws is None or loop is None:
            return

        FRAME_BYTES = 640        # 20ms @ 16kHz mono int16
        FRAME_DURATION = 0.020    # 20ms
        PREBUFFER_FRAMES = 5      # 100ms initial burst to pre-fill PulseAudio

        buf = pcm_data
        seq = 0
        frames_sent = 0
        send_start = time.perf_counter()

        while buf:
            if interrupt_event is not None and interrupt_event.is_set():
                logger.info("[TTS] Meet playback cut short — interrupted.")
                break

            chunk = buf[:FRAME_BYTES]
            buf = buf[FRAME_BYTES:]

            if len(chunk) < FRAME_BYTES:
                chunk = chunk + b"\x00" * (FRAME_BYTES - len(chunk))

            header = struct.pack(">I", seq)
            seq += 1
            frame = header + chunk

            future = asyncio.run_coroutine_threadsafe(ws.send(frame), loop)
            try:
                future.result(timeout=1.0)
                frames_sent += 1
            except Exception:
                break

            # Buffer priming: burst first 5 frames, then pace at exact 20ms intervals
            if frames_sent > PREBUFFER_FRAMES:
                target_time = send_start + ((frames_sent - PREBUFFER_FRAMES) * FRAME_DURATION)
                sleep_sec = target_time - time.perf_counter()
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

    def speak(self, text: str, interrupt_event=None):
        import pyaudio
        print(f"🤖 AI (Kokoro): {text}")
        try:
            pcm_16k, _ = self.synthesize_pcm16(text)
        except Exception as e:
            logger.error(f"Kokoro local speak error: {e}")
            return

        pa = pyaudio.PyAudio()
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, output=True)
        chunk_size = 1024
        for i in range(0, len(pcm_16k), chunk_size):
            if interrupt_event and interrupt_event.is_set():
                break
            stream.write(pcm_16k[i : i + chunk_size])
        stream.stop_stream()
        stream.close()
        pa.terminate()

    def close(self):
        pass


class PiperTTS:
    def __init__(self):
        import pyaudio
        self.pa = pyaudio.PyAudio()

    def speak(self, text: str, interrupt_event=None):
        import subprocess
        import wave
        piper_cmd = [config.PIPER_EXE, "--model", config.PIPER_MODEL_PATH, "--output_file", config.TEMP_WAV_PATH]
        try:
            subprocess.run(piper_cmd, input=text.encode("utf-8"), check=True)
            with wave.open(config.TEMP_WAV_PATH, "rb") as wf:
                stream = self.pa.open(format=self.pa.get_format_from_width(wf.getsampwidth()), channels=wf.getnchannels(), rate=wf.getframerate(), output=True)
                data = wf.readframes(1024)
                while data:
                    if interrupt_event and interrupt_event.is_set():
                        break
                    stream.write(data)
                    data = wf.readframes(1024)
                stream.stop_stream()
                stream.close()
        except Exception as e:
            logger.error(f"Piper error: {e}")

    def speak_to_websocket(self, text: str, ws_source, interrupt_event=None):
        pass

    def close(self):
        self.pa.terminate()