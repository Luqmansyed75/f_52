import sounddevice as sd
import soundfile as sf

SAMPLE_RATE = 16000
CHANNELS = 1

print("Recording...")
print("Press Enter to stop recording.")

recording = []

def callback(indata, frames, time, status):
    if status:
        print(status)
    recording.append(indata.copy())

with sd.InputStream(
    samplerate=SAMPLE_RATE,
    channels=CHANNELS,
    callback=callback,
):
    input()

audio = __import__("numpy").concatenate(recording, axis=0)

sf.write("sample.wav", audio, SAMPLE_RATE)

print("Saved as sample.wav")