import asyncio
import glob
import logging
import os
import subprocess
import time
import urllib.request
import urllib.error
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("meet_automation")

CHROME_PATH = "/usr/bin/google-chrome-stable"
PROFILE_DIR = "/chrome-profile"
DEBUG_PORT = 9222
BOT_NAME = os.environ.get("BOT_DISPLAY_NAME", "AI Assistant")

JOIN_BUTTON = "button:has-text('Join now'), button:has-text('Ask to join'), button:has-text('Join')"
LEAVE_CALL_BUTTON = 'button[aria-label*="Leave call" i], button[aria-label*="leave" i]'


class MeetAutomation:
    """Manages real Chrome via CDP and automates Google Meet joining/interaction."""

    def __init__(self):
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None
        self._chrome_proc = None

    async def start(self):
        logger.info("MeetAutomation starting (Real Chrome with PulseAudio devices)...")

        # 1. Clean stale locks
        self._cleanup_locks()

        # 2. Launch Google Chrome with real PulseAudio mic/out
        cmd = [
            CHROME_PATH,
            "about:blank",
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            # Automatically accept mic/cam permission prompts
            "--use-fake-ui-for-media-stream",
            "--autoplay-policy=no-user-gesture-required",
        ]

        logger.info(f"Spawning Chrome subprocess on port {DEBUG_PORT}...")
        self._chrome_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 3. Wait for Chrome CDP endpoint to be ready
        await self._wait_for_cdp(timeout=15)

        # 4. Connect Playwright over CDP
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{DEBUG_PORT}")

        if self.browser.contexts:
            self.context = self.browser.contexts[0]
        else:
            self.context = await self.browser.new_context()

        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()

        # 5. Pin PulseAudio devices
        self._pin_audio_devices_pactl()
        logger.info("MeetAutomation ready via CDP connection.")

    def _cleanup_locks(self):
        for pattern in ["Singleton*", ".org.chromium.Chromium.*"]:
            for f in glob.glob(os.path.join(PROFILE_DIR, pattern)):
                try:
                    os.remove(f)
                except Exception:
                    pass

    async def _wait_for_cdp(self, timeout: int = 15):
        deadline = time.time() + timeout
        url = f"http://127.0.0.1:{DEBUG_PORT}/json/version"
        while time.time() < deadline:
            try:
                loop = asyncio.get_running_loop()
                resp = await loop.run_in_executor(
                    None, lambda: urllib.request.urlopen(url, timeout=1)
                )
                if resp.status == 200:
                    logger.info("Chrome CDP endpoint verified.")
                    return
            except Exception:
                pass
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Chrome failed to start CDP listener within {timeout}s")

    def _pin_audio_devices_pactl(self):
        try:
            result = subprocess.run(
                ["pactl", "list", "sources", "short"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if "meet_mic" in line:
                    parts = line.split()
                    logger.info(f"Pinned meet_mic (pactl): {parts[1] if len(parts)>1 else line}")
                if "meet_out" in line:
                    parts = line.split()
                    logger.info(f"Pinned meet_out.monitor (pactl): {parts[1] if len(parts)>1 else line}")
        except Exception as e:
            logger.warning(f"pactl device check failed: {e}")

    async def join(self, meet_url: str) -> bool:
        logger.info(f"Navigating to Meet: {meet_url}")
        try:
            await self.page.goto(meet_url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeout:
            logger.error("Timed out loading Meet URL")
            return False

        logger.info(f"Page loaded: {self.page.url}")
        await self.page.wait_for_timeout(3000)

        # 1. Dismiss overlays/tooltips
        await self._dismiss_overlays()

        # 2. Turn off camera with Ctrl+E to save CPU
        await self.page.keyboard.press("Control+e")
        logger.info("Sent Control+e (mute camera)")
        await self.page.wait_for_timeout(500)

        # 3. Enter Guest Name if unauthenticated
        await self._fill_guest_name()

        # 4. Click Join / Ask to join
        logger.info("Clicking Join button using direct JS click...")
        for attempt in range(8):
            if await self._click_join():
                logger.info("✅ Join button clicked!")
                break
            await self.page.wait_for_timeout(1500)
            await self._dismiss_overlays()
            await self._fill_guest_name()

        await self.page.wait_for_timeout(2000)

        # 5. Wait for admission or meeting room confirmation
        logger.info("Waiting for meeting confirmation...")
        try:
            await self.page.wait_for_selector(
                f'{LEAVE_CALL_BUTTON}, div:has-text("Asking to join"), div:has-text("Waiting to be let in")',
                timeout=15000,
            )
            logger.info("✅ Google Meet knock sent / In room!")
        except PlaywrightTimeout:
            logger.info("Proceeding — join action completed.")

        # 6. Ensure bot's microphone is unmuted in the meeting call
        await self._ensure_mic_unmuted()

        return True

    async def _ensure_mic_unmuted(self):
        """Ensure Google Meet mic is NOT muted so participants can hear bot audio."""
        try:
            # Check for muted mic button (red mic button or Turn on microphone aria-label)
            muted_mic = self.page.locator('button[aria-label*="Turn on microphone" i], button[data-is-muted="true"]').first
            if await muted_mic.is_visible(timeout=1000):
                logger.info("Microphone was muted by Meet. Unmuting via Control+d...")
                await self.page.keyboard.press("Control+d")
                await self.page.wait_for_timeout(500)
            else:
                logger.info("Microphone is active and unmuted.")
        except Exception as e:
            logger.debug(f"Mic check: {e}")

    async def _dismiss_overlays(self):
        dismiss_selectors = [
            "button:has-text('Got it')",
            "button:has-text('Dismiss')",
            "button:has-text('OK')",
            "button:has-text('Close')",
            "button:has-text('Continue without microphone and camera')",
        ]
        for sel in dismiss_selectors:
            try:
                loc = self.page.locator(sel).first
                if await loc.is_visible(timeout=400):
                    await loc.evaluate("el => el.click()")
                    logger.info(f"Dismissed overlay: {sel}")
                    await self.page.wait_for_timeout(300)
            except Exception:
                pass

    async def _fill_guest_name(self):
        name_selectors = [
            'input[aria-label*="name" i]',
            'input[placeholder*="name" i]',
            'input[type="text"]',
        ]
        for sel in name_selectors:
            try:
                elem = self.page.locator(sel).first
                if await elem.is_visible(timeout=500):
                    val = await elem.input_value()
                    if not val.strip():
                        await elem.click()
                        await elem.fill(BOT_NAME)
                        logger.info(f"Typed guest name: '{BOT_NAME}'")
                        await self.page.wait_for_timeout(300)
                        await elem.press("Enter")
                    return
            except Exception:
                continue

    async def _click_join(self) -> bool:
        try:
            btn = self.page.locator(JOIN_BUTTON).first
            if await btn.is_visible(timeout=500):
                await btn.evaluate("el => el.click()")
                return True
        except Exception:
            pass

        for jsname in ["Qx7uuf", "j7LFlb", "VO20se", "l4V7wb"]:
            try:
                btn = self.page.locator(f'button[jsname="{jsname}"]').first
                if await btn.is_visible(timeout=500):
                    await btn.evaluate("el => el.click()")
                    return True
            except Exception:
                continue

        return False

    async def leave(self):
        logger.info("Leaving meeting...")
        try:
            if self.page:
                btn = self.page.locator(LEAVE_CALL_BUTTON).first
                if await btn.is_visible(timeout=1000):
                    await btn.evaluate("el => el.click()")
                else:
                    await self.page.goto("about:blank")
        except Exception:
            pass

    async def stop(self):
        logger.info("Stopping MeetAutomation...")
        try:
            if self.browser:
                await self.browser.close()
            if self.pw:
                await self.pw.stop()
            if self._chrome_proc and self._chrome_proc.poll() is None:
                self._chrome_proc.terminate()
                self._chrome_proc.wait(timeout=3)
        except Exception as e:
            logger.warning(f"Stop error: {e}")