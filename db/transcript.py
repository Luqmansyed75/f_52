from uuid import UUID as PyUUID
from sqlalchemy import select
from db.database import AsyncSessionLocal
from db.models import Transcript


async def insert_utterance(
    meeting_id: str | PyUUID,
    speaker: str,
    text_content: str,
) -> None:
    """Insert a single utterance row into the unified transcripts table."""
    async with AsyncSessionLocal() as session:
        utterance = Transcript(
            meeting_id=meeting_id,
            speaker=speaker,
            text=text_content,
        )
        session.add(utterance)
        await session.commit()


async def get_transcript(meeting_id: str | PyUUID) -> list[dict]:
    """
    Fetch all utterances for a meeting ordered by timestamp.
    Returns a list of dicts: {id, meeting_id, speaker, text, timestamp}
    """
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Transcript)
            .where(Transcript.meeting_id == meeting_id)
            .order_by(Transcript.timestamp.asc())
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": row.id,
                "meeting_id": str(row.meeting_id),
                "speaker": row.speaker,
                "text": row.text,
                "timestamp": row.timestamp,
            }
            for row in rows
        ]

