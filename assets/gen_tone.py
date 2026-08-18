import wave, struct, math
rate, duration, freq = 16000, 5, 440.0
samples = [int(32767 * math.sin(2 * math.pi * freq * t / rate)) for t in range(rate * duration)]
with wave.open('/tmp/tone.wav', 'w') as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(rate)
    f.writeframes(struct.pack('<' + 'h' * len(samples), *samples))
print('Generated /tmp/tone.wav')
