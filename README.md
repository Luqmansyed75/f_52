# 🎙️ Proxy Agent – AI Meeting Representative

An AI-powered voice meeting assistant capable of listening to conversations, transcribing speech in real time, maintaining conversational context, retrieving relevant meeting information, and responding naturally using speech.

The project combines speech recognition, meeting memory, semantic retrieval, large language models, speaker diarization, and text-to-speech into a real-time conversational assistant.

---

# Features

## ✅ Implemented

- Real-time microphone streaming
- Voice Activity Detection (Silero VAD)
- Real-time Speech-to-Text (Faster Whisper Large V3 Turbo)
- Speaker Diarization (Pyannote)
- Meeting Memory
- Semantic Search using Qdrant
- Conversation Memory
- Context-aware Question Answering
- LLM Integration (Groq)
- Text-to-Speech (Piper)
- Barge-in (Interrupt AI while speaking)
- Session Management
- Low-latency streaming pipeline
- Multi-consumer audio streaming
- Logging & Error Handling

---

# Technology Stack

## AI Models

- Faster Whisper Large V3 Turbo
- Pyannote Speaker Diarization
- Pyannote Embeddings
- Silero VAD
- sentence-transformers/all-mpnet-base-v2
- Groq LLM
- Piper TTS

---

## Infrastructure

- Python 3.10+
- Docker
- Qdrant
- Hugging Face
- PyTorch
- CUDA (Recommended)

---

# Project Structure

```
audio/
asr/
core/
llm/
memory/
meeting/
streaming/
tts/
utils/
```

---

# Requirements

- Python 3.10+
- Git
- Docker Desktop
- NVIDIA GPU (Recommended)
- CUDA 12.x (Recommended)

---

# Installation

## Clone Repository

```bash
git clone <repository_url>

cd <repository_name>
```

---

## Create Virtual Environment

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

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Create .env

Create a `.env` file in the project root.

```env
GROQ_API_KEY=YOUR_GROQ_API_KEY
HF_TOKEN=YOUR_HUGGINGFACE_TOKEN
```

---

## Install Docker

```bash
docker --version

docker compose version
```

---

## Start Required Services

```bash
docker compose up -d
```

Verify:

```bash
docker ps
```

---

# Models

The following models are downloaded automatically during the first run.

### Speech Recognition

- Faster Whisper Large V3 Turbo

### Voice Activity Detection

- Silero VAD

### Speaker Diarization

- Pyannote Speaker Diarization
- Pyannote Embedding

### Embeddings

- sentence-transformers/all-mpnet-base-v2

### Text-to-Speech

#### Piper

Download a Piper voice model (example):

```
en_US-lessac-medium.onnx
en_US-lessac-medium.onnx.json
```

Place both files inside the configured Piper model directory.

#### MMS TTS

Automatically downloaded from Hugging Face when required.

---

# Hugging Face Authentication

Either

```bash
huggingface-cli login
```

or specify

```env
HF_TOKEN=YOUR_TOKEN
```

inside `.env`.

---

# Running

```bash
python main.py
```

Expected output:

```
Loading models and services...

✅ Model + service loading time: ...

--- 🟢 SYSTEM READY. Start talking! ---
```

---

# Testing

Run individual tests:

```bash
python test_main.py

python test_pipeline.py

python test_whisper.py
```

---

# Updating

```bash
git pull origin main
```

---

# Current Capabilities

- Real-time speech transcription
- Meeting-aware conversation
- Semantic retrieval from meeting history
- Natural voice responses
- Speaker diarization
- Interrupt AI speech (Barge-in)
- Conversation memory
- Low-latency streaming

---

# Notes

- Keep Docker running before starting the project.
- The first launch downloads AI models automatically.
- GPU acceleration is strongly recommended.
- Ensure valid API keys are available in the `.env` file.
- Some models require acceptance of Hugging Face license terms before download.