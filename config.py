from pathlib import Path

# Change this if Chrome is installed elsewhere
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

BASE_DIR = Path(__file__).parent

PROFILE_DIR = BASE_DIR / "profiles" / "chrome"

HEADLESS = False

# Port for Chrome DevTools Protocol (remote debugging)
DEBUG_PORT = 9222