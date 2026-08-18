FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# System deps
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    portaudio19-dev \
    libsndfile1 \
    ffmpeg \
    curl \
    wget \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt

# Install torch separately first — largest download, cache it in its own layer
RUN pip3 install --no-cache-dir --break-system-packages \
    --timeout 300 --retries 5 \
    torch==2.6.0 torchaudio==2.6.0 torchvision==0.21.0

# Install everything else
RUN pip3 install --no-cache-dir --break-system-packages \
    --timeout 300 --retries 5 \
    -r requirements.txt

# Download Linux Piper binary
RUN mkdir -p /app/piper && \
    wget -q --tries=5 --timeout=60 -O /tmp/piper.tar.gz \
    "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz" && \
    tar -xzf /tmp/piper.tar.gz -C /app/piper --strip-components=1 && \
    rm /tmp/piper.tar.gz && \
    chmod +x /app/piper/piper && \
    echo "Piper binary installed:" && \
    ls -lh /app/piper/piper

# Download Piper voice model
RUN mkdir -p /app/assets && \
    wget -q --tries=5 --timeout=120 \
    -O /app/assets/en_US-lessac-medium.onnx \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" && \
    wget -q --tries=5 --timeout=60 \
    -O /app/assets/en_US-lessac-medium.onnx.json \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" && \
    echo "Piper model installed:" && \
    ls -lh /app/assets/

# Copy project files
COPY . /app

ENV PYTHONPATH=/app

CMD ["python3", "/app/backend/meet_main.py"]