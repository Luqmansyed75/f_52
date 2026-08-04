"""
schemas/session.py

Schema representing a meeting session record as stored in PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from schemas.base import SchemaBase


class Session(SchemaBase):
    """
    A meeting session record.

    Attributes
    ----------
    session_id : str
        Unique session identifier (UUID string from the DB).
    created_at : datetime
        When the session was started (matches sessions.started_at).
    expires_at : Optional[datetime]
        When the session will time out. None if no expiry is set
        (matches sessions.ended_at — None means still active).
    """

    session_id: str
    created_at: datetime
    expires_at: Optional[datetime] = None
