"""
🔱 titan_K — Flip 3 Server (ZERO heavy deps)
Only uses: requests, json, time, os — all built-in or trivially installable.
No python-telegram-bot, no yfinance, no pydantic, no openai, no Rust builds.

pip install requests python-dotenv
python flip3_server.py
"""
import os
import time
import json
import requests
from datetime import datetime, timezone, timedelta

# ── Config ─────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BLOG_ID = "ranto28"
BERLIN = timezone(timedelta(hours=1))  # CET; adjust +2 for CEST (summer)
OLYMPUS_URL = "https://sobluenight10-commits.github.io/titan_k_v2/TITAN_SYSTEM_v4.html"

# Stock watchlist (Yahoo Finance chart API — no library needed)
WATCHLIST = {
    "PLTR":  {"name": "Palantir",         "lo": 120, "hi": 160},
    "COHR":  {"name": "Coherent",         "lo": 220, "hi": 300},
    "RKLB":  {"name": "Rocket Lab",       "lo": 55,  "hi": 85},
    "UEC":   {"name": "Uranium Energy",   "lo": 12,  "hi": 20},
    "FCX":   {"name": "Freeport-McMoRan", "lo": 35,  "hi": 55},
    "KTOS":  {"name": "Kratos Defense",   "lo": 75,  "hi": 115},
}
KR_WATCHLIST = {
    "000660.KS": {"name": "SK Hynix",      "lo": 140000, "hi": 200000},
    "272210.KS": {"name": "Hanwha Systems", "lo": 100000, "hi": 150000},
}

last_blog_id = None
last_briefing_date = None


# ── Telegram (raw HTTP — no library) ──────────────────────────────────────────
def send(text):
    if not TOKEN or not CHAT_ID:
        print("[NO TELEGRAM] " + text[:80])
        return
    url = "https://api.telegram.org/bot{}/sendMessage".format(TOKEN)
    try:
        r = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        if not r.ok:
            print("[TG ERROR] " + r.text[:200])
    except Exception as e:
        print("[TG ERROR] " + str(e)[:200])


_last_update_id = 0

def check_updates():
    """Poll Telegram for commands — handles all titan_K commands."""
    global _last_update_id
    url = "https://api.telegram.org/bot{}/getUpdates".format(TOKEN)
    try:
        params = {"timeout": 5, "limit": 10}
        if _last_update_id:
            params["offset"] = _last_update_id
        r = requests.get(url, params=params, timeout=15)
        if not r.ok:
            return
        data = r.json()
        for upd in data.get("result", []):
            _last_update_id = upd["update_id"] + 1
            msg = upd.get("message", {})
            text = (msg.get("text") or "").strip()
            chat = str(msg.get("chat", {}).get("id", ""))
            cmd = text.lower().split()[0] if text else ""

            if chat != str(CHAT_ID):
                if cmd == "/start":
                    requests.post(
                        "https://api.telegram.org/bot{}/sendMessage".format(TOKEN),
                        json={"chat_id": chat, "text": "Your chat ID: {}. Set TELEGRAM_CHAT_ID={} in .env".format(chat, chat)},
                        timeout=10,
                    )
                continue

            if cmd == "/start" or cmd == "/help":
                send(
                    "🔱 <b>titan_K — Minerva Online (Flip 3)</b>\n\n"
                    "<b>Commands:</b>\n"
                    "• /olympus — Open Olympus Dashboard\n"
                    "• /blog — Check blog for new posts\n"
                    "• /price — All stock prices now\n"
                    "• /price PLTR UEC — Specific prices\n"
                    "• /score — Portfolio scorecard\n"
                    "• /regime — Market regime (VIX)\n"
                    "• /watchlist — Watchlist with alerts\n"
                    "• /portfolio — Full portfolio status\n"
                    "• /status — System status\n\n"
                    "📡 Blog checked every 30 min\n"
                    "📊 Stock alerts every 1 hr\n"
                    "🌅 Morning briefing at 07:00 Berlin\n\n"
                    "🏛 <a href=\"{}\">Open OLYMPUS Dashboard</a>".format(OLYMPUS_URL)
                )
            elif cmd == "/olympus":
                send(
                    "🏛 <b>OLYMPUS DASHBOARD</b>\n\n"
                    "👉 <a href=\"{}\">Open OLYMPUS Dashboard</a>\n\n"
                    "Dashboard updates at 06:45 Berlin (from laptop).\n"
                    "To refresh now: run <code>python refresh_olympus.py</code> on laptop.\n\n"
                    "📊 Quick status:".format(OLYMPUS_URL)
                )
                check_stocks(force_send=True)
            elif cmd == "/blog":
                check_blog(force=True)
            elif cmd == "/price":
                args = text.upper().split()[1:]
                if args:
                    _price_specific(args)
                else:
                    check_stocks(force_send=True)
            elif cmd == "/score" or cmd == "/portfolio":
                _send_portfolio()
            elif cmd == "/regime":
                _send_regime()
            elif cmd == "/watchlist":
                _send_watchlist()
            elif cmd == "/status":
                now = datetime.now(BERLIN).strftime("%Y-%m-%d %H:%M")
                send(
                    "🔱 <b>SYSTEM STATUS</b>\n\n"
                    "⏰ Server time: {} Berlin\n"
                    "📡 Flip 3 server: ONLINE\n"
                    "📰 Blog monitor: every 30 min\n"
                    "📊 Stock alerts: every 1 hr\n"
                    "🌅 Morning briefing: 07:00\n\n"
                    "🏛 <a href=\"{}\">OLYMPUS Dashboard</a>".format(now, OLYMPUS_URL)
                )
            elif text.startswith("/"):
                send("Unknown command. Send /start for all commands.")
            else:
                send(
                    "🔱 Send /start for commands.\n"
                    "🏛 <a href=\"{}\">Open OLYMPUS</a>".format(OLYMPUS_URL)
                )
    except Exception as e:
        print("[updates] " + str(e)[:100])


# ── Stock price (raw Yahoo API — no yfinance) ─────────────────────────────────
def get_price(ticker):
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval=1d&range=1d".format(ticker)
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return round(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"], 2)
    except:
        return None


# ── Blog check (RSS — no feedparser, just XML regex) ──────────────────────────
def check_blog(force=False):
    global last_blog_id
    try:
        rss_url = "https://rss.blog.naver.com/{}.xml".format(BLOG_ID)
        r = requests.get(rss_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok:
            print("[blog] RSS fetch failed: " + str(r.status_code))
            return
        xml = r.text
        # Find first <item><title>...</title><link>...</link>
        import re
        items = re.findall(r"<item>\s*<title>([^<]*)</title>\s*<link>([^<]*)</link>", xml)
        if not items:
            if force:
                send("📭 No blog posts found in RSS.")
            return
        title, link = items[0]
        entry_id = link.strip()
        if entry_id != last_blog_id:
            if last_blog_id is not None:
                now = datetime.now(BERLIN).strftime("%H:%M")
                send("📰 <b>NEW ranto28 POST</b>\n🕐 {}\n\n<b>{}</b>\n{}".format(now, title.strip(), link.strip()))
            last_blog_id = entry_id
            print("[blog] Latest: " + title.strip()[:60])
        elif force:
            send("📰 Latest: <b>{}</b>\n{}".format(title.strip(), link.strip()))
    except Exception as e:
        print("[blog error] " + str(e)[:100])


# ── Portfolio & Watchlist data (from config — hardcoded for Flip 3) ─────────
PORTFOLIO = {
    "TR": [
        {"ticker": "COHR",  "name": "Coherent",        "score": 7,  "action": "HOLD"},
        {"ticker": "PLTR",  "name": "Palantir",        "score": 10, "action": "HOLD + ADD DIPS"},
        {"ticker": "UEC",   "name": "Uranium Energy",  "score": 9,  "action": "HOLD — ADD AFTER EARNINGS"},
        {"ticker": "RKLB",  "name": "Rocket Lab",      "score": 6,  "action": "HOLD"},
        {"ticker": "CWEN",  "name": "Clearway Energy", "score": 6,  "action": "HOLD"},
        {"ticker": "FCX",   "name": "Freeport-McMoRan","score": 4,  "action": "SELL TR — STOP $54.50"},
        {"ticker": "URNM",  "name": "Sprott Uranium",  "score": 7,  "action": "HOLD — ADD IN 2 WEEKS"},
    ],
    "Kiwoom KR": [
        {"ticker": "000660.KS", "name": "SK Hynix",       "score": 10, "action": "LEGEND — NEVER SELL"},
        {"ticker": "272210.KS", "name": "Hanwha Systems",  "score": 10, "action": "LEGEND — NEVER SELL"},
    ],
    "Kiwoom US": [
        {"ticker": "KTOS",  "name": "Kratos Defense",  "score": 9,  "action": "HOLD pending May 6"},
        {"ticker": "IONQ",  "name": "IonQ Quantum",    "score": 7,  "action": "LIMIT $25"},
    ],
}

WATCH_CANDIDATES = [
    {"ticker": "AVAV", "name": "AeroVironment",    "score": 8, "entry": "$205-240"},
    {"ticker": "CRSP", "name": "CRISPR Therapeutics","score": 8, "entry": "$44 limit"},
    {"ticker": "NTLA", "name": "Intellia",          "score": 6, "entry": "$10 limit"},
    {"ticker": "IAU",  "name": "iShares Gold ETF",  "score": 10,"entry": "Any dip — NEVER SELL"},
]


def _price_specific(tickers):
    lines = []
    for t in tickers[:10]:
        price = get_price(t)
        if price:
            is_kr = ".KS" in t.upper()
            cur = "₩" if is_kr else "$"
            fmt = "{:,.0f}".format(price) if is_kr else "{:.2f}".format(price)
            lines.append("• <b>{}</b> {}{}".format(t, cur, fmt))
        else:
            lines.append("• <b>{}</b> N/A".format(t))
    send("📊 <b>PRICES</b>\n\n" + "\n".join(lines) if lines else "No tickers found.")


def _send_portfolio():
    lines = ["🔱 <b>PORTFOLIO SCORECARD</b>\n"]
    for broker, positions in PORTFOLIO.items():
        lines.append("<b>— {} —</b>".format(broker))
        for pos in positions:
            price = get_price(pos["ticker"])
            is_kr = ".KS" in pos["ticker"]
            cur = "₩" if is_kr else "$"
            fmt = ("{:,.0f}".format(price) if is_kr else "{:.2f}".format(price)) if price else "N/A"
            score_bar = "🟢" if pos["score"] >= 8 else "🟡" if pos["score"] >= 5 else "🔴"
            lines.append(
                "{} <b>{}</b> ({}) {}{}\n   Score: {}/10 | {}".format(
                    score_bar, pos["name"], pos["ticker"], cur, fmt, pos["score"], pos["action"]
                )
            )
        lines.append("")
    lines.append("🏛 <a href=\"{}\">Full OLYMPUS Dashboard</a>".format(OLYMPUS_URL))
    send("\n".join(lines))


def _send_regime():
    vix = get_price("^VIX")
    if vix is None:
        send("⚠️ VIX data unavailable.")
        return
    if vix < 15:
        regime, deploy, emoji = "CALM", "0% — HOLD CASH", "🟢"
    elif vix < 20:
        regime, deploy, emoji = "NORMAL", "25% — SELECTIVE", "🟡"
    elif vix < 30:
        regime, deploy, emoji = "FEAR", "50% — DEPLOY 50%", "🟠"
    else:
        regime, deploy, emoji = "CRISIS", "100% — FULL DEPLOY", "🔴"
    send(
        "📊 <b>VIX REGIME</b>\n\n"
        "{} VIX: <b>{:.1f}</b>\n"
        "Regime: <b>{}</b>\n"
        "Deploy: {}\n\n"
        "🏛 <a href=\"{}\">OLYMPUS Dashboard</a>".format(emoji, vix, regime, deploy, OLYMPUS_URL)
    )


def _send_watchlist():
    lines = ["👀 <b>WATCHLIST (pending buys)</b>\n"]
    for w in WATCH_CANDIDATES:
        price = get_price(w["ticker"])
        fmt = "${:.2f}".format(price) if price else "N/A"
        score_bar = "🟢" if w["score"] >= 8 else "🟡" if w["score"] >= 5 else "🔴"
        lines.append(
            "{} <b>{}</b> ({}) now {}\n   Score: {}/10 | Entry: {}".format(
                score_bar, w["name"], w["ticker"], fmt, w["score"], w["entry"]
            )
        )
    lines.append("\n🏛 <a href=\"{}\">OLYMPUS Dashboard</a>".format(OLYMPUS_URL))
    send("\n".join(lines))


# ── Stock alerts ───────────────────────────────────────────────────────────────
def check_stocks(force_send=False):
    alerts = []
    prices_msg = []
    for ticker, info in {**WATCHLIST, **KR_WATCHLIST}.items():
        price = get_price(ticker)
        if price is None:
            continue
        name = info["name"]
        is_kr = ".KS" in ticker
        cur = "₩" if is_kr else "$"
        fmt = "{:,.0f}".format(price) if is_kr else "{:.2f}".format(price)
        if price <= info["lo"]:
            alerts.append("🔴 <b>{} ({})</b> {}{} — BELOW {}{}".format(name, ticker, cur, fmt, cur, "{:,.0f}".format(info["lo"]) if is_kr else str(info["lo"])))
        elif price >= info["hi"]:
            alerts.append("🟢 <b>{} ({})</b> {}{} — ABOVE {}{}".format(name, ticker, cur, fmt, cur, "{:,.0f}".format(info["hi"]) if is_kr else str(info["hi"])))
        prices_msg.append("• <b>{}</b> {}{} ".format(name, cur, fmt))
    if alerts:
        now = datetime.now(BERLIN).strftime("%H:%M")
        send("⚡ <b>STOCK ALERT</b> | {}\n\n{}".format(now, "\n".join(alerts)))
    if force_send and prices_msg:
        send("📊 <b>PRICES</b>\n\n{}".format("\n".join(prices_msg)))


# ── Morning briefing ───────────────────────────────────────────────────────────
def morning_briefing():
    now = datetime.now(BERLIN)
    lines = ["🔱 <b>TITAN MORNING</b> | {}\n".format(now.strftime("%Y-%m-%d %H:%M"))]
    for ticker, info in {**WATCHLIST, **KR_WATCHLIST}.items():
        price = get_price(ticker)
        name = info["name"]
        is_kr = ".KS" in ticker
        cur = "₩" if is_kr else "$"
        if price:
            fmt = "{:,.0f}".format(price) if is_kr else "{:.2f}".format(price)
            lines.append("• <b>{}</b> {}{}".format(name, cur, fmt))
        else:
            lines.append("• <b>{}</b> N/A".format(name))
    send("\n".join(lines))
    check_blog(force=True)


# ── Main loop ──────────────────────────────────────────────────────────────────
def run():
    global last_briefing_date
    print("🔱 titan_K Flip 3 Server")
    print("   Only needs: requests")
    print("   Time: {} Berlin".format(datetime.now(BERLIN).strftime("%Y-%m-%d %H:%M")))
    send("🔱 <b>Minerva (Flip 3) ONLINE</b>\nBlog every 30 min | Stocks every 1 hr | Briefing 07:00 Berlin")
    check_blog()

    blog_timer = 0
    stock_timer = 0
    update_timer = 0

    while True:
        now = datetime.now(BERLIN)

        # 07:00 briefing (once per day)
        if now.hour == 7 and now.minute < 2:
            today = now.strftime("%Y-%m-%d")
            if last_briefing_date != today:
                last_briefing_date = today
                morning_briefing()

        # Check Telegram commands (every 10s)
        if update_timer <= 0:
            check_updates()
            update_timer = 10

        # Blog (every 30 min = 1800s)
        if blog_timer <= 0:
            check_blog()
            blog_timer = 1800

        # Stocks (every 60 min = 3600s)
        if stock_timer <= 0:
            check_stocks()
            stock_timer = 3600

        time.sleep(10)
        blog_timer -= 10
        stock_timer -= 10
        update_timer -= 10


if __name__ == "__main__":
    run()
