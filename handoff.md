# LinkedIn UX/UI Keyword Monitor — Handoff

## Goal
Daily automation that searches multiple free sources for LinkedIn **posts**
(`/posts/`, `/feed/update/`) and, as a reliable fallback, `/pulse/` articles,
across ~18 UX/UI-related keywords (Arabic + English). Validates URLs,
extracts real publication dates via JSON-LD, detects each post's language,
generates unique Gemini AI replies in that same language, and writes
everything to a Google Sheets tab — with full transparency on what was
actually found vs. diluted with articles.

## ⚠️ Important caveat on this revision
This revision was built in a sandboxed dev environment whose network is
restricted to package registries (PyPI/npm) and GitHub — it has **no route
to duckduckgo.com, google.com, linkedin.com, mojeek.com, etc.** So none of
the STEP 3 sources below (DDG, Google Alerts RSS, SearXNG, Mojeek) could be
live-tested end-to-end during development. The code is written defensively
(each source fails soft and logs, never crashes the run) and every
unverified claim is marked ⚠️ below. **Run this for real (or test it from an
environment with normal internet access) before trusting the output**, and
watch the first few `RunLog` entries closely.

## Current State

- **Search — 4 parallel sources, all fail-soft:**
  - **A. DuckDuckGo** (`ddgs`) — reshaped per prior debugging: now a single
    combined query `(site:linkedin.com/posts OR site:linkedin.com/feed/update) "<keyword>"`
    instead of 4 separate patterns. Every raw result (before filtering) is
    logged to a hidden `RawSearchLog` sheet tab so a future "0 results" dead
    end is debuggable instead of silent. ⚠️ Not verified from this
    environment — prior sessions found DDG doesn't reliably index
    `/posts/`/`/feed/update/`, only `/pulse/`. This combined-query shape is
    a new attempt, not a confirmed fix.
  - **B. Google Alerts, delivered as RSS.** Rides Google's own indexing
    pipeline instead of raw scraping, so it may sidestep the SG_REL block
    direct HTML scraping hit. **Requires manual one-time setup per keyword**
    (Google has no API to create Alerts) — see `config.py` for the exact
    steps. Keywords without a configured feed are silently skipped (not an
    error). ⚠️ Coverage/delay characteristics unverified.
  - **C. Self-hosted SearXNG instance** — optional, off unless
    `SEARXNG_INSTANCE_URL` is set. ⚠️ Free-tier hosting availability
    (Render/Fly.io etc.) was not verified live; this needs a real
    investigation before it's worth relying on.
  - **D. Mojeek Search API** — optional, off unless `MOJEEK_API_KEY` is set.
    ⚠️ Current free-tier terms (no credit card) not verified live; endpoint
    shape in the code is best-effort and may need adjustment against
    Mojeek's actual current docs.
  - **Yandex** — evaluated per STEP 3(d) and **not implemented**: historically
    requires account/site verification with friction and uncertain
    availability outside Russia; judged not worth it within a 30-minute
    timebox. Revisit only if you can verify current terms yourself.
- **Classification**: `/pulse/` → Article, `/posts/` or `/feed/update/` →
  Post, everything else (including `/jobs/`, `/company/`, `/showcase/`)
  ignored — unchanged logic, still never relabels an article as a post.
- **Validation**: HTTP status, redirect target (authwall/checkpoint/login/
  signup), page title, and body text ("was not found" / "no longer
  available") — unchanged logic from the weekly version.
- **Date extraction**: JSON-LD `datePublished`. Shows "Unknown" if absent —
  never fabricated.
- **Language detection**: `langdetect` (offline, free) on the extracted
  content; reply is generated in that same detected language (Arabic post →
  Arabic reply, English → English). Falls back to a plain templated reply
  (also language-matched) if Gemini fails or `GEMINI_API_KEY` is absent.
- **Replies**: Gemini 1.5 Flash (`google-generativeai`, free tier),
  content-specific per post, matched to detected language.
- **Dedup**: hidden `SeenURLs` sheet tab (URL + first-seen timestamp) checked
  before processing each candidate — a URL that resurfaces on a later day is
  skipped. Chose a sheet tab over a committed JSON file to avoid needing
  git-write permissions in the Actions workflow.
- **Transparency (STEP 5)**: hidden `RunLog` tab records, per run, per
  source: posts found, articles found, raw result count. Hidden
  `RawSearchLog` tab records every raw candidate URL before filtering, per
  source/keyword, for debugging.
- **Sheet columns** (daily tab, e.g. `2026-07-03`): `Type (Post/Article)` |
  `Keyword Matched` | `Content` (~500 chars) | `Link` | `Date Published` |
  `Language` | `Suggested Reply`.
- **Schedule**: daily, `cron: '30 5 * * *'` = 05:30 UTC = 08:30 Riyadh
  (AST, UTC+3, no DST — verified this is a fixed offset year-round).
- **Rate limiting**: randomized 4–9s delay between requests, retry with
  exponential backoff (up to 3 attempts) on every network call — daily
  runs across 18 keywords hit free sources much harder than the old weekly
  job, so this matters more than before.

## Files

| File | Role |
|------|------|
| `main.py` | Orchestrator: 4-source search → classify → validate → date → language → Gemini reply → dedupe → sheet write |
| `config.py` | `KEYWORDS`, rate-limit knobs, `ALERT_RSS_FEEDS` (manual setup), optional `SEARXNG_INSTANCE_URL` / `MOJEEK_API_KEY` |
| `.github/workflows/daily_search.yml` | Daily cron, passes all secrets (required + optional) |
| `requirements.txt` | requests, gspread, google-auth, beautifulsoup4, ddgs, google-generativeai, feedparser, langdetect |
| `handoff.md` | This file |

## GitHub Secrets

**Required (unchanged):**
- `GEMINI_API_KEY`
- `GOOGLE_SHEETS_CREDENTIALS`
- `SHEET_ID` — `1zvi5eWVv6tjgTFQekE0lk5NmOqSV54WEEIlQ0MIoah4`

**New, optional (leave unset to skip that source, no error):**
- `ALERT_RSS_FEEDS_JSON` — `{"<keyword>": "<google alerts rss feed url>", ...}`
- `SEARXNG_INSTANCE_URL`
- `MOJEEK_API_KEY`

## Everything That Failed (carried over from prior handoff — still closed, not re-attempted)

### Search Engines (all require credit card for billing)
Google Custom Search API, Brave Search API, Bing Web Search API.

### Web Scraping (all blocked)
Google HTML (requests / curl_cffi), `googlesearch-python`, Google News RSS,
Bing HTML, SearXNG public instances (9 tried, all blocked/down), DuckDuckGo
HTML scraping.

### DDG Limitations (prior sessions)
`ddgs.text()` with `timelimit="d"`/`"w"`, `ddgs.news()`, 4-query-pattern
approach — all returned 0 or near-0 `/posts/`/`/feed/update/` results, only
`/pulse/` articles.

### AI / API
Gemini via Vertex AI (403, needs Vertex AI User role), Vertex AI REST with
OAuth token (403), Hugging Face Inference API (cold starts / echoed prompt).

### This revision — newly attempted, status unresolved (see caveat above)
| Attempt | Status |
|---------|--------|
| DDG single combined query (STEP 3c) | ⚠️ Implemented, not live-verified — needs a real run to know if it beats the 4-pattern approach |
| Google Alerts RSS (STEP 3a) | ⚠️ Implemented, requires manual per-keyword setup, coverage unverified |
| Self-hosted SearXNG (STEP 3b) | ⚠️ Implemented but off by default — free hosting option not actually investigated/verified within timebox |
| Mojeek Search API (STEP 3d) | ⚠️ Implemented but off by default — current free-tier terms and exact endpoint shape not verified |
| Yandex (STEP 3d) | Discarded without implementation — verification friction judged not worth the timebox |

## The Core Problem (still open)
**It remains unconfirmed whether any free, zero-card, zero-login source
reliably indexes LinkedIn `/posts/`/`/feed/update/` content.** This revision
adds three new attempts (Google Alerts RSS, SearXNG, Mojeek) alongside a
reshaped DDG query, but none were tested against the live internet during
development. `/pulse/` articles remain the only fully confirmed-working
source. Watch `RunLog` after the first few real runs to see actual post vs.
article counts per source.

## What DOES Work (confirmed)
- `/pulse/` articles: findable, accessible without login, have JSON-LD
  dates, Gemini generates good replies.
- Broken-link detection: robust (auth walls, "was not found", login pages).
- Gemini replies: unique, content-specific, now language-matched.
- Google Sheets integration: daily tabs + hidden SeenURLs/RunLog/
  RawSearchLog tabs, all auto-created.
- Dedup via SeenURLs tab.

## Next Steps (recommended)
1. **Run it for real and read `RunLog`** — this is the single most useful
   next step; it will finally show whether any STEP 3 source surfaces real
   posts, with zero guessing.
2. Manually set up 2–3 Google Alerts (STEP 3a) as a quick, no-code-change
   test of Source B before configuring all 18 keywords.
3. If SearXNG/Mojeek show promise from Source A/B results, spend real time
   verifying their current terms and wiring them properly; otherwise leave
   them off.
4. Longer-term paid option unchanged: prepaid card → Google Custom Search
   API (100 free queries/day, can target `dateRestrict=d1`) or Brave Search
   API (2,000/month free with $5 credit).

## Key Technical Facts
- Google Sheet ID: `1zvi5eWVv6tjgTFQekE0lk5NmOqSV54WEEIlQ0MIoah4`
- GCP Project: `linkedin-search-501016`
- Service account: `linkedin-bot@linkedin-search-501016.iam.gserviceaccount.com`
- Google CSE CX: `f2b232ae0fc294989` (created, API enabled, billing required — unused)
- GitHub: ubuntu-latest, Python 3.11
- `/pulse/` = accessible without login, has JSON-LD `datePublished`
- `/posts/`, `/feed/update/` = historically not indexed by DDG, require login — STEP 3 sources are new, unverified attempts to work around this
