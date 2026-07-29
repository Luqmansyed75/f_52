"""
Mention detection — decides whether the agent is being addressed.

v1: simple, explicit substring matching against configured wake
phrases. This is intentionally not ML-based — a rule-based check is
easy to reason about and debug, and is enough to prove the
"only speak when called" behavior end-to-end.

EXTENSION POINT: swap is_mention()'s implementation for a proper
intent/turn-taking classifier later (e.g. a small fine-tuned model, or
an LLM call) without changing its signature — callers don't need to
change.
"""

import config


def is_mention(text: str) -> bool:
    """
    Returns True if the text appears to address the agent directly,
    based on config.WAKE_PHRASES. Case-insensitive substring match.
    """
    if not text:
        return False

    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in config.WAKE_PHRASES)


