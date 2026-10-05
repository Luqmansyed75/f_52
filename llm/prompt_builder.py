"""
prompt_builder.py

Builds the final chat messages for the LLM.
Consolidates system prompts, RAG context, and ensures perfect message 
role alternation to prevent Groq API parsing crashes.
"""

from __future__ import annotations
from typing import Dict, List
import config


class PromptBuilder:
    """
    Builds the final structured message payload for Groq / OpenAI.
    """

    def __init__(self, system_prompt: str | None = None):
        # Clean any leading spaces from configuration string indents
        self.system_prompt = (system_prompt or config.SYSTEM_PROMPT).strip()

    def build(
        self,
        user_query: str,
        conversation_history: List[Dict[str, str]],
        meeting_context: str = "",
    ) -> List[Dict[str, str]]:
        """
        Constructs a strictly formatted list of alternating chat messages.

        Parameters
        ----------
        user_query : str
            The latest user speech transcription.
        conversation_history : List[Dict[str, str]]
            The dialogue turns from ConversationMemory.
        meeting_context : str
            Context retrieved from vector memory.
        """
        # 1. Enforce strict single system prompt at the very beginning
        system_content = self.system_prompt

        if meeting_context.strip():
            system_content += (
                "\n\n[RELEVANT MEETING CONTEXT]\n"
                f"{meeting_context.strip()}\n\n"
                "Use the relevant meeting context above to answer accurately if applicable. "
                "If the query asks about a topic not mentioned in the context or history, "
                "answer based on your general knowledge but do not make up meeting details."
            )

        # 2. Gather conversation turns and current user query
        raw_turns = list(conversation_history)
        raw_turns.append({"role": "user", "content": user_query})

        # 3. Clean and merge consecutive identical roles to prevent parser crashes
        clean_turns: List[Dict[str, str]] = []
        for msg in raw_turns:
            role = msg["role"]
            content = msg["content"].strip()
            if not content:
                continue

            if clean_turns and clean_turns[-1]["role"] == role:
                # Merge consecutive identical roles cleanly with a newline
                clean_turns[-1]["content"] += f"\n{content}"
            else:
                clean_turns.append({"role": role, "content": content})

        # 4. Enforce strict alternating structure (User -> Assistant -> User -> Assistant)
        final_turns: List[Dict[str, str]] = []
        for msg in clean_turns:
            if not final_turns:
                # First turn must always be a user message
                if msg["role"] == "user":
                    final_turns.append(msg)
            else:
                # Ensure the roles strictly alternate
                expected_role = "assistant" if final_turns[-1]["role"] == "user" else "user"
                if msg["role"] == expected_role:
                    final_turns.append(msg)
                else:
                    # Safely merge consecutive role anomalies
                    final_turns[-1]["content"] += f"\n{msg['content']}"

        # 5. Output the single top-level system message and strict alternating dialogue turns
        return [
            {
                "role": "system",
                "content": system_content,
            }
        ] + final_turns


if __name__ == "__main__":
    history = [
        {"role": "user", "content": "Hey Proxy"},
        {"role": "assistant", "content": "Hello! How can I help?"},
    ]

    builder = PromptBuilder()
    messages = builder.build(
        user_query="Who proposed Postgres?",
        conversation_history=history,
        meeting_context="Proposed By: Alice",
    )

    from pprint import pprint
    pprint(messages)