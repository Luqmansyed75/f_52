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
from nats.js.api import ConsumerConfig, DeliverPolicy, AckPolicy,StreamConfig

import config
from core.logger import get_events_logger
from core.error_handler import safe_execute

logger = get_events_logger()


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

        subjects = [
            TRANSCRIPT_CREATED,
            MENTION_DETECTED,
            RESPONSE_GENERATED,
            # additional subjects from config
            config.SUBJECT_TRANSCRIPT_READY,
            config.SUBJECT_SPEECH_STARTED,
            config.SUBJECT_SPEECH_ENDED,
            config.SUBJECT_TURN_COMPLETED,
            config.SUBJECT_SESSION_TOUCHED,
            config.SUBJECT_SESSION_EXPIRED,
            config.SUBJECT_LLM_STARTED,
            config.SUBJECT_LLM_FINISHED,
            config.SUBJECT_BARGE_IN,
        ]

        try:
            await self._js.add_stream(
                StreamConfig(
                    name=config.NATS_STREAM_NAME,
                    subjects=subjects,
                )
            )
        except Exception:
            # Stream likely already exists. Try updating it to include
            # any newly-introduced subjects so publishes to those
            # subjects will be accepted by JetStream.
            try:
                await self._js.update_stream(
                    StreamConfig(name=config.NATS_STREAM_NAME, subjects=subjects)
                )
            except Exception:
                # If update also fails, give up silently — publish()
                # will log detailed errors later.
                pass

    def publish(self, subject: str, payload: dict) -> None:
        """Synchronously publish a JSON-serializable payload to a subject."""
        logger.debug("Publishing to '%s'", subject)
        data = json.dumps(payload).encode("utf-8")

        async def _publish_once():
            return await self._js.publish(subject, data)

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            self._loop.create_task(_publish_once())
            return

        future = asyncio.run_coroutine_threadsafe(_publish_once(), self._loop)
        try:
            future.result(timeout=5)
        except Exception as e:
            logger.error("Publish failed for '%s': %s", subject, e, exc_info=True)
            try:
                logger.debug("Local fallback event for '%s': %s", subject, payload)
            except Exception:
                pass

    def subscribe(self, subject: str, handler: Callable[[dict], None], durable: str = None) -> None:
        """
        Subscribe to a subject with a durable consumer. handler is called
        with the parsed JSON payload for each message (runs on the
        background event loop's thread, not the caller's thread — keep
        handlers fast or dispatch to your own worker thread if needed).
        """
        durable = durable or subject.replace(".", "_")
        logger.info("Subscribing to '%s' (durable: %s)", subject, durable)

        async def _consume():
            consumer_config = ConsumerConfig(
                durable_name=durable,
                deliver_policy=DeliverPolicy.NEW,
                ack_policy=AckPolicy.EXPLICIT,
            )
            try:
                psub = await self._js.pull_subscribe(
                    subject,
                    durable=durable,
                    config=consumer_config,
                )
            except Exception as e:
                logger.error("Pull subscribe failed for '%s': %s", subject, e, exc_info=True)
                raise

            while True:
                try:
                    msgs = await psub.fetch(1, timeout=5)
                except Exception:
                    continue

                for msg in msgs:
                    try:
                        payload = json.loads(msg.data.decode("utf-8"))

                        safe_execute(logger, handler, payload)

                        await msg.ack()

                    except Exception:
                        logger.error("Handler error on '%s'", subject, exc_info=True)
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
    bus = EventBus()

    def on_msg(payload):
        logger.debug("[smoke test] Received: %s", payload)

    bus.subscribe(TRANSCRIPT_CREATED, on_msg, durable="smoke_test")
    bus.publish(TRANSCRIPT_CREATED, {"text": "hello world", "session_id": "test"})

    import time
    time.sleep(3)  # give the pull subscriber time to fetch
    bus.close()
