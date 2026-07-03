"""
LinkedIn UX/UI Keyword Monitor — daily orchestrator.

Pipeline: multi-source search -> classify (post/article) -> validate URL ->
extract JSON-LD date -> dedupe against seen URLs -> detect language ->
generate Gemini reply -> write to Google Sheets.

Sources (see config.py and handoff.md for status of each):
  A. DuckDuckGo, single combined query per keyword            (carried over, reshaped per STEP 3c)
  B. Google Alerts RSS feed per keyword                        (⚠️ needs manual one-time setup, see config.py)
  C. Self-hosted SearXNG instance                              (⚠️ unverified, off unless configured)
  D. Mojeek Search API                                         (⚠️ unverified, off unless configured)

Every source is wrapped so a failure/format-change in one never takes down
the whole run — it just contributes zero results and gets logged.
"""
import hashlib
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover
    DDGS = None

try:
    import feedparser
except ImportError:  # pragma: no cover
    feedparser = None

try:
    from langdetect import detect as _langdetect, LangDetectException
except ImportError:  # pragma: no cover
    _langdetect = None
    LangDetectException = Exception

import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

from config import (
    KEYWORDS,
    SEARCH_WINDOW_HOURS,
    MIN_DELAY_SECONDS,
    MAX_DELAY_SECONDS,
    MAX_RETRIES,
    BACKOFF_BASE_SECONDS,
    ALERT_RSS_FEEDS,
    SEARXNG_INSTANCE_URL,
    MOJEEK_API_KEY,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("linkedin-monitor")

SHEET_ID = os.environ["SHEET_ID"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_SHEETS_CREDENTIALS = os.environ["GOOGLE_SHEETS_CREDENTIALS"]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en,ar;q=0.8"}

POST_MARKERS = ("/posts/", "/feed/update/")
ARTICLE_MARKER = "/pulse/"
EXCLUDE_MARKERS = ("/jobs/", "/company/", "/showcase/")

BLOCKED_TITLE_HINTS = ("sign up", "join linkedin", "authwall", "security check", "log in")
BLOCKED_BODY_HINTS = ("was not found", "no longer available", "page not found")
BLOCKED_REDIRECT_HINTS = ("authwall", "checkpoint", "login", "signup")

# Run-wide stats for the transparency requirement (STEP 5)
RUN_STATS = {
    "by_source": {},   # source -> {"post": n, "article": n, "raw": n}
    "totals": {"post": 0, "article": 0},
}


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------
def polite_sleep():
    time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))


def with_retry(fn, *args, retries=MAX_RETRIES, label="call", **kwargs):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — deliberately broad, fail soft
            last_exc = exc
            wait = BACKOFF_BASE_SECONDS * attempt + random.uniform(0, 2)
            log.warning("%s failed (attempt %d/%d): %s — backing off %.1fs",
                        label, attempt, retries, exc, wait)
            time.sleep(wait)
    log.error("%s failed after %d attempts: %s", label, retries, last_exc)
    return None


def record_stat(source, kind):
    bucket = RUN_STATS["by_source"].setdefault(source, {"post": 0, "article": 0, "raw": 0})
    bucket[kind] += 1
    if kind in ("post", "article"):
        RUN_STATS["totals"][kind] += 1


def classify_url(url: str):
    """Return 'post', 'article', or None (not a relevant LinkedIn URL)."""
    if "linkedin.com" not in url:
        return None
    if any(marker in url for marker in EXCLUDE_MARKERS):
        return None
    if ARTICLE_MARKER in url:
        return "article"
    if any(marker in url for marker in POST_MARKERS):
        return "post"
    return None


# ---------------------------------------------------------------------------
# SOURCE A — DuckDuckGo, single combined query (STEP 3c)
# ---------------------------------------------------------------------------
def search_ddg(keyword: str, raw_log: list):
    if DDGS is None:
        log.warning("ddgs library not installed — skipping DDG source")
        return []

    query = f'(site:linkedin.com/posts OR site:linkedin.com/feed/update) "{keyword}"'

    def _run():
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=25))

    results = with_retry(_run, label=f"DDG[{keyword}]") or []
    out = []
    for r in results:
        url = r.get("href") or r.get("url") or ""
        raw_log.append({"source": "ddg", "keyword": keyword, "url": url,
                         "title": r.get("title", "")})
        record_stat("ddg", "raw")
        if url:
            out.append({"url": url, "source": "ddg", "keyword": keyword})
    return out


# ---------------------------------------------------------------------------
# SOURCE B — Google Alerts RSS (STEP 3a)
# ⚠️ Requires manual one-time alert setup per keyword — see config.py.
# Google Alerts RSS entry links are typically Google redirect URLs
# (https://www.google.com/url?...&url=<real target>&...); unwrap them.
# ---------------------------------------------------------------------------
def _unwrap_google_alert_link(link: str) -> str:
    try:
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        if "url" in qs:
            return unquote(qs["url"][0])
    except Exception:  # noqa: BLE001
        pass
    return link


def search_google_alerts(keyword: str, raw_log: list):
    feed_url = ALERT_RSS_FEEDS.get(keyword)
    if not feed_url:
        return []  # no alert configured for this keyword — not an error
    if feedparser is None:
        log.warning("feedparser not installed — skipping Google Alerts source")
        return []

    def _run():
        return feedparser.parse(feed_url)

    parsed = with_retry(_run, label=f"GoogleAlerts[{keyword}]")
    if not parsed or getattr(parsed, "bozo", 0) and not getattr(parsed, "entries", None):
        return []

    out = []
    for entry in getattr(parsed, "entries", []):
        real_url = _unwrap_google_alert_link(entry.get("link", ""))
        raw_log.append({"source": "google_alerts", "keyword": keyword, "url": real_url,
                         "title": entry.get("title", "")})
        record_stat("google_alerts", "raw")
        if real_url:
            out.append({"url": real_url, "source": "google_alerts", "keyword": keyword})
    return out


# ---------------------------------------------------------------------------
# SOURCE C — self-hosted SearXNG (STEP 3b) — ⚠️ unverified, off by default
# ---------------------------------------------------------------------------
def search_searxng(keyword: str, raw_log: list):
    if not SEARXNG_INSTANCE_URL:
        return []

    query = f'(site:linkedin.com/posts OR site:linkedin.com/feed/update) "{keyword}"'
    params = {"q": query, "format": "json"}

    def _run():
        resp = requests.get(f"{SEARXNG_INSTANCE_URL.rstrip('/')}/search",
                             params=params, headers=REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()

    data = with_retry(_run, label=f"SearXNG[{keyword}]")
    if not data:
        return []

    out = []
    for r in data.get("results", []):
        url = r.get("url", "")
        raw_log.append({"source": "searxng", "keyword": keyword, "url": url,
                         "title": r.get("title", "")})
        record_stat("searxng", "raw")
        if url:
            out.append({"url": url, "source": "searxng", "keyword": keyword})
    return out


# ---------------------------------------------------------------------------
# SOURCE D — Mojeek Search API (STEP 3d) — ⚠️ unverified, off by default
# ---------------------------------------------------------------------------
def search_mojeek(keyword: str, raw_log: list):
    if not MOJEEK_API_KEY:
        return []

    query = f'(site:linkedin.com/posts OR site:linkedin.com/feed/update) "{keyword}"'
    params = {"q": query, "api_key": MOJEEK_API_KEY, "fmt": "json"}

    def _run():
        resp = requests.get("https://www.mojeek.com/search", params=params,
                             headers=REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()

    data = with_retry(_run, label=f"Mojeek[{keyword}]")
    if not data:
        return []

    out = []
    for r in data.get("response", {}).get("results", []):
        url = r.get("url", "")
        raw_log.append({"source": "mojeek", "keyword": keyword, "url": url,
                         "title": r.get("title", "")})
        record_stat("mojeek", "raw")
        if url:
            out.append({"url": url, "source": "mojeek", "keyword": keyword})
    return out


# ---------------------------------------------------------------------------
# Validation (carried over from the working weekly job)
# ---------------------------------------------------------------------------
def fetch_post_data(url: str):
    """Fetch a candidate URL and return {html, title} if it looks like a
    real, publicly viewable page — or None if it's broken/behind an authwall."""
    def _run():
        return requests.get(url, headers=REQUEST_HEADERS, timeout=15, allow_redirects=True)

    resp = with_retry(_run, retries=2, label=f"fetch[{url}]")
    if resp is None:
        return None

    if resp.status_code != 200:
        return None

    final_url = resp.url.lower()
    if any(hint in final_url for hint in BLOCKED_REDIRECT_HINTS):
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    title = (soup.title.string or "").strip().lower() if soup.title and soup.title.string else ""
    if any(hint in title for hint in BLOCKED_TITLE_HINTS):
        return None

    body_text = soup.get_text(" ", strip=True).lower()
    if any(hint in body_text for hint in BLOCKED_BODY_HINTS):
        return None

    return {"html": resp.text, "title": soup.title.string.strip() if soup.title and soup.title.string else "",
            "soup": soup}


def extract_published_date(soup: BeautifulSoup):
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if isinstance(item, dict) and item.get("datePublished"):
                return item["datePublished"]
    return "Unknown"


def extract_body_text(soup: BeautifulSoup, limit=500):
    # Best-effort: LinkedIn's markup varies; fall back to og:description / title.
    meta = soup.find("meta", {"property": "og:description"})
    if meta and meta.get("content"):
        text = meta["content"].strip()
    elif soup.title and soup.title.string:
        text = soup.title.string.strip()
    else:
        text = soup.get_text(" ", strip=True)
    return text[:limit]


# ---------------------------------------------------------------------------
# Language detection (STEP 4.7)
# ---------------------------------------------------------------------------
def detect_language(text: str) -> str:
    if not text or _langdetect is None:
        return "unknown"
    try:
        code = _langdetect(text)
    except LangDetectException:
        return "unknown"
    if code == "ar":
        return "Arabic"
    if code == "en":
        return "English"
    return code


# ---------------------------------------------------------------------------
# Gemini reply generation (unchanged provider, now language-aware)
# ---------------------------------------------------------------------------
FALLBACK_REPLIES = {
    "Arabic": "شكراً على هذا المحتوى القيّم، استفدت كثيراً من الأفكار المطروحة هنا.",
    "English": "Thanks for sharing this — really valuable insights here.",
    "unknown": "Thanks for sharing this — really valuable insights here.",
}


def generate_reply(content: str, language: str) -> str:
    if not GEMINI_API_KEY:
        return FALLBACK_REPLIES.get(language, FALLBACK_REPLIES["unknown"])

    lang_instruction = {
        "Arabic": "Reply in Arabic.",
        "English": "Reply in English.",
    }.get(language, "Reply in the same language as the post content below.")

    prompt = (
        "You are writing a short, genuine, professional LinkedIn comment "
        "replying to the post below. Reference something specific from the "
        "content — do not write a generic compliment. Keep it to 1-3 "
        "sentences, no hashtags, no emojis. "
        f"{lang_instruction}\n\nPost content:\n{content}"
    )

    def _run():
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        return response.text.strip()

    reply = with_retry(_run, retries=2, label="gemini")
    return reply or FALLBACK_REPLIES.get(language, FALLBACK_REPLIES["unknown"])


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------
RESULTS_HEADERS = ["Type (Post/Article)", "Keyword Matched", "Content", "Link",
                   "Date Published", "Language", "Suggested Reply"]
SEEN_HEADERS = ["URL", "First Seen (UTC)"]
RUNLOG_HEADERS = ["Run (UTC)", "Source", "Posts Found", "Articles Found", "Raw Results"]
RAWLOG_HEADERS = ["Run (UTC)", "Source", "Keyword", "URL", "Title"]


def get_sheet_client():
    creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)


def get_or_create_tab(spreadsheet, title, headers):
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=max(10, len(headers)))
        ws.append_row(headers)
    return ws


def load_seen_urls(spreadsheet) -> set:
    ws = get_or_create_tab(spreadsheet, "SeenURLs", SEEN_HEADERS)
    values = ws.get_all_values()[1:]  # skip header
    return {row[0] for row in values if row}


def append_seen_urls(spreadsheet, urls: list):
    if not urls:
        return
    ws = get_or_create_tab(spreadsheet, "SeenURLs", SEEN_HEADERS)
    now = datetime.now(timezone.utc).isoformat()
    ws.append_rows([[u, now] for u in urls])


def write_results(spreadsheet, rows: list):
    today_title = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ws = get_or_create_tab(spreadsheet, today_title, RESULTS_HEADERS)
    if rows:
        ws.append_rows(rows)


def write_run_log(spreadsheet, stats: dict):
    ws = get_or_create_tab(spreadsheet, "RunLog", RUNLOG_HEADERS)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for source, counts in stats["by_source"].items():
        rows.append([now, source, counts.get("post", 0), counts.get("article", 0),
                     counts.get("raw", 0)])
    if not rows:
        rows = [[now, "(no sources returned data)", 0, 0, 0]]
    ws.append_rows(rows)


def write_raw_search_log(spreadsheet, raw_log: list):
    ws = get_or_create_tab(spreadsheet, "RawSearchLog", RAWLOG_HEADERS)
    now = datetime.now(timezone.utc).isoformat()
    rows = [[now, e["source"], e["keyword"], e["url"], e.get("title", "")] for e in raw_log]
    if rows:
        ws.append_rows(rows)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
def main():
    spreadsheet = get_sheet_client()
    seen_urls = load_seen_urls(spreadsheet)
    raw_log = []
    result_rows = []
    newly_seen = []

    log.info("Starting run over %d keywords", len(KEYWORDS))

    for keyword in KEYWORDS:
        log.info("== Keyword: %s ==", keyword)
        candidates = []
        candidates += search_ddg(keyword, raw_log)
        candidates += search_google_alerts(keyword, raw_log)
        candidates += search_searxng(keyword, raw_log)
        candidates += search_mojeek(keyword, raw_log)

        # de-dup within this keyword's candidate set, then against history
        seen_this_keyword = set()
        for cand in candidates:
            url = cand["url"].split("?")[0].rstrip("/")
            if not url or url in seen_this_keyword or url in seen_urls:
                continue
            seen_this_keyword.add(url)

            kind = classify_url(url)
            if kind is None:
                continue

            page = fetch_post_data(url)
            polite_sleep()
            if page is None:
                continue

            content = extract_body_text(page["soup"])
            date_published = extract_published_date(page["soup"])
            language = detect_language(content)
            reply = generate_reply(content, language)

            result_rows.append([
                "Post" if kind == "post" else "Article",
                keyword,
                content,
                url,
                date_published,
                language,
                reply,
            ])
            newly_seen.append(url)
            record_stat(cand["source"], kind)

        polite_sleep()

    log.info("Writing %d new rows to today's tab", len(result_rows))
    write_results(spreadsheet, result_rows)
    append_seen_urls(spreadsheet, newly_seen)
    write_run_log(spreadsheet, RUN_STATS)
    write_raw_search_log(spreadsheet, raw_log)

    log.info("Done. Totals: %s", RUN_STATS["totals"])
    log.info("By source: %s", RUN_STATS["by_source"])


if __name__ == "__main__":
    main()
