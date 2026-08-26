"""
Text-to-speech module — supports:
1. PiperTTS (Ultra-fast ~30ms in-memory C++ engine, FIR-resampled, crackle-free)
2. KokoroTTS (Neural human voice)
"""

import audioop
import os
import struct
import subprocess
import time
import wave
import numpy as np
import scipy.signal
from core.logger import get_tts_logger
import config

logger = get_tts_logger()


class PiperTTS:
    """Ultra-fast, lightweight Piper C++ TTS Engine with FIR resampling & in-memory processing."""

    def __init__(self):
        self.piper_exe = getattr(config, "PIPER_EXE", "/app/piper/piper")
        self.model_path = getattr(config, "PIPER_MODEL_PATH", "/app/assets/en_US-lessac-medium.onnx")
        self.temp_wav = getattr(config, "TEMP_WAV_PATH", "/tmp/tts_out.wav")

    def synthesize_pcm16(self, text: str) -> bytes:
        """Synthesizes text using Piper C++ binary with FIR anti-aliased resampling to 16kHz mono int16."""
        piper_cmd = [
            self.piper_exe,
            "--model", self.model_path,
            "--output_file", self.temp_wav,
        ]

        subprocess.run(
            piper_cmd,
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        with wave.open(self.temp_wav, "rb") as wf:
            src_rate = wf.getframerate()
            src_channels = wf.getnchannels()
            src_width = wf.getsampwidth()
            raw_pcm = wf.readframes(wf.getnframes())

        # Convert raw PCM to float32 numpy array for high-quality FIR processing
        audio_data = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0

        # Downmix stereo to mono if needed
        if src_channels == 2:
            audio_data = audio_data.reshape(-1, 2).mean(axis=1)

        # Apply 15% headroom scaling to prevent digital clipping in WebRTC
        audio_data = audio_data * 0.85

        # Polyphase FIR anti-aliased resampling to 16kHz
        if src_rate == 22050:
            # 22050 -> 16000 (ratio 320 / 441)
            audio_16k = scipy.signal.resample_poly(audio_data, 320, 441)
        elif src_rate == 24000:
            # 24000 -> 16000 (ratio 2 / 3)
            audio_16k = scipy.signal.resample_poly(audio_data, 2, 3)
        elif src_rate != 16000:
            num_samples = int(len(audio_data) * 16000 / src_rate)
            audio_16k = scipy.signal.resample(audio_data, num_samples)
        else:
            audio_16k = audio_data

        pcm_16k = (np.clip(audio_16k, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        return pcm_16k

    def speak_to_websocket(self, text: str, ws_source, interrupt_event=None) -> None:
        """Stream Piper audio over WebSocket in 20ms frames with prebuffering."""
        import asyncio

        print(f"🤖 AI (Meet - Piper): {text}")
        t0 = time.perf_counter()

        try:
            pcm_data = self.synthesize_pcm16(text)
        except Exception as e:
            logger.error(f"Piper synthesis error: {e}")
            return

        synth_time = time.perf_counter() - t0

        ws = ws_source._ws
        loop = ws_source._loop
        if not ws or not loop:
            return

        FRAME_BYTES = 640
        FRAME_DURATION = 0.020
        PREBUFFER_FRAMES = 4  # 80ms smooth jitter buffer

        buf = pcm_data
        seq = 0
        frames_sent = 0
        send_start = time.perf_counter()

        while buf:
            if interrupt_event and interrupt_event.is_set():
                logger.info("[TTS] Playback interrupted.")
                break

            chunk = buf[:FRAME_BYTES]
            buf = buf[FRAME_BYTES:]
            if len(chunk) < FRAME_BYTES:
                chunk += b"\x00" * (FRAME_BYTES - len(chunk))

            header = struct.pack(">I", seq)
            seq += 1
            frame = header + chunk

            future = asyncio.run_coroutine_threadsafe(ws.send(frame), loop)
            try:
                future.result(timeout=1.0)
                frames_sent += 1
            except Exception:
                break

            if frames_sent > PREBUFFER_FRAMES:
                target = send_start + ((frames_sent - PREBUFFER_FRAMES) * FRAME_DURATION)
                sleep_sec = target - time.perf_counter()
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

        logger.info("Piper Meet TTS (synth=%.3fs frames=%d)", synth_time, frames_sent)

    def speak(self, text: str, interrupt_event=None):
        import pyaudio
        print(f"🤖 AI (Piper Local): {text}")
        pcm_16k = self.synthesize_pcm16(text)
        pa = pyaudio.PyAudio()
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, output=True)
        stream.write(pcm_16k)
        stream.stop_stream()
        stream.close()
        pa.terminate()

    def close(self):
        pass


class KokoroTTS:
    """Neural in-memory TTS engine using Kokoro-82M ONNX."""

    def __init__(self, default_voice: str = None):
        self.default_voice = default_voice or os.environ.get("KOKORO_VOICE", "af_bella")
        self.kokoro = None
        self._initialized = False

        base = getattr(config, "BASE_DIR", "/app")
        self.model_path = os.path.join(base, "assets", "kokoro", "kokoro-v0_19.onnx")
        self.voices_path = os.path.join(base, "assets", "kokoro", "voices.json")

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
                logger.warning("Kokoro model files not found")
        except Exception as e:
            print(f"[TTS] ⚠️ Kokoro init failed: {e}. Fallback to Piper.")
            logger.error(f"Kokoro init error: {e}")

    def synthesize_pcm16(self, text: str, voice: str = None) -> tuple[bytes, float]:
        """Synthesizes text into 16kHz mono 16-bit PCM bytes in memory."""
        if not self._initialized or self.kokoro is None:
            raise RuntimeError("Kokoro TTS not initialized")

        v = voice or self.default_voice
        t0 = time.perf_counter()

        samples, sample_rate = self.kokoro.create(text, voice=v, speed=1.0, lang="en-us")
        synth_time = time.perf_counter() - t0

        # Headroom scaling to prevent peak clipping
        samples = samples * 0.85

        # Polyphase FIR resampling 24kHz -> 16kHz
        if sample_rate == 24000:
            samples_16k = scipy.signal.resample_poly(samples, 2, 3)
        else:
            num_target_samples = int(len(samples) * 16000 / sample_rate)
            samples_16k = scipy.signal.resample(samples, num_target_samples)

        audio_int16 = (np.clip(samples_16k, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        return audio_int16, synth_time

    def speak_to_websocket(self, text: str, ws_source, interrupt_event=None) -> None:
        import asyncio

        print(f"🤖 AI (Meet - Kokoro): {text}")
        try:
            pcm_data, synth_sec = self.synthesize_pcm16(text)
        except Exception as e:
            logger.error(f"Kokoro synthesis failed: {e}")
            return

        ws = ws_source._ws
        loop = ws_source._loop
        if not ws or not loop:
            return

        FRAME_BYTES = 640
        FRAME_DURATION = 0.020
        PREBUFFER_FRAMES = 5

        buf = pcm_data
        seq = 0
        frames_sent = 0
        send_start = time.perf_counter()

        while buf:
            if interrupt_event and interrupt_event.is_set():
                logger.info("[TTS] Meet playback interrupted.")
                break

            chunk = buf[:FRAME_BYTES]
            buf = buf[FRAME_BYTES:]
            if len(chunk) < FRAME_BYTES:
                chunk += b"\x00" * (FRAME_BYTES - len(chunk))

            header = struct.pack(">I", seq)
            seq += 1
            frame = header + chunk

            future = asyncio.run_coroutine_threadsafe(ws.send(frame), loop)
            try:
                future.result(timeout=1.0)
                frames_sent += 1
            except Exception:
                break

            if frames_sent > PREBUFFER_FRAMES:
                target = send_start + ((frames_sent - PREBUFFER_FRAMES) * FRAME_DURATION)
                sleep_sec = target - time.perf_counter()
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

        logger.info("Kokoro Meet TTS (synth=%.3fs frames=%d)", synth_sec, frames_sent)

    def speak(self, text: str, interrupt_event=None):
        import pyaudio
        print(f"🤖 AI (Kokoro Local): {text}")
        pcm_16k, _ = self.synthesize_pcm16(text)
        pa = pyaudio.PyAudio()
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, output=True)
        stream.write(pcm_16k)
        stream.stop_stream()
        stream.close()
        pa.terminate()

    def close(self):
        pass