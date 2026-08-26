"""
LLM reasoning module — wraps Groq, streams the response and splits it
into clean clauses and sentences so TTS can start speaking in ~0.5s before
the full reply is generated (keeps perceived latency ultra-low).
"""

from groq import Groq
import time
import config
from core.logger import get_llm_logger
from core.error_handler import handle_errors

logger = get_llm_logger()

# Terminal marks that conclude a complete thought
TERMINAL_PUNCTUATION = [". ", "? ", "! ", ".\n", "!\n", "?\n", "\n\n", "\n"]

# Clause marks that represent natural speech pauses
CLAUSE_PUNCTUATION = [", ", "; ", ": ", " — ", " - ", " – "]

# Minimum word count before allowing a clause (comma/semicolon) split
MIN_WORDS_FOR_CLAUSE = 3

# Safety cap: force split at a word boundary if no punctuation for 14 words
MAX_WORDS_WITHOUT_PUNCT = 14

# Common abbreviations to avoid false terminal splits
ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "e.g.", "i.e.", "vs.", "etc."}


class GroqLLM:
    def __init__(self):
        self.client = Groq(api_key=config.GROQ_API_KEY)

    def _should_split_clause(self, text_before: str) -> bool:
        """Check if candidate clause has enough words and is not an abbreviation."""
        words = text_before.strip().split()
        if len(words) < MIN_WORDS_FOR_CLAUSE:
            return False
        last_word = words[-1].lower()
        if last_word in ABBREVIATIONS:
            return False
        return True

    def _extract_next_chunk(self, buffer: str) -> tuple[str | None, str]:
        """
        Extracts the next ready clause or sentence from the buffer.
        Returns: (extracted_chunk_or_None, remaining_buffer)
        """
        # 1. Check for Terminal Punctuation first (highest priority)
        earliest_term_idx = len(buffer)
        earliest_term_punct = None

        for punct in TERMINAL_PUNCTUATION:
            idx = buffer.find(punct)
            if idx != -1 and idx < earliest_term_idx:
                # Check if it's an abbreviation like "Dr. Smith"
                candidate = buffer[:idx + len(punct)].strip()
                words = candidate.split()
                if words and words[-1].lower() in ABBREVIATIONS:
                    continue
                earliest_term_idx = idx
                earliest_term_punct = punct

        if earliest_term_punct is not None:
            parts = buffer.split(earliest_term_punct, 1)
            chunk = (parts[0] + earliest_term_punct).strip()
            remainder = parts[1]
            return chunk, remainder

        # 2. Check for Clause Punctuation (for fast first-sound latency)
        earliest_clause_idx = len(buffer)
        earliest_clause_punct = None

        for punct in CLAUSE_PUNCTUATION:
            idx = buffer.find(punct)
            if idx != -1 and idx < earliest_clause_idx:
                earliest_clause_idx = idx
                earliest_clause_punct = punct

        if earliest_clause_punct is not None:
            candidate_before = buffer[:earliest_clause_idx]
            if self._should_split_clause(candidate_before):
                parts = buffer.split(earliest_clause_punct, 1)
                chunk = (parts[0] + earliest_clause_punct).strip()
                remainder = parts[1]
                return chunk, remainder

        # 3. Safety Fallback: split long run-on sentences without punctuation
        words = buffer.split()
        if len(words) >= MAX_WORDS_WITHOUT_PUNCT:
            # Split at the last space before the 10th word
            split_idx = buffer.find(words[10])
            if split_idx != -1:
                chunk = buffer[:split_idx].strip()
                remainder = buffer[split_idx:]
                return chunk, remainder

        return None, buffer

    @handle_errors(logger)
    def stream_reply(self, messages: list, on_sentence):
        """
        Streams the LLM response at clause-level granularity for sub-second first-sound latency.
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
        first_token_time = 0.0
        first_clause_time = 0.0
        token_count = 0
        clauses_emitted = 0

        for chunk in response:
            token = chunk.choices[0].delta.content
            if not token:
                continue

            token_count += 1

            if first_token:
                first_token_time = time.perf_counter()
                print(
                    f"⚡ First Token Latency : "
                    f"{first_token_time - request_start:.3f} sec"
                )
                logger.info("First Token Latency: %.3f sec", first_token_time - request_start)
                first_token = False

            sentence_buffer += token
            full_response += token

            # Extract and emit all ready clauses/sentences in the current buffer
            while True:
                ready_chunk, sentence_buffer = self._extract_next_chunk(sentence_buffer)
                if not ready_chunk:
                    break

                if clauses_emitted == 0:
                    first_clause_time = time.perf_counter()
                    print(
                        f"⚡ First Clause Dispatched ({len(ready_chunk.split())} words) : "
                        f"{first_clause_time - request_start:.3f} sec"
                    )

                clauses_emitted += 1
                on_sentence(ready_chunk)

        # Flush any remaining text in the buffer at stream completion
        if sentence_buffer.strip():
            clauses_emitted += 1
            on_sentence(sentence_buffer.strip())

        end = time.perf_counter()

        print("\n========== GROQ CLAUSE-STREAMING LATENCY ==========")
        print(f"Request Sent          : {request_sent - request_start:.3f} sec")
        print(f"First Token           : {first_token_time - request_start:.3f} sec")
        if first_clause_time > 0:
            print(f"First Clause to TTS   : {first_clause_time - request_start:.3f} sec")
        print(f"LLM Total Time        : {end - request_start:.3f} sec")
        print(f"Tokens Received       : {token_count}")
        print(f"Clauses Emitted       : {clauses_emitted}")
        print("===================================================\n")

        logger.info(
            "LLM Request Sent: %.3f sec, First Token: %.3f sec, Total: %.3f sec, Tokens: %d, Clauses: %d",
            request_sent - request_start,
            first_token_time - request_start,
            end - request_start,
            token_count,
            clauses_emitted,
        )

        return full_response