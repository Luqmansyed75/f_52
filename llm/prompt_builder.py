"""
prompt_builder.py

Builds the final chat messages for the LLM.

Inputs
------
- System Prompt
- Conversation History (structured messages)
- Retrieved Meeting Context
- Current User Query

Output
------
List of chat messages ready for Groq/OpenAI.
"""

from typing import Dict, List

import config


class PromptBuilder:
    """
    Builds the final chat history for the LLM.
    """

    def __init__(self, system_prompt: str | None = None):
        self.system_prompt = system_prompt or config.SYSTEM_PROMPT

    def build(
        self,
        user_query: str,
        conversation_history: List[Dict[str, str]],
        meeting_context: str = "",
    ) -> List[Dict[str, str]]:
        """
        Parameters
        ----------
        user_query:
            Latest user utterance.

        conversation_history:
            Output of conversation_memory.get_messages()

        meeting_context:
            Retrieved context from PostgreSQL/Qdrant.
        """

        messages = [
            {
                "role": "system",
                "content": self.system_prompt,
            }
        ]

        # Preserve previous chat exactly as it happened
        messages.extend(conversation_history)

        # Inject retrieved meeting context
        if meeting_context.strip():
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Relevant Meeting Context:\n\n"
                        f"{meeting_context}\n\n"
                        "Use this information if it is relevant. "
                        "If the answer is not contained here, "
                        "say you don't know instead of making up facts."
                    ),
                }
            )

        # Current user query
        messages.append(
            {
                "role": "user",
                "content": user_query,
            }
        )

        return messages


if __name__ == "__main__":

    history = [
        {
            "role": "user",
            "content": "Hey Proxy",
        },
        {
            "role": "assistant",
            "content": "Hello! How can I help?",
        },
        {
            "role": "user",
            "content": "What database did we decide to use?",
        },
        {
            "role": "assistant",
            "content": "The team decided to use PostgreSQL.",
        },
    ]

    builder = PromptBuilder()

    messages = builder.build(
        user_query="Who proposed it?",
        conversation_history=history,
        meeting_context="""
Decision:
Use PostgreSQL

Proposed By:
Alice

Deadline:
Friday
""",
    )

    from pprint import pprint
    pprint(messages)