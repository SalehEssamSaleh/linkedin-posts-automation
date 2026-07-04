"""
LinkedIn UX/UI Keyword Monitoring Automation
=============================================
Searches DuckDuckGo for recent LinkedIn posts/articles matching a list of
UX/UI keywords (Arabic + English), keeps only genuine LinkedIn post/article
links, generates a suggested reply with Gemini, and logs everything into a
Google Sheet - one new tab per week.

Runs automatically once a week via GitHub Actions
(.github/workflows/daily_search.yml). Can also be triggered manually from
the Actions tab ("Run workflow").
"""

import re
import json
import time
import random
import datetime as dt

import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from langdetect import detect
from ddgs import DDGS

import config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SHEET_HEADERS = [
    "No.",
    "Type",
    "Keyword Matched",
    "Content",
    "Link",
    "Date Published",
    "Language",
    "Suggested Reply",
]

SEEN_TAB_NAME = "SeenURLs"

POST_PATTERN = re.compile(r"linkedin\.com/(posts|feed/update)/", re.I)
# /pulse/topics/... are topic hub/listing pages, not real articles — exclude them
ARTICLE_PATTERN = re.compile(r"linkedin\.com/pulse/(?!topics/)", re.I)

RELATIVE_EN = re.compile(r"(\d+)\s*(minute|min|hour|hr|day|week)s?\s*ago", re.I)
RELATIVE_AR = re.compile(r"منذ\s*(\d+)\s*(دقيقة|ساعة|يوم|أسبوع)")
AR_UNIT_MAP = {"دقيقة": "minute", "ساعة": "hour", "يوم": "day", "أسبوع": "week"}

# Absolute written-out dates like "July 18, 2022" or "March 10, 2024" — these
# show up constantly in LinkedIn snippets and were being missed entirely
# before, letting years-old content slip through as "unverified" instead of
# correctly getting rejected as too old.
ABSOLUTE_EN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b",
    re.I,
)
MONTH_NUMBERS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

START_TIME = time.monotonic()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def time_budget_exceeded():
    elapsed_minutes = (time.monotonic() - START_TIME) / 60
    return elapsed_minutes >= config.TIME_BUDGET_MINUTES


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def week_tab_name(when):
    """e.g. '1st week of July'"""
    week_of_month = (when.day - 1) // 7 + 1
    return f"{ordinal(week_of_month)} week of {when.strftime('%B')}"


def classify_url(url):
    if POST_PATTERN.search(url):
        return "Post"
    if ARTICLE_PATTERN.search(url):
        return "Article"
    return None


def parse_relative_date(text):
    """Best-effort extraction of a publish date from a search snippet —
    tries relative phrases ('3 days ago') first, then absolute written-out
    dates ('July 18, 2022'), since both show up constantly in real snippets."""
    now = dt.datetime.now(dt.timezone.utc)

    m = RELATIVE_EN.search(text)
    if m:
        amount, unit = int(m.group(1)), m.group(2).lower()
        if unit.startswith("min"):
            delta = dt.timedelta(minutes=amount)
        elif unit.startswith(("hour", "hr")):
            delta = dt.timedelta(hours=amount)
        elif unit.startswith("day"):
            delta = dt.timedelta(days=amount)
        elif unit.startswith("week"):
            delta = dt.timedelta(weeks=amount)
        else:
            return None
        return now - delta

    m = RELATIVE_AR.search(text)
    if m:
        amount, unit = int(m.group(1)), AR_UNIT_MAP[m.group(2)]
        if unit.startswith("min"):
            delta = dt.timedelta(minutes=amount)
        elif unit.startswith(("hour", "hr")):
            delta = dt.timedelta(hours=amount)
        elif unit.startswith("day"):
            delta = dt.timedelta(days=amount)
        elif unit.startswith("week"):
            delta = dt.timedelta(weeks=amount)
        else:
            return None
        return now - delta

    m = ABSOLUTE_EN.search(text)
    if m:
        month_name, day, year = m.group(1).lower(), int(m.group(2)), int(m.group(3))
        month_num = MONTH_NUMBERS.get(month_name)
        if month_num:
            try:
                return dt.datetime(year, month_num, day, tzinfo=dt.timezone.utc)
            except ValueError:
                return None

    return None


def parse_iso_date(date_str):
    """Parse a JSON-LD datePublished string into an aware UTC datetime."""
    if not date_str:
        return None
    cleaned = date_str.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def fetch_real_date(url):
    """Best-effort SINGLE attempt to grab the real JSON-LD datePublished
    from the LinkedIn page itself — no retries, short timeout. If LinkedIn
    blocks/rate-limits/times out, we just return None and fall back to the
    DDG-snippet-based guess instead of hammering it with retries."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=8,
        )
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("datePublished"):
                return item["datePublished"]
    return None


def is_within_window(published_dt):
    """True/False if we can judge it, None if published_dt is unknown."""
    if published_dt is None:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    age = now - published_dt
    return dt.timedelta(minutes=-10) <= age <= dt.timedelta(hours=config.SEARCH_WINDOW_HOURS)


def detect_language(text):
    try:
        code = detect(text)
    except Exception:
        return "Unknown"
    if code == "ar":
        return "Arabic"
    if code == "en":
        return "English"
    return code


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
def init_gemini():
    genai.configure(api_key=config.GEMINI_API_KEY)
    models = [m for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
    if not models:
        raise RuntimeError("No Gemini model supporting generateContent was found.")
    # Prefer lighter models first — "flash-lite" / "flash" variants generally
    # carry more generous free-tier quotas than "pro" models.
    preference_order = ["flash-lite", "flash", "pro"]

    def rank(m):
        name = m.name.lower()
        for i, key in enumerate(preference_order):
            if key in name:
                return i
        return len(preference_order)

    models.sort(key=rank)
    chosen = models[0]
    print(f"[Gemini] Using model: {chosen.name}")
    return genai.GenerativeModel(chosen.name)


# Once we detect Gemini's quota is genuinely exhausted (not just a transient
# per-minute blip), stop calling the API for the rest of this run — retrying
# a hard quota error wastes time on every remaining row for zero benefit.
_gemini_quota_exhausted = False

FALLBACK_REPLIES = {
    "Arabic": "محتوى قيم، شكراً على المشاركة!",
    "English": "Great insights here — thanks for sharing!",
}


def generate_reply(model, content, language):
    global _gemini_quota_exhausted
    target_lang = "Arabic" if language == "Arabic" else "English"

    if _gemini_quota_exhausted:
        return FALLBACK_REPLIES[target_lang]

    prompt = (
        "You are a UX/UI professional writing a short, genuine, friendly "
        "LinkedIn comment replying to the post below. Keep it under 40 "
        f"words, and write it in {target_lang}.\n\nPOST:\n{content}"
    )
    last_error = None
    for attempt in range(1, 4):  # up to 3 tries total
        try:
            time.sleep(random.uniform(3, 5))  # pace calls to respect per-minute limits
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            last_error = e
            error_text = str(e).lower()
            if "exceeded your current quota" in error_text or "quota" in error_text:
                print(f"[Gemini] Quota exhausted — switching to template replies "
                      f"for the rest of this run: {e}")
                _gemini_quota_exhausted = True
                return FALLBACK_REPLIES[target_lang]
            wait = 5 * attempt
            print(f"[Gemini] reply generation failed (attempt {attempt}/3): {e} "
                  f"— retrying in {wait}s")
            time.sleep(wait)
    print(f"[Gemini] giving up after 3 attempts: {last_error}")
    return FALLBACK_REPLIES[target_lang]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search_keyword(keyword, consecutive_429):
    """Runs one DuckDuckGo search for a keyword. Returns (results, consecutive_429)."""
    # Target post/article paths directly instead of a bare site:linkedin.com
    # search — a bare search returns mostly profiles/companies/jobs, which is
    # why most results were getting rejected as not_post_or_article before.
    # No timelimit here on purpose: DDG's timelimit + site: combo has
    # historically returned 0 results even when real matches exist — we
    # filter for recency ourselves afterward using the real/parsed date.
    query = (
        f'(site:linkedin.com/posts OR site:linkedin.com/feed/update '
        f'OR site:linkedin.com/pulse) "{keyword}"'
    )
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            results = list(DDGS().text(query, max_results=35, backend="duckduckgo"))
            return results, 0  # success resets the 429 streak
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "ratelimit" in msg or "rate limit" in msg:
                consecutive_429 += 1
                wait = config.BACKOFF_BASE_SECONDS * (2 ** attempt)
                print(
                    f"[Search] 429 on '{keyword}' "
                    f"(attempt {attempt + 1}/{config.MAX_RETRIES + 1}, "
                    f"consecutive={consecutive_429}). Waiting {wait}s."
                )
                time.sleep(wait)
                if consecutive_429 >= config.CONSECUTIVE_429_LIMIT:
                    print("[Search] Circuit breaker tripped. Stopping search for this run.")
                    return [], consecutive_429
                continue
            print(f"[Search] Error on '{keyword}': {e}")
            return [], consecutive_429
    return [], consecutive_429


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------
def open_sheet():
    creds_info = json.loads(config.GOOGLE_SHEETS_CREDENTIALS)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(config.SHEET_ID)


def get_or_create_seen_tab(spreadsheet):
    try:
        ws = spreadsheet.worksheet(SEEN_TAB_NAME)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=SEEN_TAB_NAME, rows=2000, cols=1)
        ws.update("A1", [["URL"]])
        try:
            spreadsheet.batch_update(
                {
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": ws.id, "hidden": True},
                                "fields": "hidden",
                            }
                        }
                    ]
                }
            )
        except Exception:
            pass
    return ws


def load_seen_urls(seen_ws):
    values = seen_ws.col_values(1)[1:]  # skip header
    return set(values)


def get_or_create_week_tab(spreadsheet, when):
    title = week_tab_name(when)
    try:
        ws = spreadsheet.worksheet(title)
        existing_rows = max(len(ws.get_all_values()) - 1, 0)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=500, cols=len(SHEET_HEADERS))
        ws.update("A1", [SHEET_HEADERS])
        existing_rows = 0
    return ws, existing_rows


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------
def run():
    print("=== LinkedIn UX/UI Keyword Monitoring - starting run ===")

    spreadsheet = open_sheet()
    seen_ws = get_or_create_seen_tab(spreadsheet)
    seen_urls = load_seen_urls(seen_ws)

    now = dt.datetime.now()
    week_ws, existing_rows = get_or_create_week_tab(spreadsheet, now)
    next_no = existing_rows + 1

    model = init_gemini()

    new_seen_rows = []
    consecutive_429 = 0
    stats = {"found": 0, "added": 0, "duplicate": 0, "not_post_or_article": 0,
              "too_old": 0, "unverifiable_date": 0, "skipped_cap": 0}

    for keyword in config.KEYWORDS:
        if time_budget_exceeded():
            print("[Run] Time budget reached. Stopping.")
            break

        print(f"[Search] Keyword: {keyword}")
        results, consecutive_429 = search_keyword(keyword, consecutive_429)
        if consecutive_429 >= config.CONSECUTIVE_429_LIMIT:
            break

        stats["found"] += len(results)
        fetches_this_keyword = 0

        for r in results:
            if time_budget_exceeded():
                print(f"[Run] Time budget reached mid-keyword ('{keyword}'). Stopping.")
                break

            url = r.get("href", "")
            title = r.get("title", "")
            body = r.get("body", "")

            post_type = classify_url(url)
            if not post_type:
                stats["not_post_or_article"] += 1
                continue

            if url in seen_urls:
                stats["duplicate"] += 1
                continue

            if fetches_this_keyword >= config.MAX_FETCHES_PER_KEYWORD:
                # Cap reached for this keyword — skip remaining candidates
                # rather than fetch every single one. This bounds worst-case
                # run time regardless of how many keywords are configured,
                # since it's the per-candidate fetch that's expensive, not
                # the search itself.
                stats["skipped_cap"] += 1
                continue
            fetches_this_keyword += 1

            content = f"{title} - {body}".strip(" -")

            # Try once for the real, verified date. If LinkedIn blocks/times
            # out, fall back to a snippet-based estimate rather than retry.
            real_date_str = fetch_real_date(url)
            time.sleep(random.uniform(1, 3))  # small pacing gap per URL fetch

            if real_date_str:
                published = parse_iso_date(real_date_str)
                date_source = "verified" if published else "unknown"
            else:
                published = parse_relative_date(body)
                date_source = "estimated" if published else "unknown"

            within = is_within_window(published)
            if within is not True:
                # Either genuinely too old, or we couldn't determine a date
                # at all. Both get dropped now — precision over volume: a
                # result we can't verify as recent isn't worth keeping.
                if within is False:
                    stats["too_old"] += 1
                else:
                    stats["unverifiable_date"] += 1
                continue

            date_str = published.strftime("%Y-%m-%d")
            if date_source == "estimated":
                date_str += " (estimated)"

            language = detect_language(content) if content else "Unknown"
            reply = generate_reply(model, content, language)

            week_ws.append_row(
                [next_no, post_type, keyword, content, url, date_str, language, reply],
                value_input_option="RAW",
            )
            seen_urls.add(url)
            new_seen_rows.append([url])
            next_no += 1
            stats["added"] += 1

        time.sleep(random.uniform(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS))

    if new_seen_rows:
        seen_ws.append_rows(new_seen_rows, value_input_option="RAW")

    print("=== Run summary ===")
    for k, v in stats.items():
        print(f"{k}: {v}")
    print("=== Done ===")


if __name__ == "__main__":
    run()
