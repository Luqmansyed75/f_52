from collections import deque
import threading
from queue import Queue, Empty


class AudioConsumer:
    """
    Independent consumer of the shared microphone stream.
    """

    def __init__(self):
        self.queue = Queue()

    def push(self, frame: bytes):
        self.queue.put(frame)

    def read(self, timeout=None):
        try:
            return self.queue.get(timeout=timeout)
        except Empty:
            return None


class RingBuffer:
    """
    Shared audio publisher.

    Every consumer receives every microphone frame exactly once.

    Mic
      │
      ▼
    RingBuffer
      ├── Segmenter
      ├── InterruptWatcher
      ├── Recorder
      └── Future consumers
    """

    def __init__(self, max_frames=1000):

        self.buffer = deque(maxlen=max_frames)

        self.lock = threading.Lock()

        self.consumers = []

    def subscribe(self):

        consumer = AudioConsumer()

        with self.lock:
            self.consumers.append(consumer)

        return consumer

    def unsubscribe(self, consumer):

        with self.lock:
            if consumer in self.consumers:
                self.consumers.remove(consumer)

    def write(self, frame: bytes):

        with self.lock:
            self.buffer.append(frame)
            consumers = tuple(self.consumers)

        for consumer in consumers:
            consumer.push(frame)

    def get_audio_bytes(self):

        with self.lock:
            return b"".join(self.buffer)

    def clear(self):

        with self.lock:
            self.buffer.clear()

    def size(self):

        with self.lock:
            return len(self.buffer)     