"""
schemas/__init__.py

Public surface of the schemas package.

Import any schema directly from `schemas`:

    from schemas import Transcript, AudioChunk, LLMResponse, ...

All schema classes are re-exported here so consumers never need to
know which sub-module a particular class lives in.
"""

from schemas.base import SchemaBase

from schemas.audio import AudioChunk, AudioSegment

from schemas.transcript import Transcript

from schemas.memory import RetrievedMemory

from schemas.llm import ChatMessage, LLMRequest, LLMResponse

from schemas.response import LLMResponse  # noqa: F811 — intentional re-export

from schemas.events import (
    TranscriptCreatedEvent,
    ResponseGeneratedEvent,
    RawTranscriptEvent,
    MentionDetectedEvent,
)

from schemas.session import Session

__all__ = [
    # Base
    "SchemaBase",
    # Audio
    "AudioChunk",
    "AudioSegment",
    # Transcript
    "Transcript",
    # Memory
    "RetrievedMemory",
    # LLM
    "ChatMessage",
    "LLMRequest",
    "LLMResponse",
    # Events
    "TranscriptCreatedEvent",
    "ResponseGeneratedEvent",
    "RawTranscriptEvent",
    "MentionDetectedEvent",
    # Session
    "Session",
]
