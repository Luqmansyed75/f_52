"""
PostgreSQL session memory — structural storage for every utterance and
generated response, keyed by session.

Install: pip install "psycopg[binary]"
"""

import uuid
from typing import Optional

import psycopg

import config


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS utterances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    speaker TEXT DEFAULT 'unknown',
    text TEXT NOT NULL,
    is_mention BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    triggering_utterance_id UUID REFERENCES utterances(id),
    response_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class Database:
    def __init__(self):
        self.conn = psycopg.connect(config.POSTGRES_DSN, autocommit=True)
        self._ensure_schema()

    def _ensure_schema(self):
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)

    def create_session(self) -> str:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO sessions DEFAULT VALUES RETURNING id;")
            return str(cur.fetchone()[0])

    def insert_utterance(
        self,
        session_id: str,
        text: str,
        speaker: str = "unknown",
        is_mention: bool = False,
    ) -> str:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO utterances (session_id, speaker, text, is_mention)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (session_id, speaker, text, is_mention),
            )
            return str(cur.fetchone()[0])

    def insert_response(
        self,
        session_id: str,
        response_text: str,
        triggering_utterance_id: Optional[str] = None,
    ) -> str:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO responses (session_id, triggering_utterance_id, response_text)
                VALUES (%s, %s, %s)
                RETURNING id;
                """,
                (session_id, triggering_utterance_id, response_text),
            )
            return str(cur.fetchone()[0])

    def get_recent_utterances(self, session_id: str, limit: int = 10) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT speaker, text, created_at
                FROM utterances
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s;
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
            return [
                {"speaker": r[0], "text": r[1], "created_at": r[2]}
                for r in reversed(rows)  # chronological order
            ]

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    # Quick smoke test
    db = Database()
    sid = db.create_session()
    print("Created session:", sid)
    uid = db.insert_utterance(sid, "hello, testing the db module")
    print("Inserted utterance:", uid)
    print("Recent utterances:", db.get_recent_utterances(sid))
    db.close()
