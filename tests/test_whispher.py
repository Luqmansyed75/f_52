from faster_whisper import WhisperModel

print("Downloading model...")

model = WhisperModel(
    "large-v3-turbo",
    device="cuda",
    compute_type="float16",
)

print("Model loaded!")