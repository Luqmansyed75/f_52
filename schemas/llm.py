"""
schemas/llm.py

Schemas for the LLM request/response boundary.

These schemas model the data that flows into and out of the LLM layer
(GroqLLM / LLMRouter) without duplicating any business logic.
"""

from __future__ import annotations

from typing import List, Optional

from schemas.base import SchemaBase


class ChatMessage(SchemaBase):
    """
    A single OpenAI-compatible chat message.

    Attributes
    ----------
    role : str
        One of "system", "user", or "assistant".
    content : str
        The message body.
    """

    role: str
    content: str


class LLMRequest(SchemaBase):
    """
    Structured input to the LLM layer as assembled by PromptBuilder.

    Attributes
    ----------
    user_query : str
        The latest user utterance.
    conversation_history : List[ChatMessage]
        Prior turns in OpenAI message format.
    meeting_context : str
        Retrieved meeting context injected into the system prompt.
    """

    user_query: str
    conversation_history: List[ChatMessage]
    meeting_context: str


class LLMResponse(SchemaBase):
    """
    Structured output from the LLM layer after streaming is complete.

    Attributes
    ----------
    response_text : str
        Full concatenated LLM reply.
    token_count : Optional[int]
        Number of tokens received during streaming (None if not tracked).
    latency : Optional[float]
        End-to-end LLM latency in seconds (None if not tracked).
    """

    response_text: str
    token_count: Optional[int] = None
    latency: Optional[float] = None
