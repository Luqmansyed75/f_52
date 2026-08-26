from __future__ import annotations

import asyncio
import enum
import logging
import threading
import time
import uuid
from typing import Callable, List, Optional, Set, Tuple

logger = logging.getLogger("session_state")


class SessionState(str, enum.Enum):
    """Lifecycle states for the meeting representative bot."""
    STARTING = "STARTING"          # Initial boot, container initialization
    JOINING = "JOINING"            # Chrome navigating, entering meeting room
    CONNECTED = "CONNECTED"        # In meeting, audio flowing both ways, healthy
    DEGRADED = "DEGRADED"          # Heartbeat missed, WebSocket flaky, or partial failure
    RECONNECTING = "RECONNECTING"  # Actively recovering connection/bridge
    LEAVING = "LEAVING"            # Bot executing clean exit
    STOPPED = "STOPPED"            # Fully shut down (terminal state)


LEGAL_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.STARTING: {SessionState.JOINING, SessionState.STOPPED},
    SessionState.JOINING: {
        SessionState.CONNECTED,
        SessionState.DEGRADED,
        SessionState.LEAVING,
        SessionState.STOPPED,
    },
    SessionState.CONNECTED: {
        SessionState.DEGRADED,
        SessionState.LEAVING,
        SessionState.STOPPED,
    },
    SessionState.DEGRADED: {
        SessionState.CONNECTED,
        SessionState.RECONNECTING,
        SessionState.LEAVING,
        SessionState.STOPPED,
    },
    SessionState.RECONNECTING: {
        SessionState.CONNECTED,
        SessionState.DEGRADED,
        SessionState.LEAVING,
        SessionState.STOPPED,
    },
    SessionState.LEAVING: {SessionState.STOPPED},
    SessionState.STOPPED: set(),  # Terminal: no outgoing transitions
}


class SessionStateMachine:
    """
    Thread-safe and async-safe state machine managing session lifecycle,
    transition validation, state history, and event hooks.
    """

    def __init__(self, session_id: Optional[str] = None) -> None:
        self._session_id: str = session_id or str(uuid.uuid4())[:8]
        self._current_state: SessionState = SessionState.STARTING
        self._state_entered_time: float = time.time()
        self._lock: threading.RLock = threading.RLock()
        self._history: List[Tuple[float, SessionState, SessionState, str]] = []
        self._callbacks: List[Callable[[SessionState, SessionState, str], None]] = []

        logger.info(
            f"[session_id={self._session_id}] SessionStateMachine initialized in {self._current_state.value}"
        )

    @property
    def session_id(self) -> str:
        """Unique identifier for this session."""
        return self._session_id

    @property
    def current_state(self) -> SessionState:
        """Thread-safe read access to the current session state."""
        with self._lock:
            return self._current_state

    def can_transition_to(self, new_state: SessionState) -> bool:
        """Check if a transition from current state to new_state is legal."""
        with self._lock:
            return new_state in LEGAL_TRANSITIONS.get(self._current_state, set())

    def time_in_state(self) -> float:
        """Return the elapsed time in seconds since entering the current state."""
        with self._lock:
            return max(0.0, time.time() - self._state_entered_time)

    @property
    def state_history(self) -> List[Tuple[float, SessionState, SessionState, str]]:
        """Return a copy of the last 50 state transition records."""
        with self._lock:
            return list(self._history)

    def register_callback(
        self, callback_fn: Callable[[SessionState, SessionState, str], None]
    ) -> None:
        """
        Register a callback invoked after every successful state transition.
        Callback signature: (old_state: SessionState, new_state: SessionState, reason: str) -> None
        """
        with self._lock:
            if callback_fn not in self._callbacks:
                self._callbacks.append(callback_fn)

    def transition_to(self, new_state: SessionState, reason: str = "") -> bool:
        """
        Synchronously validate and execute a state transition.
        Returns True if successful, False if illegal.
        """
        callbacks_to_fire = []
        old_state: SessionState

        with self._lock:
            if not self.can_transition_to(new_state):
                logger.warning(
                    f"[{self._session_id}] ILLEGAL TRANSITION: {self._current_state.value} → {new_state.value} (reason: {reason or 'none'})"
                )
                return False

            old_state = self._current_state
            self._current_state = new_state
            self._state_entered_time = time.time()

            # Record in ring history (max 50)
            self._history.append((self._state_entered_time, old_state, new_state, reason))
            if len(self._history) > 50:
                self._history.pop(0)

            logger.info(
                f"[session_id={self._session_id}] STATE: {old_state.value} → {new_state.value} (reason: {reason or 'none'})"
            )

            callbacks_to_fire = list(self._callbacks)

        # Fire callbacks outside the lock to prevent deadlocks
        for callback in callbacks_to_fire:
            try:
                res = callback(old_state, new_state, reason)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception as e:
                logger.exception(
                    f"[{self._session_id}] Error in state transition callback {callback}: {e}"
                )

        return True

    async def transition_to_async(self, new_state: SessionState, reason: str = "") -> bool:
        """Async-friendly wrapper for transition_to."""
        return self.transition_to(new_state=new_state, reason=reason)

    def is_healthy(self) -> bool:
        """Return True only if the bot is actively and cleanly connected."""
        return self.current_state == SessionState.CONNECTED

    def is_terminal(self) -> bool:
        """Return True if the bot is stopped and shut down."""
        return self.current_state == SessionState.STOPPED