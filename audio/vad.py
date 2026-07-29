"""
Voice Activity Detection module — wraps Silero VAD.
Isolated so you can swap detectors (e.g. WebRTC VAD) without touching
the listening loop in audio_io.py.
"""

import torch


class SileroVAD:
    def __init__(self):
        self.model, self.utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
        )
        self.model.eval()

    def reset(self):
        """Call this at the start of each new listening turn."""
        self.model.reset_states()

    def speech_probability(self, audio_tensor: torch.Tensor, sample_rate: int) -> float:
        """Returns a float 0.0-1.0 indicating likelihood this chunk is speech."""
        return self.model(audio_tensor, sample_rate).item()
