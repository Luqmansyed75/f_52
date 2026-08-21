# tools/export_auth.py
import os
import json
import sqlite3
import shutil
import base64
import win32crypt
from Crypto.Cipher import AES

CHROME_PATH = os.path.expanduser(r'~\AppData\Local\Google\Chrome\User Data')
LOCAL_STATE_PATH = os.path.join(CHROME_PATH, 'Local State')

# ── Find the aiproxy52 profile automatically ──────────────────────────────────
def find_aiproxy_profile():
    import re
    for name in ['Default'] + [f'Profile {i}' for i in range(1, 20)]:
        pref_path = os.path.join(CHROME_PATH, name, 'Preferences')
        if not os.path.exists(pref_path):
            continue
        try:
            content = open(pref_path, 'r', encoding='utf-8').read()
            if 'aiproxy52' in content:
                print(f"Found aiproxy52 in profile: {name}")
                return name
        except Exception:
            continue
    print("WARNING: aiproxy52 not found in any profile — using Default")
    return 'Default'

PROFILE = find_aiproxy_profile()
COOKIES_PATH = os.path.join(CHROME_PATH, PROFILE, 'Network', 'Cookies')

def get_encryption_key():
    with open(LOCAL_STATE_PATH, "r", encoding="utf-8") as f:
        local_state = json.load(f)
    key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
    key = key[5:]  # Remove DPAPI prefix
    return win32crypt.CryptUnprotectData(key, None, None, None, 0)[1]

def decrypt_data(data, key):
    try:
        iv = data[3:15]
        payload = data[15:]
        cipher = AES.new(key, AES.MODE_GCM, iv)
        return cipher.decrypt(payload)[:-16].decode('utf-8', errors='replace')
    except Exception:
        return ""

def export_cookies():
    if not os.path.exists(COOKIES_PATH):
        print(f"ERROR: Cookie file not found at {COOKIES_PATH}")
        return

    key = get_encryption_key()
    shutil.copyfile(COOKIES_PATH, "temp_cookies.db")

    db = sqlite3.connect("temp_cookies.db")
    cursor = db.cursor()

    cursor.execute("""
        SELECT host_key, name, value, encrypted_value,
               path, is_secure, is_httponly, samesite, expires_utc
        FROM cookies
        WHERE host_key LIKE '%google.com%'
    """)

    cookies = []
    for host, name, value, enc_value, path, secure, httponly, samesite, expires in cursor.fetchall():
        # Decrypt if needed
        if enc_value and not value:
            decrypted = decrypt_data(enc_value, key)
        else:
            decrypted = value

        if not decrypted:
            continue

        # Map samesite integer to string
        samesite_map = {0: "Lax", 1: "Strict", 2: "None", -1: "Lax"}
        samesite_str = samesite_map.get(samesite, "Lax")

        # Playwright requires sameSite="None" cookies to have secure=True
        is_secure = bool(secure) or name.startswith("__Secure-") or name.startswith("__Host-")

        cookie = {
            "name": name,
            "value": decrypted,
            "domain": host,
            "path": path or "/",
            "secure": is_secure,
            "httpOnly": bool(httponly),
            "sameSite": samesite_str,
        }

        # Add expiry if set (convert Chrome epoch to Unix epoch)
        # Chrome epoch starts 1601-01-01, Unix epoch starts 1970-01-01
        # Difference = 11644473600 seconds
        if expires and expires > 0:
            unix_expires = (expires / 1_000_000) - 11644473600
            if unix_expires > 0:
                cookie["expires"] = int(unix_expires)

        cookies.append(cookie)

    db.close()
    os.remove("temp_cookies.db")

    with open("google_cookies.json", "w") as f:
        json.dump(cookies, f, indent=2)

    print(f"✅ Exported {len(cookies)} cookies from profile '{PROFILE}' to google_cookies.json")
    
    # Show which critical cookies were found
    critical = ['__Secure-3PSID', '__Secure-3PAPISID', 'SAPISID', 'SID', 'HSID', 'SSID']
    found = [c['name'] for c in cookies if c['name'] in critical]
    print(f"   Critical auth cookies: {found}")

if __name__ == "__main__":
    export_cookies()