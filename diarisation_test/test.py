import os
import torch
import warnings
warnings.filterwarnings("ignore")

import soundfile as sf
import numpy as np
from pyannote.audio import Pipeline
from faster_whisper import WhisperModel  # ← faster-whisper

# ── Config ────────────────────────────────────────────────────────
TOKEN      = "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"
AUDIO_FILE = "sample.wav"
WHISPER_MODEL = "large-v3-turbo"  # or "turbo" if you have that one

# ── Validate audio file ───────────────────────────────────────────
if not os.path.exists(AUDIO_FILE):
    print(f"ERROR: '{AUDIO_FILE}' not found!")
    print(f"Current folder: {os.getcwd()}")
    print(f"Files here: {os.listdir('.')}")
    raise SystemExit(1)

# ── Device ───────────────────────────────────────────────────────
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
compute_type = "float16" if device.type == "cuda" else "int8"
print(f"Using device: {device}, compute_type: {compute_type}")

# ── Load Diarization Pipeline ────────────────────────────────────
print("Loading diarization pipeline...")
pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    token=TOKEN,
)
pipeline.to(device)
print("Diarization pipeline ready!")

# ── Load Faster-Whisper Model ────────────────────────────────────
print(f"Loading faster-whisper '{WHISPER_MODEL}'...")
whisper_model = WhisperModel(
    WHISPER_MODEL,
    device=device.type,
    compute_type=compute_type,
)
print("Whisper ready!")

# ── Load full audio ──────────────────────────────────────────────
print(f"\nLoading audio: {AUDIO_FILE}")
audio_data, sample_rate = sf.read(AUDIO_FILE, dtype='float32')
print(f"  Shape: {audio_data.shape}, Sample rate: {sample_rate}Hz")

# Ensure mono
if audio_data.ndim == 2:
    audio_data = audio_data.mean(axis=1)
    print("  Converted to mono")

# Torch tensor for pyannote
waveform = torch.from_numpy(audio_data).float().unsqueeze(0)

# Resample to 16kHz if needed
if sample_rate != 16000:
    import torchaudio.transforms as T
    resampler = T.Resample(sample_rate, 16000)
    waveform = resampler(waveform)
    audio_data = np.array(waveform.squeeze().numpy(), dtype=np.float32)
    sample_rate = 16000
    print("  Resampled to 16kHz")
else:
    audio_data = audio_data.astype(np.float32)

audio_input = {
    "waveform": waveform,
    "sample_rate": sample_rate
}

# ── Run Diarization ──────────────────────────────────────────────
print("\nRunning diarization...")
diarization_output = pipeline(audio_input)
diarization = diarization_output.speaker_diarization

# ── Transcribe Each Speaker Segment ──────────────────────────────
print("\n" + "="*70)
print("DIARIZATION + TRANSCRIPTION")
print("="*70 + "\n")

results = []
for turn, _, speaker in diarization.itertracks(yield_label=True):
    start_time = turn.start
    end_time   = turn.end

    # Extract segment
    start_sample = int(start_time * sample_rate)
    end_sample   = int(end_time   * sample_rate)
    segment = audio_data[start_sample:end_sample]

    # Transcribe with faster-whisper
    if len(segment) < sample_rate * 0.3:
        text = "[too short]"
    else:
        segments_iter, info = whisper_model.transcribe(
            segment,
            beam_size=5,
            vad_filter=False,  # we already have VAD
            language="en",      # or None for auto-detect
        )
        # Collect all text
        text_parts = [seg.text for seg in segments_iter]
        text = " ".join(text_parts).strip() or "[no speech detected]"

    print(f"[{start_time:6.2f}s - {end_time:6.2f}s] {speaker}:")
    print(f"  {text}\n")

    results.append({
        "speaker": speaker,
        "start": start_time,
        "end": end_time,
        "text": text,
    })

# ── Summary ──────────────────────────────────────────────────────
print("="*70)
speakers = sorted(set(r["speaker"] for r in results))
print(f"Total speakers: {len(speakers)}")
print(f"Total segments: {len(results)}")
print(f"Speakers: {', '.join(speakers)}")
print("="*70)

# ── Save to file ─────────────────────────────────────────────────
with open("transcript.txt", "w", encoding="utf-8") as f:
    for r in results:
        f.write(f"[{r['start']:.2f}s - {r['end']:.2f}s] {r['speaker']}:\n")
        f.write(f"  {r['text']}\n\n")
print("\nTranscript saved to: transcript.txt")