# 🎙️ Proxy Agent – AI Meeting Representative

## Prerequisites

- Python 3.10+
- Git
- Docker Desktop
- NVIDIA GPU (Recommended)
- CUDA 12.x (Recommended)

---

# 1. Clone the Repository

```bash
git clone <repository_url>

cd <repository_name>
```

---

# 2. Create Virtual Environment

### Windows

```bash
python -m venv test_Agent

test_Agent\Scripts\activate
```

### Linux/macOS

```bash
python3 -m venv test_Agent

source test_Agent/bin/activate
```

---

# 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

---

# 4. Create Environment File

Create a `.env` file in the project root.

Example:

```env
GROQ_API_KEY=YOUR_GROQ_API_KEY
HF_TOKEN=YOUR_HUGGINGFACE_TOKEN
```

---

# 5. Install Docker

Download and install Docker Desktop.

Verify installation:

```bash
docker --version

docker compose version
```

---

# 6. Start Required Services

Run:

```bash
docker compose up -d
```

Verify:

```bash
docker ps
```

---

# 7. Download Required Models

The following models will be downloaded automatically on first run.

## Speech-to-Text

- Faster Whisper Large V3 Turbo

## Voice Activity Detection

- Silero VAD

## Speaker Diarization

- Pyannote Speaker Diarization
- Pyannote Embedding

## Embedding Model

- sentence-transformers/all-mpnet-base-v2

## Text-to-Speech

### Piper

Download the required Piper voice model.

Example:

```
en_US-lessac-medium.onnx
en_US-lessac-medium.onnx.json
```

Place both files inside the project root (or the configured model directory).

### MMS TTS

Downloaded automatically by Hugging Face.

---

# 8. Verify Hugging Face Login (Optional)

```bash
huggingface-cli login
```

or simply provide

```
HF_TOKEN
```

inside the `.env`.

---

# 9. Run the Project

```bash
python main.py
```

If everything is configured correctly, you should see:

```
Loading models and services...

✅ Model + service loading time: ...

--- 🟢 SYSTEM READY. Start talking! ---
```

---

# Project Modules

| Module | Description |
|---------|-------------|
| audio | Audio capture, VAD, denoising |
| asr | Speech-to-Text |
| llm | LLM Routing & Prompting |
| memory | Conversation Memory & Retrieval |
| tts | Text-to-Speech |
| meeting | Meeting Intelligence |
| core | Event Bus & Session Management |

---

# Updating the Repository

```bash
git pull origin main
```

---

# Running Tests

```bash
python test_main.py

python test_pipeline.py

python test_whisper.py
```

---

# Notes

- Keep Docker running before starting the project.
- Ensure the `.env` file contains valid API keys.
- The first run may take several minutes while models are downloaded and cached.