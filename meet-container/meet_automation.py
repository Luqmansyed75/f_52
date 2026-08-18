"""
MeetAutomation — Playwright Chrome controller

Phase 1: stub only.
- start() launches Chrome
- join() navigates to Meet URL
- leave() closes browser

Real Google login + DOM automation comes in Phase 4.
"""

import asyncio
import logging
import os

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger("meet_automation")

BOT_DISPLAY_NAME = os.environ.get("BOT_DISPLAY_NAME", "AI Assistant")


class MeetAutomation:
    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._meet_mic_device_id: str = ""
        self._meet_out_device_id: str = ""

    async def start(self) -> None:
        logger.info("MeetAutomation starting...")
        self._playwright = await async_playwright().start()

        self._browser = await self._playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome-stable",
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )

        self._context = await self._browser.new_context(
            permissions=["microphone", "camera"],
        )
        self._page = await self._context.new_page()

        # Enumerate and pin audio devices
        await self._pin_audio_devices()
        logger.info("MeetAutomation ready.")

    async def stop(self) -> None:
        logger.info("MeetAutomation stopping...")
        try:
            if self._browser:
                await self._browser.close()
        except Exception as e:
            logger.warning(f"Browser close error: {e}")
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"Playwright stop error: {e}")
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    async def join(self, meet_url: str) -> None:
        """
        Phase 1 stub: just navigate to the URL.
        Phase 4 will add: login check, name entry, mic/cam toggle, join button.
        """
        if self._page is None:
            raise RuntimeError("MeetAutomation not started.")

        logger.info(f"Navigating to Meet (stub): {meet_url}")
        try:
            await self._page.goto(meet_url, timeout=30000)
            await self._page.wait_for_timeout(3000)
            title = await self._page.title()
            logger.info(f"Page title: {title}")
        except Exception as e:
            logger.warning(f"Navigation error (expected in stub mode): {e}")

    async def leave(self) -> None:
        """
        Phase 1 stub: just navigate away.
        Phase 4 will click the real leave button.
        """
        if self._page is None:
            return
        try:
            await self._page.goto("about:blank", timeout=10000)
        except Exception as e:
            logger.warning(f"Leave navigation error: {e}")

    # ------------------------------------------------------------------
    # Audio device pinning
    # ------------------------------------------------------------------

    async def _pin_audio_devices(self) -> None:
        """
        Enumerate PulseAudio devices by label using a local HTTP page
        so getUserMedia has a secure context to work with.
        """
        if self._page is None:
            return

        logger.info("Enumerating PulseAudio devices via browser...")

        # Serve a minimal local page for secure getUserMedia context
        import http.server
        import threading

        html = b"""<!DOCTYPE html><html><body>
        <script>
        window.enumDevices = async function() {
            try {
                const s = await navigator.mediaDevices.getUserMedia({audio:true,video:false});
                s.getTracks().forEach(t=>t.stop());
                const devices = await navigator.mediaDevices.enumerateDevices();
                return devices
                    .filter(d=>d.kind==='audioinput'||d.kind==='audiooutput')
                    .map(d=>({kind:d.kind,label:d.label,deviceId:d.deviceId}));
            } catch(e) { return [{error:e.toString()}]; }
        };
        </script><p>device enum</p></body></html>"""

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            def log_message(self, *args):
                return

        server = http.server.HTTPServer(("0.0.0.0", 8765), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            await self._page.goto("http://localhost:8765", timeout=10000)
            await self._page.wait_for_timeout(500)

            devices_json = await self._page.evaluate("window.enumDevices()")

            for d in devices_json:
                if not isinstance(d, dict) or "error" in d:
                    logger.warning(f"Device enum error: {d}")
                    continue
                label = d.get("label", "")
                device_id = d.get("deviceId", "")
                kind = d.get("kind", "")

                if kind == "audioinput" and "meet_mic" in label:
                    self._meet_mic_device_id = device_id
                    logger.info(f"Pinned meet_mic: {device_id[:16]}...")

                if kind == "audiooutput" and "meet_out" in label:
                    self._meet_out_device_id = device_id
                    logger.info(f"Pinned meet_out: {device_id[:16]}...")

            if not self._meet_mic_device_id:
                logger.warning("meet_mic not found in browser device list")
            if not self._meet_out_device_id:
                logger.warning("meet_out not found in browser device list")

        except Exception as e:
            logger.error(f"Device enumeration failed: {e}")
        finally:
            server.shutdown()
            server.server_close()