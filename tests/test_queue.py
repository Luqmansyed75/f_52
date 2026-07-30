from queue import Queue

from streaming.ring_buffer import RingBuffer
from streaming.mic_listener import MicListener

frame_queue = Queue()
ring_buffer = RingBuffer()

mic = MicListener(
    ring_buffer=ring_buffer,
    frame_queue=frame_queue,
)

mic.start_stream()

try:
    while True:
        frame = frame_queue.get()

        print(
            f"Received frame: {len(frame)} bytes | "
            f"RingBuffer: {ring_buffer.size()} frames"
        )

except KeyboardInterrupt:
    mic.stop_stream()