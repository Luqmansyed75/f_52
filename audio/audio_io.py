"""
Microphone I/O: opens the mic stream and listens until a pause is
detected (turn-taking boundary). This is where VAD + denoise are wired
together — ASR/LLM/TTS know nothing about audio capture.
"""

import sys
import numpy as np
import pyaudio
import torch

import config
from audio.denoise import denoise_chunk


class MicListener:
    def __init__(self, vad):
        self.vad = vad
        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=config.CHANNELS,
            rate=config.RATE,
            input=True,
            frames_per_buffer=config.CHUNK,
        )

    def listen_until_pause(self) -> np.ndarray:
        """
        Continuously listens to the microphone. Starts buffering when
        speech is detected and stops after PAUSE_THRESHOLD_FRAMES of
        continuous silence. Returns the full utterance as float32 audio.
        """
        print("\n[🎙️ Listening...]")

        audio_buffer = []
        pending_silence = []

        consecutive_silence = 0
        is_recording = False

        self.vad.reset()

        MAX_RECORD_SECONDS = 40

        max_chunks = (
            MAX_RECORD_SECONDS
            * config.RATE
            // config.CHUNK
        )

        while True:
            data = self.stream.read(config.CHUNK, exception_on_overflow=False)
            audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

            # NOTE: denoising happens once on the full utterance below, not
            # per-chunk here — spectral gating needs more than 32ms of audio
            # to compute a valid STFT window.
            audio_tensor = torch.from_numpy(audio_np)
            speech_prob = self.vad.speech_probability(audio_tensor, config.RATE)

            if len(audio_buffer) >= max_chunks:
                print("\n[⏱ Maximum utterance length reached]")
                pending_silence.clear()
                break

            if speech_prob > config.VAD_SPEECH_THRESHOLD:

                if not is_recording:
                    is_recording = True
                    print("[🎤 Speech detected]")

                # User resumed speaking.
                # Keep the short pause between words.
                if pending_silence:
                    audio_buffer.extend(pending_silence)
                    pending_silence.clear()

                consecutive_silence = 0

                audio_buffer.append(audio_np)
            elif is_recording:

                consecutive_silence += 1

                # Don't immediately commit silence.
                # Hold it temporarily.
                pending_silence.append(audio_np)

            if (
                is_recording
                and consecutive_silence >= config.PAUSE_THRESHOLD_FRAMES
            ):
                print("\n[🔇 Pause Detected]")

                # Don't append pending_silence.
                # Throw it away.
                pending_silence.clear()

                break

        if not audio_buffer:
            return np.array([], dtype=np.float32)

        full_audio = np.concatenate(audio_buffer)

        if config.FEATURES.get("denoise"):
            full_audio = denoise_chunk(full_audio, config.RATE)

        return full_audio

    def open_secondary_stream(self):
        """
        Opens a second, independent input stream on the same device,
        for use by InterruptWatcher. The main listen_until_pause() loop
        and the watcher must not share a single PyAudio stream object —
        concurrent reads from two threads on the same stream corrupt/drop
        frames.
        """
        return self.pa.open(
            format=pyaudio.paInt16,
            channels=config.CHANNELS,
            rate=config.RATE,
            input=True,
            frames_per_buffer=config.CHUNK,
        )

    def close(self):
        self.stream.stop_stream()
        self.stream.close()
        self.pa.terminate()