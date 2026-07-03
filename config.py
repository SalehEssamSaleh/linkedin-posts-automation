"""
Configuration for LinkedIn UX/UI Keyword Monitoring Automation.
"""

import os

# ---------------------------------------------------------------------------
# Keywords to search for (Arabic + English UX/UI terms)
# ---------------------------------------------------------------------------
KEYWORDS = [
    "UX/UI",
    "UX Design",
    "UI Design",
    "User Experience",
    "User Interface",
    "Product Design",
    "UX Research",
    "Usability Testing",
    "Interaction Design",
    "Design Thinking",
    "Wireframing",
    "Prototyping",
    "Figma",
    "تجربة المستخدم",
    "واجهة المستخدم",
    "تصميم تجربة المستخدم",
    "تصميم واجهات",
    "مصمم UX",
]

# ---------------------------------------------------------------------------
# Search window: how far back (in hours) we accept posts as "recent".
# Weekly run -> 7 days = 168 hours.
# ---------------------------------------------------------------------------
SEARCH_WINDOW_HOURS = 168

# ---------------------------------------------------------------------------
# Rate limiting / retry behaviour (protects against LinkedIn / DDG 429s)
# ---------------------------------------------------------------------------
MIN_DELAY_SECONDS = 6
MAX_DELAY_SECONDS = 13
MAX_RETRIES = 2
BACKOFF_BASE_SECONDS = 4
CONSECUTIVE_429_LIMIT = 5

# ---------------------------------------------------------------------------
# Overall time budget for a single run, in minutes.
# GitHub Actions job timeout is 60 min; we stop early to always finish clean.
# ---------------------------------------------------------------------------
TIME_BUDGET_MINUTES = 48

# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------
SHEET_ID = os.environ.get("SHEET_ID", "")
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
