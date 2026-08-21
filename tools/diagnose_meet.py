import asyncio
from playwright.async_api import async_playwright
import json

async def diagnose():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
                  "--use-fake-ui-for-media-stream","--use-fake-device-for-media-stream"]
        )
        ctx = await browser.new_context(
            viewport={"width":1280,"height":800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        cookies = json.load(open("/chrome-profile/google_cookies.json"))
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        await page.goto("https://meet.google.com/wrg-ompr-umw", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        print("URL:", page.url)
        print("TITLE:", await page.title())
        await page.screenshot(path="/chrome-profile/meet_debug.png", full_page=True)
        buttons = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button')).map(b => ({
                text: b.innerText.trim(),
                aria: b.getAttribute('aria-label'),
                jsname: b.getAttribute('jsname'),
                visible: b.offsetParent !== null
            })).filter(b => b.text || b.aria);
        }""")
        print("BUTTONS:", buttons)
        text = await page.evaluate("() => document.body.innerText.substring(0, 800)")
        print("PAGE TEXT:", text)
        await browser.close()

asyncio.run(diagnose())
