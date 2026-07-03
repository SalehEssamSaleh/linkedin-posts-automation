"""
Configuration for the LinkedIn UX/UI Keyword Monitor.

Edit KEYWORDS to add/remove search terms. Everything else here controls
the new (STEP 3) search sources and safety knobs — see handoff.md for
which sources are verified vs. best-effort/⚠️ unverified.
"""
import json
import os

# ---------------------------------------------------------------------------
# Keywords (user-editable)
# ---------------------------------------------------------------------------
KEYWORDS = [
    "UX/UI",
    "تجربة المستخدم",
    "فحص تجربة المستخدم",
    "رحلة المستخدم",
    "تصميم تجربة المستخدم",
    "هيئة الحكومة الرقمية",
    "معايير هيئة الحكومة الرقمية",
    "مؤشر نضج التجربة الرقمية",
    "مؤشر قياس التجربة الرقمية",
    "UX Research / أبحاث تجربة المستخدم",
    "Usability Testing / اختبار قابلية الاستخدام",
    "تصميم واجهة المستخدم",
    "Human-Centered Design / التصميم المتمحور حول الإنسان",
    "تصميم الخدمات (Service Design)",
    "التفكير التصميمي (Design Thinking)",
    "التحول الرقمي (Digital Transformation)",
    "تجربة العميل (Customer Experience)",
    "هندسة المعلومات (Information Architecture)",
]

# ---------------------------------------------------------------------------
# Search window
# ---------------------------------------------------------------------------
SEARCH_WINDOW_HOURS = 24

# ---------------------------------------------------------------------------
# Rate limiting / retry — daily runs across ~18 keywords hit free search
# sources much harder than the old weekly job. Be polite.
# ---------------------------------------------------------------------------
MIN_DELAY_SECONDS = 4
MAX_DELAY_SECONDS = 9
MAX_RETRIES = 2
BACKOFF_BASE_SECONDS = 4

# Hard internal time budget for the whole run. The GitHub Actions job has a
# 60-minute timeout (see workflow file); this stops new work at 48 minutes so
# there's always time left to write whatever was already found to the Sheet,
# instead of the job getting killed mid-run with nothing saved.
TIME_BUDGET_SECONDS = 48 * 60

# ---------------------------------------------------------------------------
# Source B: Google Alerts delivered as RSS
#
# Google has no public API to create Alerts programmatically — this is a
# ONE-TIME MANUAL SETUP per keyword:
#   1. Go to https://www.google.com/alerts while signed in
#   2. Query:  (site:linkedin.com/posts OR site:linkedin.com/feed/update) "<keyword>"
#   3. Click "Show options" -> "Deliver to" -> "RSS feed"
#   4. Copy the feed URL Google gives you
#
# Supply the mapping either by editing ALERT_RSS_FEEDS below, or (recommended,
# so you don't need a commit every time you add an alert) as a GitHub Actions
# secret/variable named ALERT_RSS_FEEDS_JSON containing:
#   {"UX/UI": "https://www.google.com/alerts/feeds/.../...", ...}
#
# If a keyword has no feed configured, Source B is simply skipped for it —
# this is expected and not an error.
# ---------------------------------------------------------------------------
ALERT_RSS_FEEDS: dict[str, str] = {}
_env_feeds = os.environ.get("ALERT_RSS_FEEDS_JSON")
if _env_feeds:
    try:
        ALERT_RSS_FEEDS.update(json.loads(_env_feeds))
    except json.JSONDecodeError:
        pass  # malformed secret — fail soft, source is skipped

# ---------------------------------------------------------------------------
# Source C: self-hosted SearXNG instance (optional, OFF by default)
# ⚠️ Not live-verified in development — free-tier hosting terms on
# Render/Fly.io/etc. change often. Leave SEARXNG_INSTANCE_URL unset to skip
# this source entirely. If you stand one up, set it as a repo secret.
# ---------------------------------------------------------------------------
SEARXNG_INSTANCE_URL = os.environ.get("SEARXNG_INSTANCE_URL", "").strip()

# ---------------------------------------------------------------------------
# Source D: Mojeek Search API (optional, OFF by default)
# ⚠️ Not live-verified in development. Confirm Mojeek's current free-tier
# terms (no card required) at https://www.mojeek.com/services/search before
# enabling. Leave MOJEEK_API_KEY unset to skip.
# ---------------------------------------------------------------------------
MOJEEK_API_KEY = os.environ.get("MOJEEK_API_KEY", "").strip()

# Yandex XML/Search API was evaluated per STEP 3(d) and NOT wired in:
# historically requires account verification tied to a phone number / site
# ownership and has had access disruptions for accounts outside Russia.
# That friction/uncertainty was judged not worth it within the 30-min
# timebox. Revisit only if you specifically need it and can verify current
# terms yourself.
