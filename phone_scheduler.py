"""
titan_K PHONE SCHEDULER v2
===========================
Lightweight version for Flip 3 / Termux — ALL 9 BATTLE RHYTHM BRIEFINGS
- NO pandas, NO numpy, NO yfinance
- Uses only: requests, feedparser, python-telegram-bot, schedule, openai
- Full battle rhythm: 07:00 blog, 08:30 macro, 12:30 KR close,
  15:00 premarket, 15:40 open+40, 17:30 mid1, 19:30 mid2, 22:00 late, 23:00 close
"""

import os
import time
import schedule
import requests
import feedparser
from datetime import datetime
from dotenv import load_dotenv
import pytz
import asyncio
from telegram import Bot

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BERLIN = pytz.timezone("Europe/Berlin")

# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO & WATCHLIST (mirrors config.py — update both together)
# ══════════════════════════════════════════════════════════════════════════════

PORTFOLIO_TICKERS = {
    "COHR":      {"name": "Coherent Corp.",      "score": 7,    "action": "HOLD",                    "broker": "TR"},
    "PLTR":      {"name": "Palantir",            "score": 10,   "action": "HOLD + ADD DIPS",          "broker": "TR"},
    "UEC":       {"name": "Uranium Energy",      "score": 9,    "action": "HOLD — ADD AFTER EARNINGS","broker": "TR"},
    "RKLB":      {"name": "Rocket Lab",          "score": 6,    "action": "HOLD",                    "broker": "TR"},
    "FSLR":      {"name": "First Solar",         "score": 1,    "action": "EXIT — BROKEN THESIS",    "broker": "TR"},
    "CWEN":      {"name": "Clearway Energy",     "score": None, "action": "HOLD",                    "broker": "TR"},
    "TMO":       {"name": "Thermo Fisher",       "score": 6,    "action": "HOLD",                    "broker": "TR"},
    "MC.PA":     {"name": "LVMH",                "score": None, "action": "HOLD (locked)",           "broker": "TR"},
    "FCX":       {"name": "Freeport-McMoRan",    "score": 4,    "action": "SELL TR",                 "broker": "TR"},
    "URNM":      {"name": "Sprott Uranium ETF",  "score": None, "action": "HOLD — ADD IN 2 WEEKS",   "broker": "TR"},
    "000660.KS": {"name": "SK Hynix",            "score": 10,   "action": "LEGEND — NEVER SELL",     "broker": "Kiwoom"},
    "272210.KS": {"name": "Hanwha Systems",      "score": 10,   "action": "LEGEND — NEVER SELL",     "broker": "Kiwoom"},
    "KTOS":      {"name": "Kratos Defense",      "score": 9,    "action": "HOLD pending May 6",       "broker": "Kiwoom"},
    "IONQ":      {"name": "IonQ Quantum",        "score": 7,    "action": "LIMIT $25 ACTIVE",        "broker": "Kiwoom"},
    "HUYA":      {"name": "HUYA",                "score": 2,    "action": "EXIT MAR 17",             "broker": "Kiwoom"},
    "GEVO":      {"name": "Gevo",                "score": 4,    "action": "HOLD TO MAR 26 ONLY",     "broker": "Kiwoom"},
}

WATCHLIST_TICKERS = {
    "AVAV": {"name": "AeroVironment",       "score": 8, "entry": "$205-240", "target": 355},
    "CRSP": {"name": "CRISPR Therapeutics", "score": 8, "entry": "$44 limit","target": 106},
    "NTLA": {"name": "Intellia",            "score": 6, "entry": "$10 limit","target": 27},
    "IAU":  {"name": "iShares Gold ETF",    "score": 10,"entry": "Any dip",  "target": None},
}

MACRO_TICKERS = {
    "^VIX":     "VIX",
    "^GSPC":    "SPX",
    "^NDX":     "NDX",
    "^SOX":     "SOX",
    "GC=F":     "Gold",
    "CL=F":     "Oil",
    "DX-Y.NYB": "DXY",
    "^TNX":     "US10Y",
    "BTC-USD":  "BTC",
    "HG=F":     "Copper",
    "URA":      "Uranium",
    "EURUSD=X": "EUR/USD",
}

ALERT_THRESHOLDS = {
    "PLTR":      {"below": 70,     "above": 160},
    "COHR":      {"below": 50,     "above": 120},
    "RKLB":      {"below": 15,     "above": 35},
    "UEC":       {"below": 11.5,   "above": 20},
    "FCX":       {"below": 35,     "above": 55},
    "000660.KS": {"below": 140000, "above": 200000},
    "272210.KS": {"below": 100000, "above": 150000},
    "KTOS":      {"below": 75,     "above": 115},
    "IONQ":      {"below": 20,     "above": 45},
}

BLOG_RSS = "https://rss.blog.naver.com/ranto28.xml"
TITAN_SYSTEM_URL = os.getenv(
    "TITAN_SYSTEM_URL",
    "https://sobluenight10-commits.github.io/titan_k_v2/TITAN_SYSTEM_v4.html"
)

last_seen_blog_id = None


# ══════════════════════════════════════════════════════════════════════════════
# CORE UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

async def _send_async(message: str):
    bot = Bot(token=TELEGRAM_TOKEN)
    max_len = 4096
    if len(message) <= max_len:
        chunks = [message]
    else:
        chunks = []
        lines = message.split("\n")
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > max_len:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line
        if current:
            chunks.append(current)
    for chunk in chunks:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=chunk,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await asyncio.sleep(0.3)


def notify(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Missing credentials — skip")
        return
    try:
        asyncio.run(_send_async(message))
    except Exception as e:
        print(f"[notify error] {e}")


def berlin_now() -> str:
    return datetime.now(BERLIN).strftime("%Y-%m-%d %H:%M")


def footer() -> str:
    return f'\n{"━"*28}\n🔱 <a href="{TITAN_SYSTEM_URL}">TITAN SYSTEM</a>'


# ══════════════════════════════════════════════════════════════════════════════
# MARKET DATA — raw HTTP, no yfinance
# ══════════════════════════════════════════════════════════════════════════════

def get_price(ticker: str) -> dict | None:
    """Fetch price + daily change via Yahoo Finance v8 API. No yfinance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        result = data["chart"]["result"][0]
        meta = result["meta"]
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None]
        current = round(float(meta.get("regularMarketPrice", closes[-1] if closes else 0)), 2)
        prev = round(float(closes[-2]), 2) if len(closes) >= 2 else current
        change_pct = round(((current - prev) / prev) * 100, 2) if prev != 0 else 0
        return {"price": current, "prev": prev, "change_pct": change_pct}
    except Exception as e:
        print(f"[price error] {ticker}: {e}")
        return None


def fetch_all_prices(tickers: list) -> dict:
    results = {}
    for ticker in tickers:
        d = get_price(ticker)
        if d:
            results[ticker] = d
        time.sleep(0.2)
    return results


def fetch_macro_snapshot() -> dict:
    snapshot = {}
    for yf_ticker, label in MACRO_TICKERS.items():
        d = get_price(yf_ticker)
        if d:
            snapshot[label] = d
        time.sleep(0.15)
    return snapshot


def format_macro(snapshot: dict) -> str:
    lines = []
    for label, d in snapshot.items():
        if not d:
            continue
        chg = d["change_pct"]
        arrow = "▲" if chg >= 0 else "▼"
        bold = abs(chg) >= 2
        line = f"  {'<b>' if bold else ''}{arrow} {label} {d['price']} ({chg:+.1f}%){'</b>' if bold else ''}"
        lines.append(line)
    return "\n".join(lines)


def format_portfolio(prices: dict) -> str:
    lines = []
    for ticker, info in PORTFOLIO_TICKERS.items():
        p = prices.get(ticker, {})
        price = p.get("price", "?")
        chg = p.get("change_pct", 0)
        score = info.get("score", "?")
        action = info.get("action", "HOLD")
        arrow = "▲" if isinstance(chg, float) and chg >= 0 else "▼"
        # Format KRW differently
        price_fmt = f"₩{price:,.0f}" if ".KS" in ticker and isinstance(price, float) else f"${price}"
        lines.append(
            f"{ticker} ({info['name']}) | {arrow}{price_fmt} ({chg:+.1f}%) | "
            f"Score:{score}/10 | {action}"
        )
    return "\n".join(lines)


def format_watchlist(prices: dict) -> str:
    lines = []
    for ticker, info in WATCHLIST_TICKERS.items():
        p = prices.get(ticker, {})
        price = p.get("price", "?")
        lines.append(
            f"{ticker} ({info['name']}) | ${price} | Entry:{info['entry']} | Score:{info['score']}/10"
        )
    return "\n".join(lines)


def get_vix_regime(snapshot: dict) -> tuple:
    try:
        vix = float(snapshot.get("VIX", {}).get("price", 25))
        if vix >= 30:
            return "CRISIS", "🔴", 100
        elif vix >= 20:
            return "FEAR", "🟡", 50
        elif vix >= 15:
            return "NORMAL", "🔵", 25
        else:
            return "CALM", "🟢", 0
    except:
        return "UNKNOWN", "⚪", 0


# ══════════════════════════════════════════════════════════════════════════════
# GPT-4o — raw HTTP, no openai library
# ══════════════════════════════════════════════════════════════════════════════

def gpt_call(system: str, user: str, max_tokens: int = 600) -> str:
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.35,
                "max_tokens": max_tokens,
            },
            timeout=45,
        )
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[gpt error] {e}")
        return "⚠️ AI analysis unavailable."


# ══════════════════════════════════════════════════════════════════════════════
# SHARED CONTEXT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_context() -> dict:
    print(f"[context] Fetching live data at {berlin_now()}...")
    all_tickers = list(PORTFOLIO_TICKERS.keys()) + list(WATCHLIST_TICKERS.keys())
    prices = fetch_all_prices(all_tickers)
    snapshot = fetch_macro_snapshot()
    regime, regime_emoji, deploy_pct = get_vix_regime(snapshot)
    vix_val = snapshot.get("VIX", {}).get("price", "?")
    return {
        "prices": prices,
        "snapshot": snapshot,
        "regime": regime,
        "regime_emoji": regime_emoji,
        "deploy_pct": deploy_pct,
        "vix": vix_val,
        "portfolio_text": format_portfolio(prices),
        "watchlist_text": format_watchlist(prices),
        "macro_text": format_macro(snapshot),
    }


def build_header(title: str, ctx: dict) -> str:
    return (
        f"🔱 <b>{title}</b>\n"
        f"📅 {berlin_now()} Berlin\n"
        f"{ctx['regime_emoji']} {ctx['regime']} · VIX {ctx['vix']} · Deploy {ctx['deploy_pct']}%\n"
        f"{'━'*28}\n\n"
    )


# ══════════════════════════════════════════════════════════════════════════════
# BLOG MONITOR
# ══════════════════════════════════════════════════════════════════════════════

def check_blog():
    global last_seen_blog_id
    try:
        feed = feedparser.parse(BLOG_RSS)
        if not feed.entries:
            print("[blog] No entries in feed")
            return
        latest = feed.entries[0]
        entry_id = latest.get("id") or latest.get("link")
        if entry_id != last_seen_blog_id:
            last_seen_blog_id = entry_id
            title = latest.get("title", "No title")
            link = latest.get("link", "")
            msg = (
                f"📰 <b>ranto28 NEW POST</b>\n"
                f"🕐 {berlin_now()} Berlin\n\n"
                f"<b>{title}</b>\n{link}"
            )
            notify(msg)
            print(f"[blog] New post: {title}")
        else:
            print(f"[blog] No new post")
    except Exception as e:
        print(f"[blog error] {e}")


# ══════════════════════════════════════════════════════════════════════════════
# STOCK ALERTS
# ══════════════════════════════════════════════════════════════════════════════

def check_stock_alerts():
    alerts = []
    for ticker, thresholds in ALERT_THRESHOLDS.items():
        d = get_price(ticker)
        if not d:
            continue
        price = d["price"]
        info = PORTFOLIO_TICKERS.get(ticker, {})
        name = info.get("name", ticker)
        is_kr = ".KS" in ticker
        currency = "₩" if is_kr else "$"
        price_fmt = f"{price:,.0f}" if is_kr else f"{price:.2f}"
        lo, hi = thresholds["below"], thresholds["above"]
        if price <= lo:
            alerts.append(f"🔴 <b>{name} ({ticker})</b> {currency}{price_fmt} — BELOW {currency}{lo}")
        elif price >= hi:
            alerts.append(f"🟢 <b>{name} ({ticker})</b> {currency}{price_fmt} — ABOVE {currency}{hi}")
        time.sleep(0.15)

    if alerts:
        msg = f"⚡ <b>TITAN STOCK ALERT</b> | {berlin_now()}\n\n" + "\n".join(alerts)
        notify(msg)
        print(f"[alerts] {len(alerts)} alert(s) sent")
    else:
        print(f"[alerts] No threshold breaches")


# ══════════════════════════════════════════════════════════════════════════════
# BRIEFING GENERATORS — all 9 battle rhythm slots
# ══════════════════════════════════════════════════════════════════════════════

def briefing_morning_macro():
    """08:30 — Late night global issues → portfolio insights → today's plan."""
    print("[briefing] 08:30 morning_macro")
    ctx = build_context()
    analysis = gpt_call(
        system="""You are Minerva, briefing Titan at 8:30am Berlin.
FORMAT: Bullet points only. Max 15 words per bullet. Read on a phone.

Structure:
🌍 OVERNIGHT
• [2-3 bullets: what happened globally while Titan slept]

💼 PORTFOLIO IMPACT
• [only affected positions — skip stable ones]
• format: TICKER → impact → action

📋 TODAY'S PLAN
• [3-5 specific actions with prices/times]
• Include earnings, limit orders to set, exits to execute""",
        user=f"""LIVE MACRO:
{ctx['macro_text']}

PORTFOLIO:
{ctx['portfolio_text']}

WATCHLIST:
{ctx['watchlist_text']}""",
        max_tokens=600,
    )
    msg = build_header("🌅 MORNING MACRO", ctx)
    msg += analysis
    msg += "\n\n<b>📊 KEY MOVES</b>\n" + ctx["macro_text"]
    msg += footer()
    notify(msg)


def briefing_kr_close():
    """12:30 — Korean market close summary."""
    print("[briefing] 12:30 kr_close")
    ctx = build_context()
    kr_lines = []
    for ticker in ["000660.KS", "272210.KS"]:
        p = ctx["prices"].get(ticker, {})
        info = PORTFOLIO_TICKERS[ticker]
        price = p.get("price", "?")
        chg = p.get("change_pct", 0)
        price_fmt = f"₩{price:,.0f}" if isinstance(price, float) else f"₩{price}"
        kr_lines.append(
            f"{ticker} ({info['name']}) | {price_fmt} ({chg:+.1f}%) | {info['action']}"
        )
    analysis = gpt_call(
        system="""You are Minerva. Korean market just closed (12:30 Berlin = 19:30 Seoul).
FORMAT: Bullet points. Max 15 words per bullet.

Structure:
🇰🇷 KOREAN CLOSE
• [KOSPI direction, key themes today]

💼 KR PORTFOLIO
• [SK Hynix and Hanwha — price, change, any notable moves]

🇺🇸 US PREVIEW
• [what Korean close signals for US open in 3h]
• [any prep actions before 15:30]""",
        user=f"""KOREAN POSITIONS:
{chr(10).join(kr_lines)}

GLOBAL MACRO:
{ctx['macro_text']}

FULL PORTFOLIO:
{ctx['portfolio_text']}""",
        max_tokens=500,
    )
    msg = build_header("🇰🇷 KOREAN CLOSE", ctx)
    msg += analysis
    msg += footer()
    notify(msg)


def briefing_us_premarket():
    """15:00 — Final check before US open at 15:30 Berlin."""
    print("[briefing] 15:00 us_premarket")
    ctx = build_context()
    analysis = gpt_call(
        system="""You are Minerva. US market opens in 30 minutes (15:30 Berlin).
FORMAT: Bullet points. Max 15 words per bullet. Battle-ready.

Structure:
🎯 PRE-MARKET STATUS
• [futures direction, pre-market movers in Titan's stocks]

⚡ ORDERS CHECK
• [list every active limit/stop — confirm they're armed]
• [any new orders to place before open?]

⚠️ WATCH AT OPEN
• [which stocks to watch in first 30min and why]
• [do NOT buy at open — wait 30min for price discovery]""",
        user=f"""PORTFOLIO:
{ctx['portfolio_text']}

WATCHLIST:
{ctx['watchlist_text']}

MACRO:
{ctx['macro_text']}""",
        max_tokens=550,
    )
    msg = build_header("🇺🇸 US PRE-MARKET", ctx)
    msg += analysis
    msg += footer()
    notify(msg)


def briefing_us_session(title: str, session_context: str):
    """Generic US session check — used for 15:40, 17:30, 19:30, 22:00."""
    print(f"[briefing] {title}")
    ctx = build_context()
    analysis = gpt_call(
        system=f"""You are Minerva. {session_context}
FORMAT: Bullet points. Max 15 words per bullet.

Structure:
📊 STATUS
• [top 3-4 movers in Titan's portfolio right now]
• [any stock hitting stop or limit level?]

⚡ ACTION
• [what to do RIGHT NOW — specific, or say "no action needed"]
• [flag any position that changed status since last check]""",
        user=f"""PORTFOLIO:
{ctx['portfolio_text']}

WATCHLIST:
{ctx['watchlist_text']}

MACRO:
{ctx['macro_text']}""",
        max_tokens=450,
    )
    msg = build_header(title, ctx)
    msg += analysis
    msg += "\n\n<b>📊 MOVES</b>\n" + ctx["macro_text"]
    msg += footer()
    notify(msg)


def briefing_us_close():
    """23:00 — US market close summary + daily review."""
    print("[briefing] 23:00 us_close")
    ctx = build_context()
    analysis = gpt_call(
        system="""You are Minerva. US market just closed (23:00 Berlin).
FORMAT: Bullet points. Max 15 words per bullet.

Structure:
🏁 MARKET CLOSE
• [SPX, NDX, SOX final — direction + % change]
• [VIX close and what it means for tomorrow]

💼 PORTFOLIO REVIEW
• [biggest winners and losers today]
• [any stops triggered? any limits filled?]

📋 SCORECARD UPDATE
• [any stock whose score should change based on today?]
• [positions needing attention tomorrow]

🌅 TOMORROW
• [1-2 bullets: what to prepare]
• [earnings or macro events tomorrow?]""",
        user=f"""PORTFOLIO (end of day):
{ctx['portfolio_text']}

WATCHLIST:
{ctx['watchlist_text']}

MACRO:
{ctx['macro_text']}""",
        max_tokens=700,
    )
    msg = build_header("🏁 US MARKET CLOSE", ctx)
    msg += analysis
    msg += "\n\n<b>📊 FINAL</b>\n" + ctx["macro_text"]
    msg += footer()
    notify(msg)


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULE — all Berlin time
# ══════════════════════════════════════════════════════════════════════════════

# Blog monitor — every 15 min
schedule.every(15).minutes.do(check_blog)

# Stock alerts — every 30 min
schedule.every(30).minutes.do(check_stock_alerts)

# Battle rhythm
schedule.every().day.at("08:30").do(briefing_morning_macro)
schedule.every().day.at("12:30").do(briefing_kr_close)
schedule.every().day.at("15:00").do(briefing_us_premarket)
schedule.every().day.at("15:40").do(lambda: briefing_us_session(
    "⚡ 40min AFTER OPEN",
    "US market opened 40 minutes ago. First volatility wave settling."
))
schedule.every().day.at("17:30").do(lambda: briefing_us_session(
    "📊 MID-SESSION #1",
    "US market mid-session (17:30 Berlin = 11:30 EST). Lunch hour, volume dips."
))
schedule.every().day.at("19:30").do(lambda: briefing_us_session(
    "📊 MID-SESSION #2",
    "US market afternoon (19:30 Berlin = 13:30 EST). Institutional flows resume."
))
schedule.every().day.at("22:00").do(lambda: briefing_us_session(
    "📊 LATE SESSION",
    "US market late session (22:00 Berlin = 16:00 EST). Power hour — final positioning."
))
schedule.every().day.at("23:00").do(briefing_us_close)


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════

print("🔱 titan_K Phone Scheduler v2 — ALL 9 BATTLE RHYTHM BRIEFINGS")
print(f"   Time: {berlin_now()} Berlin")
print("   Schedule:")
print("   08:30 macro | 12:30 KR close | 15:00 premarket")
print("   15:40 open+40 | 17:30 mid1 | 19:30 mid2 | 22:00 late | 23:00 close")
print("   Blog: every 15min | Alerts: every 30min")

if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
    notify(
        "🔱 <b>titan_K Phone Scheduler v2 ONLINE</b>\n"
        "All 9 battle rhythm briefings armed.\n"
        "Blog every 15min · Stock alerts every 30min\n\n"
        "<i>Minerva standing by.</i>"
    )
else:
    print("⚠️ Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")

# Run immediately on start
check_blog()
check_stock_alerts()

while True:
    schedule.run_pending()
    time.sleep(30)
