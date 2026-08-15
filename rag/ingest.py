import chromadb
from sentence_transformers import SentenceTransformer

# --- Models & Clients ---
embed_model = SentenceTransformer("all-MiniLM-L6-v2")
chroma_client = chromadb.PersistentClient(path=".chroma")
collection = chroma_client.get_or_create_collection(
    name="meeting",
    metadata={"hnsw:space": "cosine"},
)


# --- Helpers ---

def parse_utterance(utterance: str) -> tuple[str, str]:
    """
    Split 'Speaker 1: hi this is luqman' → ('Speaker 1', 'hi this is luqman').
    Falls back to ('unknown', full_text) if no colon found.
    """
    if ":" in utterance:
        speaker, text = utterance.split(":", 1)
        return speaker.strip(), text.strip()
    return "unknown", utterance.strip()


# --- Core Functions ---

def generate_embeddings(utterances: list[str]) -> list[list[float]]:
    """
    Embed a list of utterance strings.
    Each utterance is embedded as-is (speaker name included in the text).
    Returns a list of 384-dim float vectors.
    """
    vectors = embed_model.encode(utterances, convert_to_numpy=True)
    return vectors.tolist()


def store_in_chroma(utterances: list[str], sequence_start: int = 0) -> None:
    """
    Store a batch of utterances into ChromaDB.
    Each utterance in the list becomes exactly one chunk/document.

    Args:
        utterances:     e.g. ["Speaker 1: hi this is luqman", "Speaker 2: how are you"]
        sequence_start: offset for IDs (useful when ingesting multiple batches)
    """
    embeddings = generate_embeddings(utterances)

    for i, (utterance, embedding) in enumerate(zip(utterances, embeddings)):
        speaker, _ = parse_utterance(utterance)

        collection.upsert(
            ids=[str(sequence_start + i)],
            documents=[utterance],          # "Speaker 1: hi this is luqman"
            embeddings=[embedding],
            metadatas=[{"speaker": speaker}],
        )
