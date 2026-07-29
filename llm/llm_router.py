"""
Routes each conversational turn to the configured LLM.

The router accepts the final list of chat messages built by
PromptBuilder and forwards them to Groq.
"""

from llm.llm import GroqLLM


class LLMRouter:
    def __init__(self):
        self.llm = GroqLLM()

    def stream_reply(self, messages: list, on_sentence):
        return self.llm.stream_reply(
            messages,
            on_sentence,
        )