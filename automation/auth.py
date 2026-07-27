import time
from urllib.parse import urlparse
from playwright.sync_api import Page


class AuthManager:
    """Manages Google authentication using a persistent Chrome profile."""

    def __init__(self, page: Page):
        self.page = page

    def login(self, poll_interval: float = 2.0, max_wait_minutes: int = 10):
        """
        Open Google login page and wait for the user to authenticate.
        Polls the page to detect when the user has completed login or
        closed the browser.

        Parameters
        ----------
        poll_interval : float
            Seconds between each status check.
        max_wait_minutes : int
            Maximum minutes to wait before giving up.
        """
        self.page.goto("https://accounts.google.com")

        max_attempts = int((max_wait_minutes * 60) / poll_interval)

        for _ in range(max_attempts):
            # Detect if the browser/page context was closed
            try:
                current_url = self.page.url
            except Exception:
                # Browser closed — stop
                return

            # If we've navigated away from accounts.google.com/*login*,
            # the user has likely completed authentication
            parsed = urlparse(current_url)
            if "accounts.google.com" not in parsed.netloc:
                # Redirected away from login — consider it done
                return

            time.sleep(poll_interval)

    def is_logged_in(self) -> bool:
        """
        Navigate to myaccount.google.com and check if the user is signed in.
        Returns True if the page title does NOT contain "Sign in".

        Note: this navigates the page, so call it only after the user
        has finished the login flow.
        """
        try:
            self.page.goto(
                "https://myaccount.google.com",
                wait_until="networkidle",
                timeout=15000,
            )
            time.sleep(1.5)  # allow any redirects to settle
            title = self.page.title()
            return "Sign in" not in title
        except Exception:
            # Page likely closed — not logged in
            return False

    def get_logged_in_email(self) -> str | None:
        """
        Attempt to retrieve the logged-in email from myaccount page.
        Returns the email string, or None if not logged in / page closed.
        """
        try:
            self.page.goto("https://myaccount.google.com", wait_until="domcontentloaded")
            # The email often appears in elements like:
            #   <div class="gb_7b">user@gmail.com</div>
            email_el = self.page.query_selector(".gb_7b")
            if email_el:
                return email_el.inner_text()
            return None
        except Exception:
            return None