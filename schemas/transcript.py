"""
schemas/transcript.py

Schema for a single transcribed utterance produced by the ASR pipeline.
"""

from __future__ import annotations

from schemas.base import SchemaBase


class Transcript(SchemaBase):
    """
    One transcribed utterance from the ASR worker.

    Attributes
    ----------
    utterance_id : str
        Unique identifier for this utterance (UUID string from the DB).
    session_id : str
        Identifier of the active meeting session.
    speaker : str
        Speaker label (e.g. "unknown" or a diarisation label).
    text : str
        The transcribed speech text.
    language : str
        BCP-47 language code detected by Whisper (e.g. "en").
    confidence : float
        Language detection probability returned by Whisper (0.0 – 1.0).
    is_mention : bool
        True when the utterance contains a trigger phrase directed at the
        agent (determined by mention_detector).
    timestamp : float
        Unix timestamp (seconds) when the utterance was produced.
    """

    utterance_id: str
    session_id: str
    speaker: str
    text: str
    language: str
    confidence: float
    is_mention: bool
    timestamp: float
