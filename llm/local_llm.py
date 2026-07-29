"""
Local Hindi/Telugu LLM — wraps Sarvam-2B running via Ollama.
Matches GroqLLM's stream_reply(prompt, history, on_sentence) interface
so main.py/llm_router.py can swap between them transparently.

Requires Ollama running locally with the model pulled:
    ollama pull
"""

import json
import requests

import config


class LocalLLM:
    def __init__(self):
        self.base_url = config.OLLAMA_BASE_URL
        self.model = config.LOCAL_OLLAMA_MODEL

    def stream_reply(self, prompt: str, conversation_history: list, on_sentence):
        """
        Streams the LLM response from Ollama, splits into sentences,
        and calls on_sentence(text) for each — same contract as
        GroqLLM.stream_reply. Returns the full response text.
        """
        messages = conversation_history + [{"role": "user", "content": prompt}]

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "thinking":False,
                    "options":{
                        "temperature":0.6
                    }
                },
                stream=True,
                timeout=30,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            error_msg = (
                "Sorry, I couldn't reach the local Hindi/Telugu model. "
                "Please check that Ollama is running."
            )
            print(f"[sarvam_local] Connection error: {e}")
            on_sentence(error_msg)
            return error_msg

        sentence_buffer = ""
        full_response = ""
        punctuation_marks = [". ", "? ", "! ", "\n", "। "]  # include Devanagari danda

        for line in response.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

            token = chunk.get("message", {}).get("content", "")
            print(repr(token))
            if not token:
                continue

            sentence_buffer += token
            full_response += token

            while any(punct in sentence_buffer for punct in punctuation_marks):
                earliest_punct, earliest_idx = None, len(sentence_buffer)
                for punct in punctuation_marks:
                    idx = sentence_buffer.find(punct)
                    if idx != -1 and idx < earliest_idx:
                        earliest_idx, earliest_punct = idx, punct

                parts = sentence_buffer.split(earliest_punct, 1)
                clean_sentence = (parts[0] + earliest_punct).strip()

                if clean_sentence:
                    on_sentence(clean_sentence)

                sentence_buffer = parts[1]

            if chunk.get("done"):
                break

        if sentence_buffer.strip():
            on_sentence(sentence_buffer.strip())

        return full_response
