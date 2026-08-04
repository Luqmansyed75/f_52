"""
schemas/memory.py

Schema for a single memory entry retrieved from the vector store (Qdrant)
or the relational fallback (PostgreSQL).
"""

from __future__ import annotations

from schemas.base import SchemaBase


class RetrievedMemory(SchemaBase):
    """
    A single piece of meeting context retrieved by the retrieval layer.

    Attributes
    ----------
    utterance_id : str
        Unique identifier of the source utterance (UUID string).
    session_id : str
        Identifier of the session this memory belongs to.
    text : str
        The utterance text retrieved as context.
    score : float
        Semantic similarity score returned by Qdrant (cosine, 0.0 – 1.0).
        A score of 0.0 is used as a sentinel when the result comes from
        the PostgreSQL fallback, which does not produce similarity scores.
    """

    utterance_id: str
    session_id: str
    text: str
    score: float
