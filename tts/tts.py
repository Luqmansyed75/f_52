"""
Text-to-speech module — wraps Piper.
Synthesizes to a temp WAV file and plays it back via PyAudio.
(Future upgrade: stream raw PCM from Piper's stdout directly into
the output stream to skip the disk round-trip — see README note.)
"""
import config

import struct
import subprocess
import wave
import pyaudio
import time
from core.logger import get_tts_logger
from core.error_handler import handle_errors

logger = get_tts_logger()


class PiperTTS:
    def __init__(self):
        self.pa = pyaudio.PyAudio()

    @handle_errors(logger)
    def speak(self, text: str, interrupt_event=None):
        print(f"🤖 AI: {text}")

        piper_cmd = [
            config.PIPER_EXE,
            "--model", config.PIPER_MODEL_PATH,
            "--output_file", config.TEMP_WAV_PATH,
        ]

        try:
            tts_start = time.perf_counter()
            subprocess.run(
                piper_cmd,
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            synthesis_end = time.perf_counter()
        except subprocess.CalledProcessError as e:
            print("\n❌ PIPER INTERNAL ERROR:")
            print(e.stderr.decode("utf-8"))
            logger.error("Piper internal error: %s", e.stderr.decode("utf-8"))
            return
        playback_start = time.perf_counter()
        with wave.open(config.TEMP_WAV_PATH, "rb") as wf:
            stream = self.pa.open(
                format=self.pa.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True,
            )
            data = wf.readframes(1024)
            while data:
                if interrupt_event is not None and interrupt_event.is_set():
                    print("[tts] Playback cut short — interrupted.")
                    break
                stream.write(data)
                data = wf.readframes(1024)
            stream.stop_stream()
            stream.close()
            playback_end = time.perf_counter()

            print("\n===== PIPER =====")
            print(f"Synthesis : {synthesis_end-tts_start:.3f} sec")
            print(f"Playback  : {playback_end-playback_start:.3f} sec")
            print(f"Total     : {playback_end-tts_start:.3f} sec")
            print("=================\n")
            logger.info(
                "Piper TTS (Synthesis: %.3f sec, Playback: %.3f sec, Total: %.3f sec)",
                synthesis_end - tts_start,
                playback_end - playback_start,
                playback_end - tts_start,
            )

    def speak_to_websocket(
        self,
        text: str,
        ws_source,
        interrupt_event=None,
    ) -> None:
        """
        Meet mode: synthesise with Piper, then send raw PCM over WebSocket
        to meet-container instead of playing locally.

        ws_source: WebSocketSource instance (has _ws and _loop)
        Audio is resampled to 16kHz mono int16 to match the bridge format.
        """
        import asyncio
        import audioop  # stdlib, available in Python 3.10

        print(f"🤖 AI (Meet): {text}")

        piper_cmd = [
            config.PIPER_EXE,
            "--model", config.PIPER_MODEL_PATH,
            "--output_file", config.TEMP_WAV_PATH,
        ]

        try:
            tts_start = time.perf_counter()
            subprocess.run(
                piper_cmd,
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            synthesis_end = time.perf_counter()
        except subprocess.CalledProcessError as e:
            logger.error("Piper error: %s", e.stderr.decode("utf-8"))
            return

        # Read WAV and resample to 16kHz mono int16 if needed
        FRAME_BYTES = 640  # 20ms @ 16kHz mono int16
        seq = [0]

        with wave.open(config.TEMP_WAV_PATH, "rb") as wf:
            src_rate = wf.getframerate()
            src_channels = wf.getnchannels()
            src_width = wf.getsampwidth()
            raw_pcm = wf.readframes(wf.getnframes())

        # Convert to mono if stereo
        if src_channels == 2:
            raw_pcm = audioop.tomono(raw_pcm, src_width, 0.5, 0.5)

        # Convert sample width to 2 bytes (int16) if needed
        if src_width != 2:
            raw_pcm = audioop.lin2lin(raw_pcm, src_width, 2)

        # Resample to 16kHz if needed
        if src_rate != 16000:
            raw_pcm, _ = audioop.ratecv(
                raw_pcm, 2, 1, src_rate, 16000, None
            )

        # Send in 640-byte frames over WebSocket
        ws = ws_source._ws
        loop = ws_source._loop

        if ws is None or loop is None:
            logger.warning("speak_to_websocket: no active WebSocket, skipping.")
            return

        send_start = time.perf_counter()
        buf = raw_pcm
        frames_sent = 0

        while buf:
            if interrupt_event is not None and interrupt_event.is_set():
                logger.info("[tts] Meet playback cut short — interrupted.")
                break

            chunk = buf[:FRAME_BYTES]
            buf = buf[FRAME_BYTES:]

            # Pad last frame if needed
            if len(chunk) < FRAME_BYTES:
                chunk = chunk + b'\x00' * (FRAME_BYTES - len(chunk))

            header = struct.pack(">I", seq[0])
            seq[0] += 1
            frame = header + chunk

            future = asyncio.run_coroutine_threadsafe(
                ws.send(frame),
                loop,
            )
            try:
                future.result(timeout=1.0)
                frames_sent += 1
            except Exception as e:
                logger.warning(f"WebSocket TTS frame send failed: {e}")
                break

            # Pace sending at ~real-time (20ms per frame)
            # so meet-container doesn't buffer everything at once
            time.sleep(0.018)

        send_end = time.perf_counter()
        logger.info(
            "Piper Meet TTS (synthesis=%.3fs frames=%d send=%.3fs)",
            synthesis_end - tts_start,
            frames_sent,
            send_end - send_start,
        )

    def close(self):
        self.pa.terminate()