import threading
import pyaudio


class MicListener(threading.Thread):
    def __init__(
        self,
        ring_buffer,
        rate=16000,
        channels=1,
        chunk=512,
        sample_format=pyaudio.paInt16,
        device_index=None,
    ):
        super().__init__(daemon=True)

        self.ring_buffer = ring_buffer
        self.rate = rate
        self.channels = channels
        self.chunk = chunk
        self.sample_format = sample_format
        self.device_index = device_index

        self._running = False

        self.audio = pyaudio.PyAudio()
        self.stream = None


    def start_stream(self):
        """Open microphone stream."""

        self.stream = self.audio.open(
            format=self.sample_format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk,
            input_device_index=self.device_index,
        )

        self._running = True
        self.start()

    def run(self):

        while self._running:

            frame = self.stream.read(
                self.chunk,
                exception_on_overflow=False,
            )

            self.ring_buffer.write(frame)

    def stop_stream(self):
        """Stop recording."""

        self._running = False

        if self.stream is not None:
            self.stream.stop_stream()
            self.stream.close()

        self.audio.terminate()

