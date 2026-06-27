# ═══════════════════════════════════════════════════════════════════════════════
# Minerva / titan_K — runtime configuration
# Secrets: set in .env (OPENAI_API_KEY, TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN, etc.)
# ═══════════════════════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import re
import sys
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv()


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# ── API & Telegram ────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
FAST_MODEL = os.getenv("FAST_MODEL", "gpt-4o-mini")

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
# scheduler.py legacy name
TELEGRAM_TOKEN = TELEGRAM_BOT_TOKEN

TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
# Many Windows networks reset TLS to api.telegram.org over IPv6 or flaky routes; IPv4 is more stable.
# Set TELEGRAM_FORCE_IPV4=0 in .env to disable. On non-Windows default is off.
TELEGRAM_FORCE_IPV4 = _env_bool("TELEGRAM_FORCE_IPV4", default=(sys.platform == "win32"))
TELEGRAM_HTTP_TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT", "90"))
TITAN_BOT_TOKEN = (os.getenv("TITAN_BOT_TOKEN") or TELEGRAM_BOT_TOKEN or "").strip()
TITAN_SYSTEM_URL = os.getenv(
    "TITAN_SYSTEM_URL",
    "http://5.189.176.185/index.html",
).strip()

# ── OLYMPUS pre-alarm (liquidity expectation + velocity) ─────────────────────
LIQUIDITY_ROLLING_DAYS = int(os.getenv("LIQUIDITY_ROLLING_DAYS", "90"))
PRE_ALARM_SURPRISE_ALERT = float(os.getenv("PRE_ALARM_SURPRISE_ALERT", "0.82"))
PRE_ALARM_VELOCITY_ALERT_B = float(os.getenv("PRE_ALARM_VELOCITY_ALERT_B", "85"))
PRE_ALARM_CORRIDOR_MARGIN_B = float(os.getenv("PRE_ALARM_CORRIDOR_MARGIN_B", "15"))
LIQUIDITY_BOOTSTRAP_LOW_B = float(os.getenv("LIQUIDITY_BOOTSTRAP_LOW_B", "2100"))
LIQUIDITY_BOOTSTRAP_HIGH_B = float(os.getenv("LIQUIDITY_BOOTSTRAP_HIGH_B", "2900"))
FRED_REFRESH_INTERVAL_MINUTES = int(os.getenv("FRED_REFRESH_INTERVAL_MINUTES", "60"))

# Tech radar RSS (comma-separated URLs; empty = built-in list in tech_radar.py)
_tech_feeds = os.getenv("TECH_RADAR_FEEDS", "").strip()
TECH_RADAR_FEEDS: List[str] = (
    [x.strip() for x in _tech_feeds.split(",") if x.strip()] if _tech_feeds else []
)
TECH_RADAR_INTERVAL_MINUTES = int(os.getenv("TECH_RADAR_INTERVAL_MINUTES", "30"))
TECH_RADAR_SCORE_ALERT = int(os.getenv("TECH_RADAR_SCORE_ALERT", "8"))
TECH_RADAR_MAX_ITEMS = int(os.getenv("TECH_RADAR_MAX_ITEMS", "24"))
PORTFOLIO_TECH_TICKERS: tuple = tuple(
    x.strip().upper()
    for x in os.getenv(
        "PORTFOLIO_TECH_TICKERS",
        "TSM,NVDA,ASML,AMD,PLTR,ARM,INTC,QCOM,AVGO,MU,COHR,VRT,RKLB,AMAT",
    ).split(",")
    if x.strip()
)

# NewsAPI (keyword scan in price_alert.check_news_alerts)
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# Legacy / optional
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
CACHE_PATH = os.getenv("CACHE_PATH", os.path.join("data", "titan_cache.json"))
LOG_PATH = os.getenv("LOG_PATH", "titan_k.log")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
DATA_FILE = os.getenv("DATA_FILE", os.path.join("data", "titan_state.json"))

# ── Blog (Naver) — default ranto28 is "메르의 블로그" (same ID, display name only)
NAVER_BLOG_ID = os.getenv("NAVER_BLOG_ID", "ranto28")
NAVER_BLOG_LABEL = os.getenv("NAVER_BLOG_LABEL", "메르 (ranto28)")
NAVER_RSS_URL = os.getenv(
    "NAVER_RSS_URL",
    f"https://rss.blog.naver.com/{NAVER_BLOG_ID}.xml",
)
# Optional extra Naver RSS feeds: comma-separated blog IDs (e.g. "otherid") or full https://rss.blog.naver.com/....xml
BLOG_EXTRA_RSS_URLS = os.getenv("BLOG_EXTRA_RSS_URLS", "").strip()
BLOG_FETCH_INTERVAL_MINUTES = int(os.getenv("BLOG_FETCH_INTERVAL_MINUTES", "5"))


def naver_blog_rss_list() -> List[str]:
    """All Naver blog RSS URLs (primary + BLOG_EXTRA_RSS_URLS)."""
    urls: List[str] = [NAVER_RSS_URL.strip()]
    extra = (BLOG_EXTRA_RSS_URLS or "").strip()
    if not extra:
        return urls
    for part in extra.split(","):
        p = part.strip()
        if not p:
            continue
        u = p if p.startswith("http") else f"https://rss.blog.naver.com/{p}.xml"
        if u not in urls:
            urls.append(u)
    return urls

# ── News pulse (Layer 3) ──────────────────────────────────────────────────────
NEWS_PULSE_INTERVAL_MINUTES = int(os.getenv("NEWS_PULSE_INTERVAL_MINUTES", "120"))
NEWS_PULSE_START_HOUR = float(os.getenv("NEWS_PULSE_START_HOUR", "7"))
NEWS_PULSE_END_HOUR = float(os.getenv("NEWS_PULSE_END_HOUR", "23.5"))

# ── Thesis / intraday drop tiers (%, price_alert.check_thesis_alerts & run_price_alerts) ─
ALERT_TIER_WATCH = -5
ALERT_TIER_THESIS = -10
ALERT_TIER_EMERGENCY = -15

# ── Intraday upside spike tiers (%, price_alert.check_thesis_alerts) ─
ALERT_TIER_WATCH_UP = 5
ALERT_TIER_MOMENTUM_UP = 10
ALERT_TIER_BREAKOUT_UP = 15

# ── Berlin schedules (weekday checks are inside battle_rhythm.generate_briefing) ─
# US-session cadence (GOD directive Jun 27 2026): six volatility-aware briefings
# anchored to the US market (summer: open 15:30, close 22:00 Berlin), plus the
# 07:00 morning strategic plan. Each is actionable + cause-classified (Why Engine).
#   14:30 = 1h before open · 16:30 = 1h after open · 19:30 = 4h after open
#   21:00 = 1h before close · 22:00 = at close · 23:00 = 1h after close (+ tomorrow)
DAILY_SCHEDULE = [
    ("07:00", "master_daily", "🌅 Morning Plan"),
    ("14:30", "us_preopen", "🔮 Pre-Open Forecast"),
    ("16:30", "us_open", "🟢 Open Status"),
    ("19:30", "us_midday", "📊 Midday Status"),
    ("21:00", "us_preclose", "🟠 Pre-Close Status"),
    ("22:00", "us_close", "🏁 Close Summary"),
    ("23:00", "us_postclose", "🌙 Post-Close + Tomorrow"),
]

WEEKLY_SCHEDULE = [
    ("07:00", "olympus_weekly", "Saturday Olympus weekly"),
]

DAILY_TIME = os.getenv("DAILY_TIME", "07:00")

# ── Institutional headline gate (news pulse) ─────────────────────────────────
IMPORTANT_KEYWORDS: List[str] = [
    "earnings",
    "eps",
    "revenue",
    "guidance",
    "sec",
    "investigation",
    "lawsuit",
    "fda",
    "clinical",
    "phase ",
    "acquisition",
    "merger",
    "takeover",
    "downgrade",
    "upgrade",
    "price target",
    "analyst",
    "bankruptcy",
    "chapter 11",
    "offering",
    "secondary",
    "insider",
    "13f",
    "activist",
    "settlement",
    "antitrust",
    "tariff",
    "sanction",
    "export ban",
    "rate cut",
    "rate hike",
    "fed ",
    "ecb ",
    "macro",
    "recession",
    "default",
    "dividend",
    "buyback",
    "ceo",
    "cfo",
    "resign",
    "layoff",
    "warning",
]

_RETAIL_NOISE_SUBSTR = (
    "you won't believe",
    "shocking",
    "meme",
    "reddit",
    "april fools",
    "gamestop mania",
    "three stocks to",
    "one stock",
    "retire rich",
    "millionaire",
    "this morning",
    "here's why",
)


def is_institutional_signal(headline: str) -> bool:
    if not headline or len(headline.strip()) < 12:
        return False
    h = headline.lower()
    if any(s in h for s in _RETAIL_NOISE_SUBSTR):
        return False
    if re.search(r"\b\d{1,2}\s*(must-own|stocks? to buy|reasons?)\b", h):
        return False
    return any(k in h for k in IMPORTANT_KEYWORDS)


# ── VIX regimes (market_data.get_vix_regime) ──────────────────────────────────
VIX_REGIMES: Dict[str, Dict] = {
    "CALM": {"range": (0, 15), "deploy_pct": 0, "label": "HOLD CASH"},
    "NORMAL": {"range": (15, 20), "deploy_pct": 25, "label": "SELECTIVE"},
    "FEAR": {"range": (20, 30), "deploy_pct": 50, "label": "DEPLOY 50%"},
    "CRISIS": {"range": (30, 999), "deploy_pct": 100, "label": "FULL DEPLOY"},
}

# ── titan_K composite weights (keys must match market_data.INDICATOR_TICKERS) ─
_IND_KEYS = [
    "VIX", "VVIX", "SKEW", "Put/Call", "VIX_Term", "MOVE",
    "US10Y", "US2Y", "Yield_Curve", "DXY", "Fed_Funds",
    "SPX", "NDX", "SOX", "RSP_SPY", "Adv_Dec", "52W_HL",
    "Gold", "Oil", "Copper", "Uranium", "Nat_Gas",
    "HYG_Spread", "IG_Spread", "TED_Spread", "LIBOR_OIS",
    "AAII_Bull", "CNN_FG", "Geopolitical", "BTC",
]
_W = 1.0 / len(_IND_KEYS)
WEIGHTS: Dict[str, float] = {k: _W for k in _IND_KEYS}

DEFAULT_EUR_USD = float(os.getenv("DEFAULT_EUR_USD", "1.08"))

# ── Calendars (extend on VPS) ─────────────────────────────────────────────────
EARNINGS_CALENDAR: List[Dict] = []
MACRO_CALENDAR: List[Dict] = []

# ── FUTURE STATE (analyzer prompt context) ────────────────────────────────────
FUTURE_STATE_CATEGORIES: List[str] = [
    "Intelligence",
    "Energy",
    "Space",
    "Bio-Engineering",
    "Robotics",
    "Infrastructure",
]

# ── Portfolio & watchlist (edit to match brokers; thesis feeds Olympus updater) ─
PORTFOLIO: Dict[str, List[Dict]] = {
    "TR": [
        {"ticker": "COHR", "name": "Coherent", "score": 7, "action": "HOLD", "thesis": "Photonics / industrial lasers"},
        {"ticker": "PLTR", "name": "Palantir", "score": 10, "action": "HOLD + ADD DIPS", "thesis": "AI gov / commercial platform"},
        {"ticker": "UEC", "name": "Uranium Energy", "score": 9, "action": "HOLD", "thesis": "US uranium restart / SWUs"},
        {"ticker": "RKLB", "name": "Rocket Lab", "score": 6, "action": "HOLD", "thesis": "Space launch cadence"},
        {"ticker": "URNM", "name": "Sprott Uranium", "score": 7, "action": "HOLD", "thesis": "Uranium ETF proxy"},
    ],
    "Kiwoom KR": [
        {"ticker": "000660.KS", "name": "SK Hynix", "score": 10, "action": "LEGEND — NEVER SELL", "thesis": "HBM memory cycle"},
        {"ticker": "272210.KS", "name": "Hanwha Systems", "score": 10, "action": "LEGEND — NEVER SELL", "thesis": "Defense / space exposure"},
    ],
    "Kiwoom US": [
        {"ticker": "KTOS", "name": "Kratos Defense", "score": 9, "action": "HOLD pending May 6", "thesis": "Hypersonics / C5ISR"},
    ],
}

# Held positions monitored for intraday tiered thesis alerts (see price_alert.check_thesis_alerts)
THESIS_ALERT_TICKERS: List[str] = [
    # TR holdings
    "TSM", "PLTR", "UEC", "URNM", "COHR", "1810.HK", "NTR",
    "PL", "TMO", "CWEN", "UUUU", "FCX", "RKLB", "MC.PA",
    # Kiwoom holdings
    "000660.KS", "272210.KS", "ARKQ", "BOTZ", "VRT", "IAU", "KTOS", "AMAT",
    # Watchlist
    "NVDA", "CCJ", "OKLO", "ASTS", "CRSP", "NTLA", "BEAM", "ASML",
]

WATCHLIST: List[Dict] = [
    {"ticker": "CRSP", "name": "CRISPR Therapeutics", "score": 8, "entry": "$44 limit", "target_usd": None},
    {"ticker": "NTLA", "name": "Intellia", "score": 6, "entry": "$10 limit", "target_usd": None},
    {"ticker": "IAU", "name": "iShares Gold ETF", "score": 10, "entry": "Any dip", "target_usd": None},
    {"ticker": "IONQ", "name": "IonQ", "score": 7, "entry": "$25 limit", "target_usd": None},
]

# Company names for NewsAPI query when ticker is not in PORTFOLIO (see get_company_name_for_ticker)
_THESIS_ALERT_NAME_FALLBACK: Dict[str, str] = {
    "TSM": "Taiwan Semiconductor",
    "1810.HK": "Xiaomi",
    "VRT": "Vertiv",
    "ARKQ": "ARK Autonomous Technology Robotics ETF",
    "BOTZ": "Global Robotics and Automation ETF",
}


def get_company_name_for_ticker(ticker: str) -> str:
    """Resolve company name for NewsAPI q= ticker + name; prefers PORTFOLIO/WATCHLIST."""
    for _bk, positions in PORTFOLIO.items():
        for p in positions:
            if p["ticker"] == ticker:
                return str(p.get("name") or ticker)
    for w in WATCHLIST:
        if w["ticker"] == ticker:
            return str(w.get("name") or ticker)
    return _THESIS_ALERT_NAME_FALLBACK.get(ticker, ticker)


def _build_stocks_list() -> List[Dict]:
    rows: List[Dict] = []
    for _broker, positions in PORTFOLIO.items():
        for p in positions:
            rows.append({
                "ticker": p["ticker"],
                "name": p["name"],
                "score": p["score"],
                "thesis": p.get("thesis") or p.get("action") or "—",
                "signal": "HOLD",
                "status": "portfolio",
                "action": p.get("action", ""),
            })
    for w in WATCHLIST:
        rows.append({
            "ticker": w["ticker"],
            "name": w["name"],
            "score": w["score"],
            "thesis": (w.get("entry") or "Watchlist")[:120],
            "signal": "BUY",
            "status": "watchlist",
            "action": "",
        })
    return rows


STOCKS: List[Dict] = _build_stocks_list()


def get_all_tickers() -> List[str]:
    t = set()
    for _bk, positions in PORTFOLIO.items():
        for p in positions:
            t.add(p["ticker"])
    for w in WATCHLIST:
        t.add(w["ticker"])
    return sorted(t)


def get_tradeable_tickers() -> List[str]:
    skip = {"xAI", "FigureAI"}
    return [s["ticker"] for s in STOCKS if s["ticker"] not in skip]
