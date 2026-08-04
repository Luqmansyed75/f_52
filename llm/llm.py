"""
LLM reasoning module — wraps Groq, streams the response and splits it
into clean sentences so TTS can start speaking before the full reply
is generated (keeps perceived latency low).
"""

from groq import Groq
import time
import config
from core.logger import get_llm_logger
from core.error_handler import handle_errors

logger = get_llm_logger()


PUNCTUATION_MARKS = [". ", "? ", "! ", "\n"]


class GroqLLM:
    def __init__(self):
        self.client = Groq(api_key=config.GROQ_API_KEY)

    import time

    @handle_errors(logger)
    def stream_reply(self, messages: list, on_sentence):
        """
        Streams the LLM response and prints detailed latency statistics.
        """
        logger.info("Sending request to LLM (model=%s)", config.LLM_MODEL)
        request_start = time.perf_counter()

        response = self.client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
            stream=True,
        )

        request_sent = time.perf_counter()

        sentence_buffer = ""
        full_response = ""

        first_token = True
        first_token_time = 0
        token_count = 0

        for chunk in response:

            token = chunk.choices[0].delta.content

            if not token:
                continue

            token_count += 1

            if first_token:
                first_token_time = time.perf_counter()
                print(
                    f"⚡ First Token Latency : "
                    f"{first_token_time-request_start:.3f} sec"
                )
                logger.info("First Token Latency: %.3f sec", first_token_time-request_start)
                first_token = False

            sentence_buffer += token
            full_response += token

            while any(p in sentence_buffer for p in PUNCTUATION_MARKS):

                earliest_punct = None
                earliest_idx = len(sentence_buffer)

                for punct in PUNCTUATION_MARKS:
                    idx = sentence_buffer.find(punct)
                    if idx != -1 and idx < earliest_idx:
                        earliest_idx = idx
                        earliest_punct = punct

                parts = sentence_buffer.split(earliest_punct, 1)

                clean_sentence = (
                    parts[0] + earliest_punct
                ).strip()

                if clean_sentence:
                    on_sentence(clean_sentence)

                sentence_buffer = parts[1]

        if sentence_buffer.strip():
            on_sentence(sentence_buffer.strip())

        end = time.perf_counter()

        print("\n========== GROQ LATENCY ==========")
        print(f"Request Sent        : {request_sent-request_start:.3f} sec")
        print(f"First Token         : {first_token_time-request_start:.3f} sec")
        print(f"LLM Total Time      : {end-request_start:.3f} sec")
        print(f"Tokens Received     : {token_count}")
        print("==================================\n")

        logger.info("LLM Request Sent: %.3f sec, First Token: %.3f sec, Total: %.3f sec, Tokens: %d",
                    request_sent-request_start, first_token_time-request_start, end-request_start, token_count)

        return full_response