import re
from sqlalchemy import text
from db.database import engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_name(meeting_id: str) -> str:
    """
    Convert a UUID string to a valid PostgreSQL table name.
    e.g. '3f2a1b4c-...' → 'transcripts_3f2a1b4c_...'
    """
    safe = re.sub(r"[^a-zA-Z0-9]", "_", str(meeting_id))
    return f"transcripts_{safe}"


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

async def create_transcript_table(meeting_id: str) -> None:
    """
    Create the transcript table for a meeting if it doesn't already exist.
    Call this once when a new meeting session starts.
    """
    table = _table_name(meeting_id)
    async with engine.begin() as conn:
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id          BIGSERIAL PRIMARY KEY,
                meeting_id  UUID REFERENCES meetings(meeting_id),
                speaker     VARCHAR(100),
                text        TEXT,
                timestamp   TIMESTAMP DEFAULT NOW()
            )
        """))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def insert_utterance(
    meeting_id: str,
    speaker: str,
    text_content: str,
) -> None:
    """Insert a single utterance row into the meeting's transcript table."""
    table = _table_name(meeting_id)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"""
                INSERT INTO {table} (meeting_id, speaker, text)
                VALUES (:meeting_id, :speaker, :text)
            """),
            {"meeting_id": meeting_id, "speaker": speaker, "text": text_content},
        )


async def get_transcript(meeting_id: str) -> list[dict]:
    """
    Fetch all utterances for a meeting ordered by timestamp.
    Returns a list of dicts: {id, speaker, text, timestamp}
    """
    table = _table_name(meeting_id)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(f"""
                SELECT id, speaker, text, timestamp
                FROM {table}
                ORDER BY timestamp ASC
            """)
        )
        return [dict(row._mapping) for row in result]
