"""
Qdrant vector store — semantic memory over everything the agent has
heard, so it can answer questions grounded in actual session history
rather than pure LLM recall.

Install: pip install qdrant-client sentence-transformers
"""

import uuid
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer

import config


class VectorStore:
    def __init__(self):
        self.client = QdrantClient(url=config.QDRANT_URL)
        self.embedder = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
        self.available = True
        self._ensure_collection()

    def _ensure_collection(self):
        try:
            existing = [c.name for c in self.client.get_collections().collections]
            if config.QDRANT_COLLECTION_NAME not in existing:
                self.client.create_collection(
                    collection_name=config.QDRANT_COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=config.EMBEDDING_DIM, distance=Distance.COSINE
                    ),
                )
        except Exception as e:
            print(f"[vector_store] Could not reach Qdrant — degrading to Postgres-only fallback: {e}")
            self.available = False

    def upsert_utterance(self, utterance_id: str, session_id: str, text: str) -> None:
        if not self.available:
            return
        try:
            embedding = self.embedder.encode(text).tolist()
            self.client.upsert(
                collection_name=config.QDRANT_COLLECTION_NAME,
                points=[
                    PointStruct(
                        id=utterance_id,
                        vector=embedding,
                        payload={"session_id": session_id, "text": text},
                    )
                ],
            )
        except Exception as e:
            print(f"[vector_store] Upsert failed (continuing without it): {e}")

    def search(self, session_id: str, query_text: str, top_k: int = 5) -> list[dict]:
        """
        Returns [] if Qdrant is unavailable or the search fails — callers
        (retrieval.py) should fall back to db.get_recent_utterances in
        that case, not treat [] as "no relevant memories exist."
        """
        if not self.available:
            return []
        try:
            query_vector = self.embedder.encode(query_text).tolist()
            results = self.client.query_points(
                collection_name=config.QDRANT_COLLECTION_NAME,
                query=query_vector,
                query_filter=Filter(
                    must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
                ),
                limit=top_k,
            ).points
            return [{"text": r.payload["text"], "score": r.score} for r in results]
        except Exception as e:
            print(f"[vector_store] Search failed, returning empty (caller should fall back): {e}")
            return []


if __name__ == "__main__":
    # Quick smoke test
    vs = VectorStore()
    sid = str(uuid.uuid4())
    vs.upsert_utterance(str(uuid.uuid4()), sid, "we need the report by Friday")
    vs.upsert_utterance(str(uuid.uuid4()), sid, "let's grab lunch at noon")
    results = vs.search(sid, "when is the deadline?", top_k=3)
    print("Search results:", results)