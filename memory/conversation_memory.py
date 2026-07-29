"""
conversation_memory.py

Maintains short-term conversational context for the active session.

Purpose
-------
Keeps only the recent dialogue exchanged between the user and the
assistant. This context is sent to the LLM so it can understand
follow-up questions like:

User: What's today's agenda?
Assistant: ...
User: Who proposed it?

without repeatedly querying long-term memory.

This module is intentionally independent of:
- PostgreSQL
- Qdrant
- Retrieval
- LLM
- Session Manager

The SessionManager decides WHEN a conversation starts/stops.
This module only stores the dialogue.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List


class ConversationMemory:
    """
    Maintains the recent dialogue history.

    Example:

        User: Hello
        Assistant: Hi!

        User: What's today's agenda?
        Assistant: ...

        User: Who proposed it?

    Only the most recent N turns are retained.
    """

    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns
        self._history: Deque[Dict[str, str]] = deque(maxlen=max_turns * 2)

    # --------------------------------------------------
    # Add messages
    # --------------------------------------------------

    def add_user(self, text: str) -> None:
        """Store a user message."""

        text = text.strip()

        if not text:
            return

        self._history.append(
            {
                "role": "user",
                "content": text,
            }
        )

    def add_assistant(self, text: str) -> None:
        """Store an assistant message."""

        text = text.strip()

        if not text:
            return

        self._history.append(
            {
                "role": "assistant",
                "content": text,
            }
        )

    # Retrieval

    def get_messages(self) -> List[Dict[str, str]]:
        """
        Returns messages in OpenAI/Groq format.

        Example:

        [
            {"role":"user","content":"Hello"},
            {"role":"assistant","content":"Hi"},
            ...
        ]
        """

        return [msg.copy() for msg in self._history]

    def last_message(self) -> Dict[str, str] | None:
        """
        Returns the most recent message, or None if empty.
        """

        if not self._history:
            return None

        return self._history[-1].copy()

    def get_context(self) -> str:
        """
        Returns formatted conversation text.

        Useful if your LLM prompt expects plain text.
        """

        if not self._history:
            return ""

        lines = []

        for msg in self._history:

            speaker = (
                "User"
                if msg["role"] == "user"
                else "Assistant"
            )

            lines.append(f"{speaker}: {msg['content']}")

        return "\n".join(lines)

    # Management


    def clear(self) -> None:
        """
        Clears the current conversation.

        Called when SessionManager ends the session.
        """

        self._history.clear()

    def size(self) -> int:
        """Number of stored messages."""

        return len(self._history)

    def empty(self) -> bool:
        """True if no conversation exists."""

        return len(self._history) == 0

    # Debug

    def __len__(self):
        return len(self._history)

    def __repr__(self):

        return (
            f"ConversationMemory("
            f"messages={len(self._history)}, "
            f"max_turns={self.max_turns})"
        )


if __name__ == "__main__":

    memory = ConversationMemory(max_turns=5)

    memory.add_user("Hello")

    memory.add_assistant("Hi! How can I help you?")

    memory.add_user("What's today's agenda?")

    memory.add_assistant(
        "Today's agenda includes project updates and planning."
    )

    memory.add_user("Who proposed it?")

    print("------ Context ------")
    print(memory.get_context())

    print("\n------ Messages ------")
    print(memory.get_messages())

    print("\nClearing memory...")
    memory.clear()

    print(memory)