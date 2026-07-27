"""
CSS selectors and locators for Google Meet elements.
These may need updating if Google changes their DOM structure.
"""

# --- Green room / pre-join screen ---
JOIN_BUTTON = "button:has-text('Join now'), button:has-text('Ask to join')"
MIC_BUTTON = "button[data-is-muted]"
CAM_BUTTON = "button[data-is-muted]"

# --- In-meeting controls ---
LEAVE_CALL_BUTTON = 'button[aria-label="Leave call"]'

# --- End-of-meeting detection ---
END_SCREEN_TEXT = (
    "text=You left the meeting,"
    " text=Meeting ended,"
    " text=Call ended"
)