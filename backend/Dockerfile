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
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY backend/requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy entire project into container
# meet_main.py imports from asr/, audio/, core/, etc.
# so the whole repo root needs to be at /app
COPY . /app

# Piper binary and model (mounted at runtime via docker-compose volume)
# so we don't bake them into the image

ENV PYTHONPATH=/app

CMD ["python3", "/app/backend/meet_main.py"]