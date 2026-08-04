"""
Routes each conversational turn to the configured LLM.

The router accepts the final list of chat messages built by
PromptBuilder and forwards them to Groq.
"""

from llm.llm import GroqLLM
import config
from core.event_bus import EventBus
import time


class LLMRouter:
    def __init__(self, bus: EventBus = None):
        self.llm = GroqLLM()
        self._bus = bus

    def stream_reply(self, messages: list, on_sentence):
        # Publish LLM started
        start_ts = time.time()
        if self._bus is not None:
            try:
                self._bus.publish(config.SUBJECT_LLM_STARTED, {"timestamp": start_ts})
            except Exception:
                pass

        result = self.llm.stream_reply(
            messages,
            on_sentence,
        )

        # Publish LLM finished
        end_ts = time.time()
        if self._bus is not None:
            try:
                self._bus.publish(config.SUBJECT_LLM_FINISHED, {"timestamp": end_ts})
            except Exception:
                pass

        return result