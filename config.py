# ═══════════════════════════════════════════════════════════════════════════════
# Minerva / titan_K — runtime configuration
# Secrets: set in .env (OPENAI_API_KEY, TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN, etc.)
# ═══════════════════════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import re
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv()

# ── API & Telegram ────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
FAST_MODEL = os.getenv("FAST_MODEL", "gpt-4o-mini")

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
# scheduler.py legacy name
TELEGRAM_TOKEN = TELEGRAM_BOT_TOKEN

TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
TITAN_BOT_TOKEN = (os.getenv("TITAN_BOT_TOKEN") or TELEGRAM_BOT_TOKEN or "").strip()
TITAN_SYSTEM_URL = os.getenv(
    "TITAN_SYSTEM_URL",
    "http://5.189.176.185/index.html",
).strip()

# Legacy / optional
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
CACHE_PATH = os.getenv("CACHE_PATH", os.path.join("data", "titan_cache.json"))
LOG_PATH = os.getenv("LOG_PATH", "titan_k.log")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
DATA_FILE = os.getenv("DATA_FILE", os.path.join("data", "titan_state.json"))

# ── Blog (ranto28) ────────────────────────────────────────────────────────────
NAVER_BLOG_ID = os.getenv("NAVER_BLOG_ID", "ranto28")
NAVER_RSS_URL = os.getenv(
    "NAVER_RSS_URL",
    f"https://rss.blog.naver.com/{NAVER_BLOG_ID}.xml",
)
BLOG_FETCH_INTERVAL_MINUTES = int(os.getenv("BLOG_FETCH_INTERVAL_MINUTES", "30"))

# ── News pulse (Layer 3) ──────────────────────────────────────────────────────
NEWS_PULSE_INTERVAL_MINUTES = int(os.getenv("NEWS_PULSE_INTERVAL_MINUTES", "120"))
NEWS_PULSE_START_HOUR = float(os.getenv("NEWS_PULSE_START_HOUR", "7"))
NEWS_PULSE_END_HOUR = float(os.getenv("NEWS_PULSE_END_HOUR", "23.5"))

# ── Thesis / intraday drop tiers (%, price_alert.check_thesis_alerts & run_price_alerts) ─
ALERT_TIER_WATCH = -8
ALERT_TIER_THESIS = -12
ALERT_TIER_EMERGENCY = -15

# ── Intraday upside spike tiers (%, price_alert.check_thesis_alerts) ─
ALERT_TIER_WATCH_UP = 5
ALERT_TIER_MOMENTUM_UP = 10
ALERT_TIER_BREAKOUT_UP = 15

# ── Berlin schedules (weekday checks are inside battle_rhythm.generate_briefing) ─
DAILY_SCHEDULE = [
    ("07:00", "master_daily", "🌅 Morning Brief"),
    ("16:30", "us_open", "🇺🇸 US Open"),
    ("19:00", "us_midday", "📊 Interim Review"),
    ("23:30", "us_close", "🏁 US Close"),
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
        {"ticker": "CWEN", "name": "Clearway Energy", "score": 6, "action": "HOLD", "thesis": "Yieldco renewables"},
        {"ticker": "FCX", "name": "Freeport-McMoRan", "score": 4, "action": "SELL TR — STOP $54.50", "thesis": "Copper levered trade"},
        {"ticker": "URNM", "name": "Sprott Uranium", "score": 7, "action": "HOLD", "thesis": "Uranium ETF proxy"},
    ],
    "Kiwoom KR": [
        {"ticker": "000660.KS", "name": "SK Hynix", "score": 10, "action": "LEGEND — NEVER SELL", "thesis": "HBM memory cycle"},
        {"ticker": "272210.KS", "name": "Hanwha Systems", "score": 10, "action": "LEGEND — NEVER SELL", "thesis": "Defense / space exposure"},
    ],
    "Kiwoom US": [
        {"ticker": "KTOS", "name": "Kratos Defense", "score": 9, "action": "HOLD + ADD $80", "thesis": "Hypersonics / C5ISR"},
        {"ticker": "IONQ", "name": "IonQ", "score": 7, "action": "LIMIT $25", "thesis": "Quantum compute optionality"},
    ],
}

# Held positions monitored for intraday tiered thesis alerts (see price_alert.check_thesis_alerts)
THESIS_ALERT_TICKERS: List[str] = [
    "TSM",
    "PLTR",
    "UEC",
    "URNM",
    "KTOS",
    "RKLB",
    "COHR",
    "000660.KS",
    "272210.KS",
    "1810.HK",
    "IONQ",
    "VRT",
    "ARKQ",
    "BOTZ",
]

WATCHLIST: List[Dict] = [
    {"ticker": "AVAV", "name": "AeroVironment", "score": 8, "entry": "$205-240", "target_usd": None},
    {"ticker": "CRSP", "name": "CRISPR Therapeutics", "score": 8, "entry": "$44 limit", "target_usd": None},
    {"ticker": "NTLA", "name": "Intellia", "score": 6, "entry": "$10 limit", "target_usd": None},
    {"ticker": "IAU", "name": "iShares Gold ETF", "score": 10, "entry": "Any dip", "target_usd": None},
]


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
