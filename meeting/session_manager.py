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
import threading
import uuid
from typing import Optional

import config
from core.event_bus import EventBus


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

    def __init__(self, timeout_seconds: int = None, bus: Optional[EventBus] = None):
        """
        If timeout_seconds is None, use config.SESSION_INACTIVITY_SECONDS.
        If a bus is provided, session events will be published to it.
        """

        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else config.SESSION_INACTIVITY_SECONDS
        )

        self._active = False
        self._session_id = None
        self._started_at = None
        self._last_activity = None

        self._bus = bus
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    # Session lifecycle

    def start(self) -> str:
        """
        Starts a new conversation session.

        Returns
        -------
        str
            Newly created conversation session ID.
        """

        now = time.time()
        print("SESSION STARTED")
        with self._lock:
            self._active = True
            self._session_id = str(uuid.uuid4())
            self._started_at = now
            self._last_activity = now

        # Start/reset the inactivity timer outside the lock
        self._reset_timer()

        return self._session_id

    def stop(self) -> None:
        """
        Ends the current conversation session.
        """
        with self._lock:
            self._active = False

            self._session_id = None
            self._started_at = None
            self._last_activity = None
            print("SESSION STOPPED")

            if self._timer is not None:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
                self._timer = None

    # Activity

    def refresh_activity(self) -> None:
        """
        Call whenever the user speaks during
        an active conversation.
        """
        # Update last_activity under lock, then reset timer and publish
        # outside the lock to avoid holding the lock during I/O.
        print("SESSION REFRESH")
        with self._lock:
            active = self._active   
            sid = self._session_id
            if active:
                self._last_activity = time.time()

        if active:
            self._reset_timer()
            # Publish session touched event
            if self._bus is not None:
                try:
                    self._bus.publish(
                        config.SUBJECT_SESSION_TOUCHED,
                        {"session_id": sid, "timestamp": time.time()},
                    )
                except Exception:
                    pass

    # Backwards-compatible alias
    def touch(self) -> None:
        return self.refresh_activity()

    def _reset_timer(self) -> None:
        with self._lock:
            if self._timer is not None:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
                self._timer = None

            # Start a new timer that will expire the session
            try:
                self._timer = threading.Timer(self.timeout_seconds, self._expire)
                self._timer.daemon = True
                self._timer.start()
            except Exception:
                self._timer = None

    def _expire(self) -> None:
        print("SESSION EXPIRED")
        with self._lock:
            if not self._active:
                return
            # Mark inactive
            self._active = False
            sid = self._session_id
            self._session_id = None
            self._started_at = None
            self._last_activity = None
            self._timer = None

        # Publish session expired event
        if self._bus is not None:
            try:
                self._bus.publish(
                    config.SUBJECT_SESSION_EXPIRED,
                    {"session_id": sid, "timestamp": time.time()},
                )
            except Exception:
                pass

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

        # Polling-style timeout checks are deprecated. Sessions expire
        # via a timer and publish an event. Keep this method for API
        # compatibility but return False when the session is active.
        if not self._active:
            return False

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
        print(
            "Session:",
            self._active,
            "Mention:",
            mention_detected,
        )

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