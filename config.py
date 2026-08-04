"""
Central configuration for the AI Meeting Representative voice agent.
All paths, model IDs, and feature toggles live here so you can change
behavior without touching the module logic.
"""

import os
from dotenv import load_dotenv
load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY not found in environment. "
        "Set it before running (see comment in config.py)."
    )


# PATHS

BASE_DIR = r"C:\Users\Akhil\Desktop\Voice Agent Test"
PIPER_EXE = os.path.join(BASE_DIR, "piper", "piper.exe")
PIPER_MODEL_PATH = os.path.join(BASE_DIR, "assets/en_US-lessac-medium.onnx")
TEMP_WAV_PATH = os.path.join(BASE_DIR, "assets/temp_audio.wav")

# Hugging Face network validation
os.environ["HF_HUB_OFFLINE"] = "1"

# # if you point this elsewhere)
# os.environ.setdefault("HF_HOME", "C:/hf_cache")
# os.environ.setdefault("TRANSFORMERS_CACHE", "C:/hf_cache")
# os.environ.setdefault("HF_DATASETS_CACHE", "C:/hf_cache")

# MODELS

ASR_MODEL_ID = "large-v3-turbo"
LLM_MODEL = "openai/gpt-oss-120b"
DEVICE = "cuda"  # will be overridden to "cpu" automatically if no GPU — see asr.py

OLLAMA_BASE_URL = "http://localhost:11434"
LOCAL_OLLAMA_MODEL = "llama3:latest"

# AUDIO SETTINGS

FORMAT_WIDTH = 2          # pyaudio.paInt16, kept as width for portability
CHANNELS = 1
RATE = 16000
CHUNK = 512
VAD_SPEECH_THRESHOLD = 0.6
PAUSE_THRESHOLD_FRAMES = 25
MAX_RECORD_SECONDS = 20

# FEATURE TOGGLES — flip these on as you build each piece.
# This is the "add one by one" switchboard.

FEATURES = {
    "denoise": True,        # noise reduction before VAD/ASR
    "barge_in": False,      # interrupt AI mid-speech (not yet implemented)
    "diarization": False,   # speaker separation for multi-person audio (not yet)
}

# System prompt for the LLM
SYSTEM_PROMPT = '''
    You are a real-time voice assistant.

Rules:
- Reply only with the final answer.
- Never reveal your reasoning or thought process.
- Never write phrases like:
  - "Let me think"
  - "The user said"
  - "First I need to"
  - "Breaking it down"
  - "I should"
- Do not explain how you arrived at the answer.
- Respond naturally in the user's language.
- Keep replies under 20 words unless the user explicitly asks for details.
- Always answer in English regardless of the input language.
'''

# ------------------------------------------------------------------
# NATS JetStream
# ------------------------------------------------------------------
NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")
NATS_STREAM_NAME = "MEETING_EVENTS"

# Subject constants (used by event_bus.py)
SUBJECT_TRANSCRIPT_CREATED = "meeting.transcript.created"
SUBJECT_MENTION_DETECTED = "meeting.mention.detected"
SUBJECT_RESPONSE_GENERATED = "meeting.response.generated"

# New subjects for turn assembly and session events
SUBJECT_TRANSCRIPT_READY = "meeting.transcript.ready"
SUBJECT_SPEECH_STARTED = "meeting.speech.started"
SUBJECT_SPEECH_ENDED = "meeting.speech.ended"
SUBJECT_TURN_COMPLETED = "meeting.turn.completed"
SUBJECT_SESSION_TOUCHED = "meeting.session.touched"
SUBJECT_SESSION_EXPIRED = "meeting.session.expired"
SUBJECT_LLM_STARTED = "meeting.llm.started"
SUBJECT_LLM_FINISHED = "meeting.llm.finished"
SUBJECT_BARGE_IN = "meeting.bargein.detected"

# ------------------------------------------------------------------
# PostgreSQL
# ------------------------------------------------------------------

POSTGRES_DSN = os.environ.get(
    "POSTGRES_DSN",
    "postgresql://voiceagent:password@localhost:5432/meetings",
)


# ------------------------------------------------------------------
# Qdrant
# ------------------------------------------------------------------
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION_NAME = "utterance_embeddings"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output dimension

# ------------------------------------------------------------------
# Feature toggles
# ------------------------------------------------------------------
FEATURES["always_listening"] = True
FEATURES["mention_detection"] = True

# ------------------------------------------------------------------
# Mention detection — wake phrases (edit to taste)
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# End-of-turn / assembler tuning
# ------------------------------------------------------------------
# Maximum gap (seconds) between consecutive ASR segments to consider
# them part of the same continuous user turn. If two segments are more
# separated than this, the assembler will treat them as distinct.
END_OF_TURN_MAX_GAP = float(os.environ.get("END_OF_TURN_MAX_GAP", 0.8))

# Time to wait (seconds) after the last ASR chunk before finalising
# a turn and emitting a ready transcript. This must be tuned to allow
# short pauses inside a single utterance while still being responsive.
END_OF_TURN_TIMEOUT = float(os.environ.get("END_OF_TURN_TIMEOUT", 1.2))

# Session inactivity window (seconds) used by SessionManager when
# configured for activity-based expiration. Touching the session resets
# this timer.
SESSION_INACTIVITY_SECONDS = int(os.environ.get("SESSION_INACTIVITY_SECONDS", 10))

# When merging consecutive ASR chunks, remove duplicate outputs that
# are identical to the last emitted ready transcript within this window.
DUPLICATE_TRANSCRIPT_WINDOW = float(os.environ.get("DUPLICATE_TRANSCRIPT_WINDOW", 1.0))

WAKE_PHRASES = [
    "hey assistant",
    "hey agent",
    "ai rep",
    "meeting assistant",
    "hey proxy",
    "hi akhil",
]