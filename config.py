"""
Configuration for LinkedIn UX/UI Keyword Monitoring Automation.
"""

import os

# ---------------------------------------------------------------------------
# Keywords to search for (Arabic + English UX/UI terms)
# ---------------------------------------------------------------------------
KEYWORDS = [
    "Accessibility (a11y)",
    "Arabic Interface Design",
    "Arabic Localization UX",
    "Arabic UX Design",
    "Customer Experience (CX)",
    "Design community Arab world",
    "Design Thinking",
    "Digital Transformation",
    "Human-Centered Design",
    "Information Architecture",
    "Interaction Design",
    "Persona Development",
    "Product Design",
    "Responsive Design",
    "RTL (Right-to-Left) Design",
    "Service Design",
    "UI Design",
    "UI/UX Training & Workshops",
    "Usability Testing",
    "User Experience (UX)",
    "User Interface (UI)",
    "User Journey Mapping",
    "User-Centered Design (UCD)",
    "UX Audits & Consulting",
    "UX Design",
    "UX Middle East",
    "UX MENA",
    "UX Research",
    "UX Strategy",
    "UX/UI",
    "Wireframing & Prototyping",
    "Design Career",
    "Design Community",
    "Design Portfolio",
    "Design Systems",
    "Figma / Sketch / Adobe XD",
    "Prototyping",
    "Usability",
    "User Research",
    "UX/UI Jobs",
    "UX Writing",
    "Wireframing",
    "أبحاث تجربة المستخدم",
    "اختبار قابلية الاستخدام",
    "الاستراتيجية الرقمية",
    "التصميم المتمحور حول الإنسان",
    "التصميم المتمحور حول المستخدم",
    "التصميم المتجاوب",
    "التصميم من اليمين لليسار",
    "التفكير التصميمي",
    "التحول الرقمي",
    "التعريب في تجربة المستخدم",
    "تصميم الخدمات",
    "تصميم المنتجات",
    "تصميم التفاعل",
    "تصميم الواجهات العربية",
    "تصميم تجربة المستخدم",
    "تصميم واجهة المستخدم",
    "تدريب وورش عمل تجربة المستخدم",
    "تدقيق واستشارات تجربة المستخدم",
    "تجربة العميل",
    "تجربة المستخدم",
    "تجربة المستخدم في الشرق الأوسط",
    "تجربة المستخدم في الوطن العربي",
    "شخصيات المستخدم",
    "فحص تجربة المستخدم",
    "معايير هيئة الحكومة الرقمية",
    "مؤشر نضج التجربة الرقمية",
    "مؤشر قياس التجربة الرقمية",
    "مجتمع المصممين العرب",
    "المخططات الهيكلية والنماذج الأولية",
    "هيئة الحكومة الرقمية",
    "هندسة المعلومات",
    "رحلة المستخدم",
    "استراتيجية تجربة المستخدم",
    "واجهة المستخدم",
    "أنظمة التصميم",
    "تعلم التصميم",
    "تصميم عربي",
    "تصميم UI",
    "تصميم UX",
    "بحوث المستخدم",
    "سهولة الاستخدام",
    "مصممين عرب",
    "مجتمع التصميم",
    "وظائف تصميم",
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
BACKOFF_BASE_SECONDS = 15
CONSECUTIVE_429_LIMIT = 8

# ---------------------------------------------------------------------------
# Overall time budget for a single run, in minutes.
# GitHub Actions job timeout is 60 min; we stop early to always finish clean.
# ---------------------------------------------------------------------------
TIME_BUDGET_MINUTES = 48

# ---------------------------------------------------------------------------
# Cap on how many candidates per keyword get the expensive real-page-fetch
# treatment. This is what actually bounds worst-case run time as the
# keyword list grows — the search itself is cheap, it's fetching each
# LinkedIn page for its real date that's slow. A keyword rarely has more
# than a handful of genuinely-recent matches anyway, so this costs very
# few real results while keeping run time predictable regardless of how
# many keywords are configured.
# ---------------------------------------------------------------------------
MAX_FETCHES_PER_KEYWORD = 10

# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------
SHEET_ID = os.environ.get("SHEET_ID", "")
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
