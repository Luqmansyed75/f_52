FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install essential system audio & phonemizer libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    portaudio19-dev \
    libasound2-dev \
    pulseaudio-utils \
    libpulse-dev \
    wget \
    curl \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip3 install --no-cache-dir --upgrade pip

# Install PyTorch CPU using extra-index-url
RUN pip3 install --no-cache-dir --default-timeout=100 \
    torch==2.6.0 \
    torchaudio==2.6.0 \
    --extra-index-url https://download.pytorch.org/whl/cpu

# Install application dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip3 install --no-cache-dir --default-timeout=100 -r /app/backend/requirements.txt

# Create asset directories
RUN mkdir -p /app/assets/kokoro /app/piper

# Download Kokoro-82M ONNX model and voice definitions (~300MB)
RUN curl -sSL -o /app/assets/kokoro/kokoro-v0_19.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx && \
    curl -sSL -o /app/assets/kokoro/voices.json https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.json

# Download Piper binary (fallback engine)
RUN curl -sSL https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz | tar -xz -C /app/piper --strip-components=1

# Download Piper fallback voice model (Hugging Face) using curl -sSL
RUN curl -sSL -o /app/assets/en_US-lessac-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx && \
    curl -sSL -o /app/assets/en_US-lessac-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json

# Copy project code
COPY . /app

EXPOSE 5001

CMD ["python3", "-m", "backend.meet_main"]