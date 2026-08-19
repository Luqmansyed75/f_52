from uuid import uuid4
from sqlalchemy import Column, Text, BigInteger, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from db.database import Base


class Meeting(Base):
    __tablename__ = "meetings"

    meeting_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    title    = Column(Text, nullable=True)
    summary  = Column(Text, nullable=True)
    insights = Column(JSONB, nullable=True)  # e.g. {"decisions": [], "risks": []}


class Transcript(Base):
    __tablename__ = "transcripts"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    meeting_id = Column(UUID(as_uuid=True), ForeignKey("meetings.meeting_id", ondelete="CASCADE"), nullable=False)
    speaker    = Column(String(100), nullable=True)
    text       = Column(Text, nullable=False)
    timestamp  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_transcripts_meeting_time", "meeting_id", "timestamp"),
    )

