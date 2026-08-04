# 🎙️ Proxy Agent – AI Meeting Representative

An event-driven AI Meeting Representative that listens to meetings in real time, understands conversations, retrieves relevant meeting context, and responds naturally through speech.

The system is built around a modular architecture where each capability communicates through an internal EventBus, allowing new components such as Memory and Reasoning to be added independently without modifying the core audio pipeline.

---

# Architecture

```
                 ┌──────────────────────┐
                 │   Microphone Input   │
                 └──────────┬───────────┘
                            │
                     Voice Activity Detection
                      (Silero VAD)
                            │
                            ▼
                  Faster Whisper ASR
                            │
                            ▼
                  Transcript Assembler
                            │
                            ▼
                    Wake Word Detection
                            │
                  Session Management
                            │
                            ▼
                 Semantic Retrieval
                     (Qdrant)
                            │
                            ▼
                     LLM (Groq)
                            │
                            ▼
                    Piper Text-to-Speech
```

The entire pipeline is coordinated through an internal **NATS JetStream EventBus**, enabling loosely coupled communication between modules.

---

# Current Features

## Audio Pipeline

* Real-time microphone streaming
* Multi-consumer audio streaming
* Voice Activity Detection (Silero VAD)
* Faster Whisper Large V3 Turbo
* Transcript assembly
* Wake-word detection
* Conversation session management
* Barge-in support (interrupt AI speech)

---

## AI Components

* Context-aware conversation
* Semantic retrieval using Qdrant
* Speaker diarization
* Streaming LLM responses
* Piper Text-to-Speech

---

## Infrastructure

* Event-driven architecture
* NATS JetStream EventBus
* Docker support
* Structured logging
* Centralized error handling
* Modular design for independent development

---

# Current Project Structure

```
audio/
asr/
core/
llm/
meeting/
memory/
streaming/
tts/
utils/

main.py
config.py
requirements.txt
docker-compose.yml
```

---

# Technology Stack

## AI Models

* Faster Whisper Large V3 Turbo
* Silero VAD
* Pyannote Speaker Diarization
* Pyannote Embeddings
* sentence-transformers/all-mpnet-base-v2
* Groq LLM
* Piper TTS

---

## Infrastructure

* Python 3.10+
* Docker
* NATS JetStream
* Qdrant Vector Database
* Hugging Face
* CUDA (Recommended)

---

# Requirements

* Python 3.10+
* Git
* Docker Desktop
* NVIDIA GPU (Recommended)
* CUDA 12.x (Recommended)

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

## Environment Variables

Create a `.env` file in the project root.

```env
GROQ_API_KEY=YOUR_GROQ_API_KEY
HF_TOKEN=YOUR_HUGGINGFACE_TOKEN
```

---

# Docker Services

Start the required services.

```bash
docker compose up -d
```

Verify:

```bash
docker ps
```

---

# Hugging Face Authentication

Either login:

```bash
huggingface-cli login
```

or provide

```env
HF_TOKEN=YOUR_TOKEN
```

inside the `.env` file.

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

# Developer Integration

The project is intentionally modular.

Two major components are currently under active development by separate contributors.

## 1. Memory Service

Responsibilities:

* Long-term conversation memory
* Meeting memory persistence
* Cross-session retrieval
* Memory summarization
* Vector indexing

The service should subscribe and publish through the EventBus without modifying the existing audio pipeline.

---

## 2. Reasoning Service

Responsibilities:

* Multi-step reasoning
* Planning
* Tool orchestration
* Context refinement
* Response verification

The reasoning layer should consume events after retrieval and before LLM generation.

---

# Event Flow

```
Microphone
      │
      ▼
Voice Activity Detection
      │
      ▼
Speech Recognition
      │
      ▼
Transcript Created
      │
      ▼
Transcript Ready
      │
      ▼
Wake Word Detection
      │
      ▼
Session Manager
      │
      ▼
Memory Retrieval
      │
      ▼
Reasoning Layer
      │
      ▼
LLM
      │
      ▼
Text-to-Speech
```

---

# Future Development Endpoints

## Memory

**Status:** Under Development

Responsibilities

* Long-term storage
* Meeting history
* Semantic memory
* Session persistence

---

## Reasoning

**Status:** Under Development

Responsibilities

* Multi-step planning
* Agent reasoning
* Tool execution
* Context refinement

---

# Testing

Run individual components:

```bash
python test_pipeline.py

python test_whisper.py

python test_main.py
```

---

# Notes

* Docker must be running before starting the application.
* AI models are downloaded automatically during the first launch.
* GPU acceleration is strongly recommended.
* Some Hugging Face models require accepting their license before download.
* The EventBus architecture allows independent feature development without changing the existing pipeline.

---

# Current Status

✅ Real-time Audio Pipeline

✅ EventBus Architecture

✅ Wake Word Detection

✅ Session Management

✅ Semantic Retrieval

✅ Groq Integration

✅ Piper TTS

✅ Barge-in Support

🚧 Memory Service (In Progress)

🚧 Reasoning Service (In Progress)

---

# License

This project is intended for research and educational purposes.
