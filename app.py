import threading
import time
import streamlit as st

from automation.browser import BrowserManager
from automation.auth import AuthManager
from automation.meet import MeetManager

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Google Meet Bot",
    page_icon="🤖",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Shared dict for thread → UI communication (avoids ScriptRunContext errors)
# This is a plain dict; background threads write here, main thread syncs to
# st.session_state on each rerun.
# ---------------------------------------------------------------------------
if "_shared" not in st.session_state:
    st.session_state._shared = {
        "auth_done": False,
        "meeting_status": "idle",
        "status_message": "",
        "_auth_thread_running": False,
        "_join_thread_running": False,
    }

_shared = st.session_state._shared  # module-level alias for threads

# ---------------------------------------------------------------------------
# Sync shared dict → session state (runs on main Streamlit thread)
# ---------------------------------------------------------------------------
for _k, _v in _shared.items():
    st.session_state[_k] = _v


# =========================  AUTH FLOW  =====================================
def _status(msg: str):
    """Set a live status message (thread-safe — writes to shared dict)."""
    _shared["status_message"] = msg


def _run_auth():
    """
    Thread target:
    1. Launch a persistent Chrome browser (uses existing Chrome via CHROME_PATH).
    2. Navigate to accounts.google.com for manual login.
    3. Wait until the user closes the browser window.
    4. Launch a FRESH browser on the same profile to verify login.
    """
    browser = None
    verify_browser = None
    try:
        _status("🟡 Opening Chrome browser for Google login...")
        browser = BrowserManager()
        page = browser.launch()

        auth = AuthManager(page)
        auth.login()  # navigates to accounts.google.com, then waits (polls until browser closed or login detected)

        # User has closed the browser → close our handle
        _status("🟢 Browser closed. Verifying login...")
        browser.close()
        browser = None
        time.sleep(1)

        # Launch a temporary browser with the same profile to check login
        _status("🟢 Checking authentication status...")
        verify_browser = BrowserManager()
        verify_page = verify_browser.launch()
        verify_auth = AuthManager(verify_page)

        if verify_auth.is_logged_in():
            email = verify_auth.get_logged_in_email()
            if email:
                _status(f"✅ Google account connected: {email}")
            else:
                _status("✅ Google account connected!")
            _shared["auth_done"] = True
        else:
            _status("❌ Login verification failed. Please try again.")

    except Exception as e:
        _status(f"❌ Auth error: {e}")
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if verify_browser:
            try:
                verify_browser.close()
            except Exception:
                pass
        _shared["_auth_thread_running"] = False


# =====================  JOIN MEET FLOW  ====================================
def _run_join(meet_url: str):
    """
    Thread target:
    1. Launch browser with the stored profile.
    2. Navigate to the Meet URL.
    3. Wait for green room, mute, click join.
    4. Wait for admission, then monitor until the meeting ends.
    """
    browser = None
    try:
        _status("🟡 Launching browser...")
        browser = BrowserManager()
        page = browser.launch()
        meet = MeetManager(page)

        # ---- Enter green room ----
        _status("🟡 Navigating to the meeting...")
        if not meet.enter_green_room(meet_url):
            _shared["meeting_status"] = "error"
            _status("❌ Could not load the green room (join button not found).")
            return

        # ---- Mute ----
        _status("🟡 Turning off mic & camera...")
        meet.mute_all()

        # ---- Join ----
        _status("🟡 Clicking join button...")
        meet.click_join()

        # ---- Wait for admission ----
        _status("🟡 Waiting for host to let you in...")
        if meet.wait_for_admission():
            _shared["meeting_status"] = "connected"
            _status("✅ Connected to the meeting!")
        else:
            _shared["meeting_status"] = "error"
            _status("❌ Host did not admit us, or the meeting ended.")
            return

        # ---- Monitor ----
        _status("🟡 In the meeting – monitoring...")
        reason = meet.monitor_until_end(fallback_minutes=30)
        _status(f"✅ Meeting ended (reason: {reason}). Browser closed.")

    except Exception as e:
        _shared["meeting_status"] = "error"
        _status(f"❌ Error: {e}")
    finally:
        _shared["meeting_status"] = "idle"
        _shared["_join_thread_running"] = False
        if browser:
            try:
                browser.close()
            except Exception:
                pass


# =========================  UI  ============================================
st.title("🤖 Google Meet Bot")
st.markdown(
    "Automatically join Google Meet meetings using your existing Chrome browser."
)
st.caption("Uses a persistent Chrome profile — login once, reuse forever.")

st.divider()

# ---- Step 1: Connect Google Account ----
st.subheader("Step 1: Connect Google Account")
st.caption(
    "One-time setup. A Chrome window will open for you to log in. "
    "Close the browser when done."
)

if st.session_state.auth_done:
    st.success("✅ Google account is connected.")
else:
    btn_disabled = st.session_state._auth_thread_running
    if st.button(
        "🔗 Connect Google Account",
        type="primary",
        disabled=btn_disabled,
    ):
        _shared["_auth_thread_running"] = True
        _shared["status_message"] = "🟡 Opening browser..."
        thread = threading.Thread(target=_run_auth, daemon=True)
        thread.start()
        st.rerun()

st.divider()

# ---- Step 2: Paste meeting URL ----
st.subheader("Step 2: Paste Meeting URL")
meet_url = st.text_input(
    "Google Meet URL",
    placeholder="https://meet.google.com/abc-defg-hij",
    label_visibility="collapsed",
)

st.divider()

# ---- Step 3: Join ----
st.subheader("Step 3: Join Meeting")

col1, col2 = st.columns([1, 1])
with col1:
    join_disabled = (
        not st.session_state.auth_done
        or not meet_url.strip()
        or st.session_state._join_thread_running
    )
    if st.button(
        "🎥 Join Meeting",
        type="primary",
        use_container_width=True,
        disabled=join_disabled,
    ):
        _shared["_join_thread_running"] = True
        _shared["meeting_status"] = "joining"
        _shared["status_message"] = "🟡 Starting the bot..."
        thread = threading.Thread(
            target=_run_join, args=(meet_url.strip(),), daemon=True
        )
        thread.start()
        st.rerun()

with col2:
    if st.button("🔄 Reset", use_container_width=True):
        st.session_state.meeting_status = "idle"
        st.session_state.status_message = ""
        st.rerun()

st.divider()

# ---- Live Status ----
st.subheader("📡 Live Status")

status = st.session_state.meeting_status
if status == "idle":
    if st.session_state.status_message:
        st.info(st.session_state.status_message)
    else:
        st.info("Awaiting your instructions...")
elif status == "joining":
    st.warning(st.session_state.status_message or "Joining...")
elif status == "connected":
    st.success(st.session_state.status_message or "Connected!")
elif status == "error":
    st.error(st.session_state.status_message or "Something went wrong.")

# Auto-refresh while a background thread is running
if st.session_state._auth_thread_running or st.session_state._join_thread_running:
    time.sleep(1)
    st.rerun()