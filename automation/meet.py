import time
from playwright.sync_api import Page

from automation.selectors import (
    JOIN_BUTTON,
    LEAVE_CALL_BUTTON,
    END_SCREEN_TEXT,
)


class MeetManager:
    """Handles the Google Meet joining and monitoring lifecycle."""

    def __init__(self, page: Page):
        self.page = page

    def enter_green_room(self, meet_url: str, timeout: int = 30_000):
        """
        Navigate to the meeting URL and wait for the green room to load.
        Returns True if the join button appeared, False otherwise.
        """
        self.page.goto(meet_url)
        self.page.wait_for_load_state("networkidle")

        try:
            self.page.wait_for_selector(JOIN_BUTTON, timeout=timeout)
            time.sleep(2)  # let overlays / tooltips settle
            self._dismiss_overlays()
            return True
        except Exception:
            return False

    def mute_mic(self):
        """Toggle microphone off via Ctrl+D."""
        self.page.keyboard.press("Control+d")
        time.sleep(0.3)

    def mute_camera(self):
        """Toggle camera off via Ctrl+E."""
        self.page.keyboard.press("Control+e")
        time.sleep(0.3)

    def mute_all(self):
        """Mute both mic and camera."""
        self.mute_mic()
        self.mute_camera()
        time.sleep(0.5)

    def click_join(self):
        """
        Click the 'Join now' or 'Ask to join' button.
        Uses JavaScript click to bypass Google Meet's overlay divs
        that intercept pointer events.
        """
        self._dismiss_overlays()
        btn = self.page.locator(JOIN_BUTTON).first
        # JS click bypasses any overlay that sits on top of the button
        btn.evaluate("el => el.click()")
        time.sleep(1)

    def wait_for_admission(self, timeout: int = 60_000) -> bool:
        """
        Wait until the 'Leave call' button appears (confirms we're in the meeting).
        Returns True if admitted, False on timeout.
        """
        try:
            self.page.wait_for_selector(LEAVE_CALL_BUTTON, timeout=timeout)
            return True
        except Exception:
            return False

    def monitor_until_end(self, fallback_minutes: int = 30) -> str:
        """
        Block until one of three signals fires:

        1. The 'Leave call' button disappears (host ended the meeting).
        2. An end-of-meeting text appears ('Call ended' etc.).
        3. A fallback timeout elapses.

        Returns the reason string.
        """
        from playwright.sync_api import TimeoutError as PwTimeout

        # We poll every 2 seconds for efficiency rather than busy-waiting
        poll_interval = 2
        elapsed = 0
        fallback_seconds = fallback_minutes * 60

        while True:
            # Signal 1: Leave button disappeared
            try:
                self.page.wait_for_selector(
                    LEAVE_CALL_BUTTON,
                    timeout=1_000,  # short poll
                )
            except PwTimeout:
                # Button is gone → meeting ended
                return "leave_button_gone"

            # Signal 2: End screen text visible
            try:
                self.page.wait_for_selector(
                    END_SCREEN_TEXT,
                    timeout=1_000,
                )
                return "end_screen"
            except PwTimeout:
                pass

            # Signal 3: Fallback timeout
            elapsed += poll_interval
            if elapsed >= fallback_seconds:
                return "timeout"

            time.sleep(poll_interval)

    def leave(self):
        """Explicitly click the Leave call button."""
        try:
            self.page.locator(LEAVE_CALL_BUTTON).first.evaluate("el => el.click()")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dismiss_overlays(self):
        """
        Dismiss any Google Meet popups, tooltips, or 'Got it' dialogs
        that overlay the green room and block button clicks.
        """
        dismiss_selectors = [
            "button:has-text('Got it')",
            "button:has-text('Dismiss')",
            "button:has-text('OK')",
            "button:has-text('Close')",
        ]
        for sel in dismiss_selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=500):
                    loc.evaluate("el => el.click()")
                    time.sleep(0.3)
            except Exception:
                pass