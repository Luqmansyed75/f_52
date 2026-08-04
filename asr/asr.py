"""
Speech-to-text module — wraps Faster-Whisper Large-v3 Turbo.
Falls back to CPU automatically if no CUDA GPU is available.
"""

import os
import time
import torch

import config
from faster_whisper import WhisperModel
from huggingface_hub import scan_cache_dir
from core.logger import get_asr_logger

logger = get_asr_logger()


print("HF_HOME:", os.environ.get("HF_HOME"))

try:
    info = scan_cache_dir()
    for repo in info.repos:
        print(repo.repo_id, repo.size_on_disk_str, repo.repo_path)
except Exception as e:
    print("Cache scan failed:", e)


class WhisperASR:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        if self.device == "cuda":
            compute_type = "float16"
        else:
            compute_type = "int8"

        print(f"[ASR] Loading Faster-Whisper ({config.ASR_MODEL_ID})...")
        print(f"[ASR] Device       : {self.device}")
        print(f"[ASR] Compute Type : {compute_type}")

        start = time.perf_counter()

        self.model = WhisperModel(
            config.ASR_MODEL_ID,
            device=self.device,
            compute_type=compute_type,
        )

        print(
            f"[ASR] Model loaded in {time.perf_counter() - start:.3f} sec"
        )
        logger.info("Faster-Whisper model loaded in %.3f sec (device=%s, compute=%s)",
                    time.perf_counter() - start, self.device, compute_type)

    def transcribe(self, audio_np) -> str:
        """
        Parameters
        ----------
        audio_np : np.ndarray
            Float32 mono PCM audio sampled at 16kHz.

        Returns
        -------
        str
            Transcribed text.
        """

        start = time.perf_counter()

        segments, info = self.model.transcribe(
            audio_np,
            language="en",
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            word_timestamps=False,
            initial_prompt="",
        )

        text = " ".join(segment.text.strip() for segment in segments).strip()
        text = _collapse_repetition(text)

        print(f"[ASR] Language      : {info.language}")
        print(f"[ASR] Confidence    : {info.language_probability:.3f}")
        print(f"[ASR] Latency       : {time.perf_counter()-start:.3f} sec")
        
        logger.info("Transcribed text (language=%s, confidence=%.3f, latency=%.3fs): %s",
                    info.language, info.language_probability, time.perf_counter()-start, text)

        return text


def _collapse_repetition(text: str, min_repeats: int = 3) -> str:
    """
    Whisper occasionally hallucinates by repeating the same short
    sentence many times in a row, usually on quiet/ambiguous audio.
    If a sentence repeats min_repeats+ times consecutively, collapse
    it down to a single instance.
    """
    if not text:
        return text

    # Split on sentence-ending punctuation, keeping it simple/robust
    # rather than a full NLP sentence splitter.
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)

    collapsed = []
    i = 0
    while i < len(sentences):
        current = sentences[i]
        repeat_count = 1
        j = i + 1
        while j < len(sentences) and sentences[j].strip().lower() == current.strip().lower():
            repeat_count += 1
            j += 1

        collapsed.append(current)
        if repeat_count >= min_repeats:
            print(f"[ASR] Collapsed {repeat_count}x repeated sentence: '{current}'")
            logger.warning("Collapsed %dx repeated sentence: '%s'", repeat_count, current)
        i = j

    return " ".join(collapsed).strip()