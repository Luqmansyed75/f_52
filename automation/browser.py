import socket
import subprocess
import time

import requests
from playwright.sync_api import sync_playwright

from config import CHROME_PATH, PROFILE_DIR, HEADLESS, DEBUG_PORT


class BrowserManager:
    """
    Launches the user's real Chrome via subprocess with remote debugging,
    then connects Playwright over CDP.  Google sees a normal Chrome browser —
    no automation flags, no navigator.webdriver = true.
    """

    def __init__(self):
        self.playwright = None
        self.browser = None
        self._chrome_process = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def launch(self):
        """Launch Chrome and return a Playwright Page handle."""

        # 1. Kill any leftover Chrome debug sessions on the port
        self._ensure_port_free()

        # 2. Build the Chrome command line
        cmd = [
            CHROME_PATH,
            "about:blank",                        # open a blank page, not chrome://newtab
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-service-autorun",
            "--disable-background-networking",
            "--disable-sync",
        ]

        if HEADLESS:
            cmd.append("--headless=new")

        # 3. Start Chrome as a normal subprocess
        self._chrome_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 4. Wait for the debug port to accept connections
        self._wait_for_debug_port(timeout=15)

        # 5. Connect Playwright over CDP
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(
            f"http://localhost:{DEBUG_PORT}",
        )

        # 6. Get the default context and reuse the about:blank page
        #    that Chrome opened (it's fully navigable via CDP).
        if self.browser.contexts:
            context = self.browser.contexts[0]
        else:
            context = self.browser.new_context()

        if context.pages:
            page = context.pages[0]
        else:
            page = context.new_page()

        return page

    def close(self):
        """Disconnect Playwright, then terminate the Chrome subprocess."""
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass

        try:
            if self._chrome_process and self._chrome_process.poll() is None:
                self._chrome_process.terminate()
                self._chrome_process.wait(timeout=5)
        except Exception:
            pass

        self.browser = None
        self.playwright = None
        self._chrome_process = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_port_free(self):
        """Check if the debug port is already in use and abort if so."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", DEBUG_PORT)) == 0:
                # Port occupied — try to ask the existing Chrome to close,
                # or just let the user know.
                raise RuntimeError(
                    f"Port {DEBUG_PORT} is already in use. "
                    "Close any existing Chrome instances that use this port "
                    "and try again."
                )

    def _wait_for_debug_port(self, timeout: int = 15):
        """Block until Chrome's /json/version endpoint responds."""
        deadline = time.time() + timeout
        url = f"http://localhost:{DEBUG_PORT}/json/version"

        while time.time() < deadline:
            try:
                resp = requests.get(url, timeout=2)
                if resp.status_code == 200:
                    return
            except requests.ConnectionError:
                pass
            time.sleep(0.5)

        raise TimeoutError(
            f"Chrome did not start within {timeout}s. "
            f"No response on localhost:{DEBUG_PORT}."
        )