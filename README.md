# 🤖 Proxy Agent — Google Meet Bot

Automatically join Google Meet meetings using your **existing Chrome browser**.  
Login once — session is saved and reused.

---

## Quick Start

```bash
cd proxy-agent
uv sync
playwright install chromium
streamlit run app.py
```

Then:
1. Click **Connect Google Account** → log in → close Chrome.
2. Paste a Meet URL.
3. Click **Join Meeting**.

---

## How it works

- Launches your real Chrome via DevTools Protocol (stealth — no automation flags).
- Connects Playwright over CDP to control it.
- Opens Meet, mutes mic/cam, clicks Join, waits for host, monitors until meeting ends.

---

## Project Structure

```
app.py                         # Streamlit UI
config.py                      # Chrome path, profile dir
automation/
    browser.py                 # Launches Chrome via CDP
    auth.py                    # Google login + verification
    meet.py                    # Join + monitor meeting
    selectors.py               # CSS selectors for Google Meet
profiles/chrome/               # Persistent Chrome profile
```

---

## Configure

Edit `config.py` if Chrome is installed elsewhere:

```python
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
```

---

## License

MIT