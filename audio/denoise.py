"""
Noise reduction module.

Uses `noisereduce` (spectral gating) as the default — pure Python, no
extra binaries, good enough for steady background noise (fans, hum,
keyboard clatter). Swap in RNNoise later if you need better quality on
non-stationary noise; keep the same function signature so nothing else
in the pipeline needs to change.

Install: pip install noisereduce
"""

import numpy as np

try:
    import noisereduce as nr
    _NOISEREDUCE_AVAILABLE = True
except ImportError:
    _NOISEREDUCE_AVAILABLE = False


def denoise_chunk(audio_np: np.ndarray, sample_rate: int) -> np.ndarray:
    """
    Reduce background noise in a float32 mono audio array (range -1.0 to 1.0).

    Args:
        audio_np: audio samples as float32 numpy array
        sample_rate: sample rate of the audio (e.g. 16000)

    Returns:
        Denoised float32 numpy array, same shape as input.
    """
    if not _NOISEREDUCE_AVAILABLE:
        # Fail open — if the library isn't installed, pass audio through
        # unchanged rather than crashing the whole pipeline.
        return audio_np

    if audio_np.size == 0:
        return audio_np

    try:
        reduced = nr.reduce_noise(y=audio_np, sr=sample_rate, stationary=True)
        return reduced.astype(np.float32)
    except Exception as e:
        print(f"[denoise] Skipped due to error: {e}")
        return audio_np
