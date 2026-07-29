"""
Conversation session manager.

Responsible ONLY for managing whether the AI assistant is currently in
an active conversation.

Responsibilities
----------------
- Start a conversation session after a wake word.
- Keep the session alive while the user continues talking.
- Automatically close the session after a period of inactivity.
- Expose a simple API so callers don't need to know the internal state.

NOT responsible for:
- Retrieval
- Conversation memory
- Database
- Vector store
- Mention detection
- LLM
- TTS

Those remain separate modules.

Future Extensions
-----------------
- Speaker-aware sessions
- Multiple simultaneous sessions
- Conversation IDs
- Permission management
- Interrupt handling
"""

from __future__ import annotations

import time
import uuid


class SessionManager:
    """
    Controls the conversation lifecycle.

    States:

        IDLE
          |
      Wake Word
          |
          v
      ACTIVE SESSION
          |
      User continues talking
          |
      refresh_activity()
          |
      silence > timeout
          |
          v
         IDLE
    """

    def __init__(self, timeout_seconds: int = 10):
        self.timeout_seconds = timeout_seconds

        self._active = False
        self._session_id = None
        self._started_at = None
        self._last_activity = None

    # Session lifecycle

    def start(self) -> str:
        """
        Starts a new conversation session.

        Returns
        -------
        str
            Newly created conversation session ID.
        """

        self._active = True

        self._session_id = str(uuid.uuid4())

        now = time.time()

        self._started_at = now
        self._last_activity = now

        return self._session_id

    def stop(self) -> None:
        """
        Ends the current conversation session.
        """

        self._active = False

        self._session_id = None
        self._started_at = None
        self._last_activity = None

    # Activity

    def refresh_activity(self) -> None:
        """
        Call whenever the user speaks during
        an active conversation.
        """

        if self._active:
            self._last_activity = time.time()

    # Timeout
 
    def check_timeout(self) -> bool:
        """
        Checks whether the conversation has expired.

        Returns
        -------
        bool

        True
            Session was closed due to inactivity.

        False
            Session still active.
        """

        if not self._active:
            return False

        elapsed = time.time() - self._last_activity

        if elapsed >= self.timeout_seconds:
            self.stop()
            return True

        return False

    # Query helpers

    @property
    def active(self) -> bool:
        return self._active

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def last_activity(self) -> float | None:
        return self._last_activity

    @property
    def started_at(self) -> float | None:
        return self._started_at

    def should_respond(self, mention_detected: bool) -> bool:
        """
        Main decision function.

        Returns True if the assistant should
        respond to the current transcript.

        Rules
        -----

        ACTIVE SESSION
            Always respond.

        NO SESSION
            Respond only if wake word detected.
        """

        if self._active:
            self.refresh_activity()
            return True

        if mention_detected:
            self.start()
            return True

        return False

    # Debug

    def __repr__(self):

        if not self._active:
            return "SessionManager(IDLE)"

        return (
            f"SessionManager("
            f"ACTIVE, "
            f"session_id={self._session_id}, "
            f"timeout={self.timeout_seconds}s)"
        )


if __name__ == "__main__":

    import time

    manager = SessionManager(timeout_seconds=5)

    print(manager)

    print("\nWake word detected...")

    manager.should_respond(True)

    print(manager)

    print("\nUser keeps talking...")

    time.sleep(2)

    manager.should_respond(False)

    print(manager)

    print("\nWaiting for timeout...")
    time.sleep(6)
    expired = manager.check_timeout()
    print("Expired:", expired)
    (manager)