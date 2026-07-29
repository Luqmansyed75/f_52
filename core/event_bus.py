"""
NATS JetStream event bus — choreography layer for the always-listening
agent.

nats-py is asyncio-native, but the rest of this codebase is synchronous
(matching the existing style in vad.py/asr.py/llm.py). This module runs
a single background event loop in its own thread and exposes plain
synchronous publish()/subscribe() methods on top of it, so main.py
doesn't need to become async.

Install: pip install nats-py
"""

import asyncio
import json
import threading
from typing import Callable

import nats
from nats.js.api import StreamConfig

import config


# Subject constants — import these rather than hardcoding subject
# strings elsewhere in the codebase.
TRANSCRIPT_CREATED = config.SUBJECT_TRANSCRIPT_CREATED
MENTION_DETECTED = config.SUBJECT_MENTION_DETECTED
RESPONSE_GENERATED = config.SUBJECT_RESPONSE_GENERATED


class EventBus:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._nc = None
        self._js = None

        # Block until the connection + stream setup is done, so callers
        # can use publish()/subscribe() immediately after __init__.
        future = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        future.result(timeout=10)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _connect(self):
        self._nc = await nats.connect(config.NATS_URL)
        self._js = self._nc.jetstream()

        try:
            await self._js.add_stream(
                StreamConfig(
                    name=config.NATS_STREAM_NAME,
                    subjects=[
                        TRANSCRIPT_CREATED,
                        MENTION_DETECTED,
                        RESPONSE_GENERATED,
                    ],
                )
            )
        except Exception:
            # Stream likely already exists — fine, idempotent setup.
            pass

    def publish(self, subject: str, payload: dict) -> None:
        """Synchronously publish a JSON-serializable payload to a subject."""
        data = json.dumps(payload).encode("utf-8")
        future = asyncio.run_coroutine_threadsafe(
            self._js.publish(subject, data), self._loop
        )
        try:
            future.result(timeout=5)
        except Exception as e:
            print(f"[event_bus] Publish failed for '{subject}': {e}")

    def subscribe(self, subject: str, handler: Callable[[dict], None], durable: str = None) -> None:
        """
        Subscribe to a subject with a durable consumer. handler is called
        with the parsed JSON payload for each message (runs on the
        background event loop's thread, not the caller's thread — keep
        handlers fast or dispatch to your own worker thread if needed).
        """
        durable = durable or subject.replace(".", "_")

        async def _consume():
            psub = await self._js.pull_subscribe(subject, durable=durable)
            while True:
                try:
                    msgs = await psub.fetch(1, timeout=5)
                except Exception:
                    continue
                for msg in msgs:
                    try:
                        payload = json.loads(msg.data.decode("utf-8"))
                        handler(payload)
                        await msg.ack()
                    except Exception as e:
                        print(f"[event_bus] Handler error on '{subject}': {e}")

        asyncio.run_coroutine_threadsafe(_consume(), self._loop)

    def close(self):
        if self._nc is not None:
            future = asyncio.run_coroutine_threadsafe(self._nc.close(), self._loop)
            try:
                future.result(timeout=5)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)


if __name__ == "__main__":
    # Quick smoke test: publish then consume one message.
    bus = EventBus()

    def on_msg(payload):
        print("[smoke test] Received:", payload)

    bus.subscribe(TRANSCRIPT_CREATED, on_msg, durable="smoke_test")
    bus.publish(TRANSCRIPT_CREATED, {"text": "hello world", "session_id": "test"})

    import time
    time.sleep(3)  # give the pull subscriber time to fetch
    bus.close()
