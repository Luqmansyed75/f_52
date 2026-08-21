import json
import asyncio
from playwright.async_api import async_playwright


async def main():
    with open("/chrome-profile/google_cookies.json", "r") as f:
        cookies = json.load(f)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        for i, cookie in enumerate(cookies):
            try:
                await context.add_cookies([cookie])
                print(f"OK  #{i}: {cookie.get('name')}")
            except Exception as e:
                print(f"\nBAD #{i}: {cookie.get('name')}")
                print("Fields:", list(cookie.keys()))

                # Don't print the cookie value.
                safe = {
                    k: v
                    for k, v in cookie.items()
                    if k != "value"
                }
                print("Cookie:", safe)
                print("ERROR:", e)

        await browser.close()


asyncio.run(main())
