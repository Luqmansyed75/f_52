from db.database import Base

import uuid
from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB


class Meeting(Base):
    __tablename__ = "meetings"

    meeting_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title    = Column(Text, nullable=True)
    summary  = Column(Text, nullable=True)
    insights = Column(JSONB, nullable=True)  # e.g. {"decisions": [], "risks": []}
