"""
schemas/audio.py

Audio-related schemas: raw microphone chunks and VAD-segmented audio.

Both schemas override model_config to allow NumPy arrays, which are
not natively supported by Pydantic's default type system.
"""

from __future__ import annotations

import numpy as np
from pydantic import ConfigDict

from schemas.base import SchemaBase


class AudioChunk(SchemaBase):
    """
    A single raw audio chunk captured from the microphone.

    Attributes
    ----------
    samples : np.ndarray
        Raw PCM samples (float32, mono).
    sample_rate : int
        Samples per second (e.g. 16000).
    timestamp : float
        Unix timestamp (seconds) when the chunk was captured.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        frozen=False,
        populate_by_name=True,
        extra="forbid",
    )

    samples: np.ndarray
    sample_rate: int
    timestamp: float


class AudioSegment(SchemaBase):
    """
    A VAD-delimited audio segment ready for ASR.

    Attributes
    ----------
    audio : np.ndarray
        Float32 mono PCM audio at 16 kHz.
    duration : float
        Length of the segment in seconds.
    start_time : float
        Unix timestamp when the segment begins.
    end_time : float
        Unix timestamp when the segment ends.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        frozen=False,
        populate_by_name=True,
        extra="forbid",
    )

    audio: np.ndarray
    duration: float
    start_time: float
    end_time: float
