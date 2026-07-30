"""
Text-to-speech module — wraps Piper.
Synthesizes to a temp WAV file and plays it back via PyAudio.
(Future upgrade: stream raw PCM from Piper's stdout directly into
the output stream to skip the disk round-trip — see README note.)
"""
import config

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
            logger.info("Piper TTS (Synthesis: %.3f sec, Playback: %.3f sec, Total: %.3f sec)", 
                        synthesis_end-tts_start, playback_end-playback_start, playback_end-tts_start)
    def close(self):
        self.pa.terminate()