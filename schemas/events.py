"""
schemas/events.py

Event payload schemas for the NATS JetStream event bus.

These schemas represent the structured payloads published and consumed
via EventBus.publish() / EventBus.subscribe().
"""

from __future__ import annotations

from schemas.base import SchemaBase
from schemas.transcript import Transcript


class TranscriptCreatedEvent(SchemaBase):
    """
    Published to SUBJECT_TRANSCRIPT_CREATED when the ASR worker produces
    a new utterance.

    Attributes
    ----------
    transcript : Transcript
        The full transcribed utterance.
    """

    transcript: Transcript


class ResponseGeneratedEvent(SchemaBase):
    """
    Published to SUBJECT_RESPONSE_GENERATED after the LLM produces a
    complete reply and it has been stored in the database.

    Attributes
    ----------
    session_id : str
        Identifier of the active session.
    triggering_utterance_id : str
        Utterance ID that caused this response to be generated.
    response_text : str
        The full LLM-generated reply text.
    timestamp : float
        Unix timestamp (seconds) when the response was finalised.
    """

    session_id: str
    triggering_utterance_id: str
    response_text: str
    timestamp: float


class RawTranscriptEvent(SchemaBase):
    """
    Published to SUBJECT_TRANSCRIPT_CREATED by the main loop after the
    ASR worker produces text.

    This is the raw EventBus wire payload — NOT a database entity.
    It carries only the fields available immediately after ASR, before
    DB insertion, mention detection, or diarisation.

    Attributes
    ----------
    session_id : str
        Identifier of the active session.
    text : str
        ASR-transcribed speech text.
    speaker : str
        Speaker label at publish time (typically "unknown").
    timestamp : float
        Unix timestamp when the utterance was captured.
    asr_seconds : float
        ASR processing latency in seconds.
    """

    session_id: str
    text: str
    speaker: str
    timestamp: float
    asr_seconds: float


class MentionDetectedEvent(SchemaBase):
    """
    Published to SUBJECT_MENTION_DETECTED inside worker() when a
    trigger phrase is detected and the agent should respond.

    Attributes
    ----------
    session_id : str
        Identifier of the active session.
    utterance_id : str
        UUID of the DB-inserted utterance that triggered the mention.
    text : str
        The transcribed text that contained the trigger phrase.
    timestamp : float
        Unix timestamp forwarded from the originating RawTranscriptEvent.
    """

    session_id: str
    utterance_id: str
    text: str
    timestamp: float
