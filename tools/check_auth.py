import asyncio
from playwright.async_api import async_playwright


async def check_auth():
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir="/chrome-profile",
            headless=True,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        page = await context.new_page()

        # Check Google account
        await page.goto(
            "https://myaccount.google.com/",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        await page.wait_for_timeout(3000)

        print("Account page URL:", page.url)

        await page.screenshot(
            path="/chrome-profile/account_check.png",
            full_page=True,
        )

        text = await page.evaluate(
            "() => document.body.innerText.substring(0, 500)"
        )
        print("Account page text:", text)

        # Check Google Accounts
        await page.goto(
            "https://accounts.google.com/",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        await page.wait_for_timeout(2000)

        print("Accounts URL:", page.url)

        text2 = await page.evaluate(
            "() => document.body.innerText.substring(0, 300)"
        )
        print("Accounts text:", text2)

        await context.close()


asyncio.run(check_auth())