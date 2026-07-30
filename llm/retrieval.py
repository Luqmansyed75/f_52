"""
Retrieval — pulls relevant past utterances for a query, so the LLM
answers grounded in what the agent has actually heard rather than pure
model knowledge.

Tries Qdrant semantic search first; falls back to the most recent
Postgres utterances if Qdrant is unavailable or returns nothing.
"""

from memory.db import Database
from memory.vector_store import VectorStore
from core.logger import get_retrieval_logger

logger = get_retrieval_logger()


SUMMARY_KEYWORDS = ["summarize", "summary", "recap", "discussed earlier", "what did we"]
 
def retrieve_context(
    db: Database,
    vector_store: VectorStore,
    session_id: str,
    query_text: str,
    top_k: int = 5,
) -> str:
    """
    Returns a formatted context string ready to insert into an LLM
    prompt, e.g.:

        Relevant things said earlier in this session:
        - "we need the report by Friday"
        - "the client meeting got moved to 3pm"
    """
    is_summary_request = any(kw in query_text.lower() for kw in SUMMARY_KEYWORDS)
    logger.info("Retrieval query: '%s' (is_summary=%s, top_k=%d)", query_text, is_summary_request, top_k)
    
    if is_summary_request:
        recent = db.get_recent_utterances(session_id, limit=15)  # wider window for summaries
        if not recent:
            logger.debug("No recent utterances found for summary")
            return ""
        logger.info("Retrieved %d recent utterances for summary", len(recent))
        lines = [f'- {u["speaker"]}: "{u["text"]}"' for u in recent]
        return "Recent conversation history:\n" + "\n".join(lines)

    results = vector_store.search(session_id, query_text, top_k=top_k)

    if results:
        logger.info("Qdrant returned %d results", len(results))
        for r in results:
            logger.debug("Retrieved memory (score=%.3f): %s", r.get("score", 0.0), r["text"])
        lines = [f'- "{r["text"]}"' for r in results]
        header = "Relevant things said earlier in this session:"
    else:
        logger.info("Qdrant returned 0 results, falling back to chronological history")
        # Fallback: most recent utterances, chronological.
        recent = db.get_recent_utterances(session_id, limit=top_k)
        if not recent:
            logger.debug("No fallback utterances found")
            return ""
        logger.info("Retrieved %d recent fallback utterances", len(recent))
        lines = [f'- {u["speaker"]}: "{u["text"]}"' for u in recent]
        header = "Recent conversation history:"

    return header + "\n" + "\n".join(lines)


if __name__ == "__main__":
    # Quick smoke test — requires Postgres and Qdrant running
    db = Database()
    vs = VectorStore()

    sid = db.create_session()
    u1 = db.insert_utterance(sid, "we need the report by Friday")
    vs.upsert_utterance(u1, sid, "we need the report by Friday")
    u2 = db.insert_utterance(sid, "let's grab lunch at noon")
    vs.upsert_utterance(u2, sid, "let's grab lunch at noon")

    context = retrieve_context(db, vs, sid, "when is the deadline?")
    print(context)

    db.close()


