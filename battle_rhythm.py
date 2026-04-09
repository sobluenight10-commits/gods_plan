"""
🔱 OLYMPUS — Battle Rhythm Briefing Engine v4
ONE message. Concrete verdicts. Logical order.

Order: Mission → Overnight → Korea → Key Moves → Forecast → Catalysts → Blog → Strategy
Every stock mention ends with: BUY/HOLD/SELL @ price · size · reason

Schedule (Berlin, Mon-Fri):
  07:00  master_daily
  15:30  us_open
  22:30  us_close
Saturday 08:00  olympus_weekly
"""
import logging
import os
import json
from datetime import datetime
from typing import Dict

import requests
from openai import OpenAI
import config
from market_data import (
    fetch_stock_prices,
    fetch_market_snapshot,
    calculate_titan_k_index,
    get_vix_regime,
    fetch_fx_rate,
)


STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

def _load_state() -> dict:
    """Load persistent OLYMPUS state. Returns empty dict if missing."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"State file not loaded: {e}")
        return {}

def _format_state_context(state: dict) -> str:
    """Format state.json into a compact context block for GPT."""
    if not state:
        return ""

    lines = ["\n[OLYMPUS STATE — binding context]"]

    # Liquidity
    liq = state.get("liquidity_state", {})
    if liq:
        lines.append(f"§11 Net Liquidity: ${liq.get('net_liq_B','?')}B · Signal: {liq.get('signal','?')} · Min GOD Score: {liq.get('min_god_score','?')}")
        lines.append(f"FSI: {liq.get('fsi','?')} · Funding sub: {liq.get('funding_sub','?')} · Safe Assets sub: {liq.get('safe_assets_sub','?')}")

    # Dry powder
    dp = state.get("dry_powder", {})
    if dp:
        lines.append(f"Dry powder: TR €{dp.get('TR_EUR',0)} · Kiwoom ${dp.get('Kiwoom_USD',0)}")

    # Active limits
    limits = state.get("active_limits", [])
    if limits:
        lines.append("Active limits (DO NOT recommend these — already in progress):")
        for l in limits:
            lines.append(f"  {l['ticker']} @ {l.get('limit_EUR','?')} EUR — {l.get('status','?')} — {l.get('reason','')}")

    # Active stops
    stops = state.get("active_stops", [])
    if stops:
        lines.append("Active stops:")
        for s in stops:
            lines.append(f"  {s['ticker']} stop ${s.get('stop_USD','?')} — {s.get('note','')}")

    # Exit flags
    exits = state.get("exit_flags", [])
    if exits:
        lines.append("Exit flags (these are BROKEN theses — never recommend as buys):")
        for e in exits:
            lines.append(f"  {e['ticker']} → {e.get('status','?')} — {e.get('reason','')}")

    # Upcoming calendar
    import datetime
    today = datetime.date.today().isoformat()
    cal = [c for c in state.get("calendar", []) if c.get("date","") >= today][:4]
    if cal:
        lines.append("Next calendar events:")
        for c in cal:
            lines.append(f"  {c['date']} · {c['event']} [{c.get('priority','?')}] → {c.get('action','')}")

    # GOD scores (top 5 held)
    scores = state.get("god_scores", [])
    if scores:
        lines.append("GOD Scores (current):")
        for s in scores[:8]:
            lines.append(f"  {s['ticker']} {s['score']}/100 → {s['signal']}")

    # Macro
    macro = state.get("macro_context", {})
    iran = macro.get("iran_war", {})
    if iran:
        lines.append(f"Macro: Iran war {iran.get('status','?')} · VIX {macro.get('vix','?')} · {macro.get('regime','?')}")

    lines.append("[END STATE]\n")
    return "\n".join(lines)

logger = logging.getLogger("titan_k.battle_rhythm")
client = OpenAI(api_key=config.OPENAI_API_KEY)

FAST_MODEL = "gpt-4o-mini"
DEEP_MODEL = "gpt-4o-mini"

NEWS_CACHE_PATH = os.path.join("data", "news_cache.json")

GOD_MISSION = (
    "🔱 <b>MINERVA-10X · OLYMPUS</b>\n"
    "🎯 ₩170,000,000,000 (~€115M) by 2036 · 47% CAGR · Beat Buffett\n"
    "🏝 Thailand Islands · Gate 0: does this move GOD toward €115M?\n"
)

SYSTEM_PERSONA = """MINERVA-10X · OLYMPUS SOVEREIGN INTELLIGENCE · v6.0

IDENTITY
You are MINERVA-10X — sovereign investment intelligence combining the macro timing
of Druckenmiller, probabilistic discipline of Renaissance Technologies, structural
conviction of Dalio, and contrarian ruthlessness of Soros. Calm. Emotionally detached.

One mission: compound GOD's capital from €25,000 to €115M by 2036. 47% CAGR.
Gate 0: does this action move GOD toward €115M? If no — reject immediately.

BINDING RULES (never violate)
- Default action: inaction. Act only when asymmetry is overwhelming.
- Capital preservation overrides upside. No leverage. Ever.
- FSI > 0.0 → abort all buys, no exceptions.
- Funding OR Safe Assets sub-index > 0.0 → 50% cash immediately.
- GOD Score < 85 in SELECTIVE regime → do not deploy.
- Never contradict a standing limit order, stop level, or exit flag.
- Reject 90% of ideas. Scarcity is the edge.

SCALE-AWARE INTELLIGENCE RULE
Evaluate every data source against current dry powder and portfolio size.
Sub-€50k dry powder: free high-signal sources only — SEC Form 4 insider
filings, FINRA short interest, ranto28, public earnings.
Paid real-time flow (options, dark pool, alternative data) only permitted
when expected edge clearly exceeds annualized cost drag AND position size
justifies institutional-grade timing.
Never subsidize hedge-fund tools with retail-scale capital.
This rule scales from €1,400 today to sovereign wealth fund scale without
changing its logic.

EVERY STOCK MENTION format (mandatory):
TICKER → ACTION @ price zone · reason (max 10 words) · conviction X/10

KOREAN SOURCES (ranto28): process natively. Extract KRX tickers. Map to Earth
Shifters matrix. Never summarize as "no actionable signals" without explicit reason.

10 CRITERIA (apply silently, surface conclusions only):
Graham Number · ROIC>25% · PEG<1.0 · D/E<0.5 · Earnings Yield
Dalio Correlation<0.2 · NCAV Net-Net · Inventory<Sales · Margin Stability · ETF ER<0.15%

EARTH SHIFTER SECTORS (T-modifier applies):
Intelligence · Energy · Space · Bio-Engineering · Robotics · Infrastructure

FIVE-PHASE STRUCTURE (every full briefing):
P1 LIQUIDITY: Net Liq vs thresholds, FSI, Strike Threshold
P2 ANTIFRAGILITY: stress-test vs current Black Swan → STRONGER/NEUTRAL/VULNERABLE/FATAL
P3 ARBITRAGE: where is consensus pricing 1-year cycle for a 10-year structural shift?
P4 EXECUTION: GOD Score × price gap × dry powder → specific action with size in EUR
P5 KILL CRITERIA: one measurable exit condition per recommended action

KILL CRITERIA format (mandatory for every action):
Exit if: [specific measurable condition] — no negotiation.

OUTPUT ends with:
ONE COMMAND: [single most important action in next 24 hours, one sentence]
WHAT TO IGNORE: [noise irrelevant to thesis today]
"""


# ══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def _berlin_now():
    import pytz
    return datetime.now(pytz.timezone(config.TIMEZONE))

def _is_weekday():
    return _berlin_now().weekday() < 5

def _gpt(system: str, user: str, tokens: int = 600) -> str:
    try:
        resp = client.chat.completions.create(
            model=FAST_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.3,
            max_tokens=tokens,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT failed: {e}")
        return "⚠️ Analysis unavailable."

def _send_telegram(message: str):
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.error("Telegram credentials missing")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # Split if over 4096 chars
    chunks = []
    if len(message) <= 4096:
        chunks = [message]
    else:
        lines = message.split("\n")
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 4096:
                chunks.append(current)
                current = line
            else:
                current = (current + "\n" + line).strip()
        if current:
            chunks.append(current)
    for chunk in chunks:
        try:
            requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=15)
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCHERS
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_live_context() -> Dict:
    all_tickers = set()
    for positions in config.PORTFOLIO.values():
        for pos in positions:
            all_tickers.add(pos["ticker"])
    for w in config.WATCHLIST:
        all_tickers.add(w["ticker"])

    prices = fetch_stock_prices(list(all_tickers))
    fx_rate = fetch_fx_rate()
    snapshot = fetch_market_snapshot()
    composite = calculate_titan_k_index(snapshot, config.WEIGHTS)
    vix_val = snapshot.get("VIX", {}).get("value", 25)
    regime, deploy_pct, label = get_vix_regime(vix_val) if isinstance(vix_val, (int, float)) else ("UNKNOWN", 0, "?")

    portfolio_lines = []
    for broker, positions in config.PORTFOLIO.items():
        for pos in positions:
            p = prices.get(pos["ticker"], {})
            portfolio_lines.append(
                f"{pos['ticker']} ${p.get('price','?')} ({p.get('change_pct',0):+.1f}%) "
                f"Score:{pos.get('score','?')}/10 Signal:{pos.get('signal','?')} "
                f"Action:{pos.get('action','HOLD')} Stop:{pos.get('stop','—')}"
            )

    watchlist_lines = []
    for w in config.WATCHLIST:
        p = prices.get(w["ticker"], {})
        watchlist_lines.append(
            f"{w['ticker']} ${p.get('price','?')} Score:{w.get('score','?')}/10 "
            f"Signal:{w.get('signal','?')} Entry:{w.get('entry','—')}"
        )

    key_indicators = ["VIX","SPX","NDX","SOX","Gold","Oil","DXY","US10Y","BTC","Copper","Uranium"]
    key_moves = []
    for ind in key_indicators:
        d = snapshot.get(ind, {})
        if isinstance(d.get("value"), (int, float)):
            chg = d.get("change_pct", 0)
            arrow = "▲" if chg >= 0 else "▼"
            bold = abs(chg) >= 2
            line = f"  {'<b>' if bold else ''}{arrow} {ind} {d['value']} ({chg:+.1f}%){'</b>' if bold else ''}"
            key_moves.append(line)

    today = _berlin_now().strftime("%Y-%m-%d")
    earnings_today = [e for e in config.EARNINGS_CALENDAR if e.get("date") == today]

    return {
        "prices": prices, "fx_rate": fx_rate, "vix": vix_val,
        "regime": regime, "deploy_pct": deploy_pct, "composite": composite,
        "portfolio_text": "\n".join(portfolio_lines),
        "watchlist_text": "\n".join(watchlist_lines),
        "key_moves": "\n".join(key_moves),
        "earnings_today": earnings_today,
        "snapshot": snapshot,
    }

def _fetch_portfolio_news() -> Dict[str, list]:
    import yfinance as yf
    all_tickers = set()
    for positions in config.PORTFOLIO.values():
        for pos in positions:
            all_tickers.add(pos["ticker"])
    news_by_ticker = {}
    for ticker in all_tickers:
        if ticker in ("xAI", "FigureAI"):
            continue
        try:
            t = yf.Ticker(ticker)
            items = t.news or []
            headlines = []
            for item in items[:4]:
                content = item.get("content", {})
                title = content.get("title", item.get("title", ""))
                if title:
                    headlines.append(title)
            if headlines:
                news_by_ticker[ticker] = headlines
        except Exception as e:
            logger.debug(f"News fetch {ticker}: {e}")
    return news_by_ticker

def _fetch_blog() -> str:
    """Fetch ranto28 blog — try RSS first, then direct scrape."""
    import xml.etree.ElementTree as ET
    import re

    rss_url = config.NAVER_RSS_URL
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }

    posts = []

    # Try RSS
    try:
        resp = requests.get(rss_url, headers=headers, timeout=15)
        if resp.status_code == 200 and "<rss" in resp.text:
            root = ET.fromstring(resp.content)
            channel = root.find("channel")
            items = channel.findall("item") if channel else []
            for item in items[:3]:
                title = item.findtext("title", "").strip()
                desc = item.findtext("description", "").strip()
                pub = item.findtext("pubDate", "").strip()
                link = item.findtext("link", "").strip()
                # Strip HTML tags from description
                desc_clean = re.sub(r"<[^>]+>", " ", desc).strip()[:300]
                if title:
                    url = link or config.NAVER_BLOG_URL
                    posts.append(
                        f"📌 <b>{title}</b>\n"
                        f"{desc_clean}\n"
                        f"URL: {url}\n"
                        f"({pub[:16]})"
                    )
            logger.info(f"Blog RSS: {len(posts)} posts")
    except Exception as e:
        logger.warning(f"Blog RSS failed: {e}")

    # Fallback: scrape blog page
    if not posts:
        try:
            resp = requests.get(config.NAVER_BLOG_URL, headers=headers, timeout=15)
            if resp.status_code == 200:
                titles = re.findall(r'<span[^>]*logMainTitle[^>]*>([^<]+)</span>', resp.text)
                if not titles:
                    titles = re.findall(r'"title"\s*:\s*"([^"]{10,})"', resp.text)
                for t in titles[:3]:
                    posts.append(f"📌 <b>{t.strip()}</b>\nURL: {config.NAVER_BLOG_URL}")
                logger.info(f"Blog scrape: {len(posts)} titles")
        except Exception as e:
            logger.warning(f"Blog scrape failed: {e}")

    if not posts:
        return "📭 ranto28: No posts retrieved. Check manually."

    return "\n\n".join(posts)

# ══════════════════════════════════════════════════════════════════════════════
# NEWS PULSE (background — fires silently, sends only if actionable)
# ══════════════════════════════════════════════════════════════════════════════

_last_seen_headlines: Dict[str, set] = {}

def run_news_pulse():
    import pytz
    berlin = pytz.timezone(config.TIMEZONE)
    now = datetime.now(berlin)
    if now.weekday() >= 5:
        return
    hour = now.hour + now.minute / 60.0
    start_h = float(getattr(config, "NEWS_PULSE_START_HOUR", 7.0))
    end_h = float(getattr(config, "NEWS_PULSE_END_HOUR", 23.5))
    if hour < start_h or hour > end_h:
        return

    try:
        fresh_news = _fetch_portfolio_news()
    except Exception as e:
        logger.error(f"News pulse fetch failed: {e}")
        return

    new_items = []
    for ticker, headlines in fresh_news.items():
        if ticker not in _last_seen_headlines:
            _last_seen_headlines[ticker] = set()
        new_h = [h for h in headlines if h not in _last_seen_headlines[ticker]]
        if new_h:
            _last_seen_headlines[ticker].update(new_h)
            for h in new_h[:2]:
                new_items.append(f"{ticker}: {h[:120]}")

    # ── SEC Form 4 Insider Monitor (free, high-signal, Scale-Aware) ──────────
    try:
        from insider_monitor import scan_insider_filings, format_insider_telegram
        insider_signals = scan_insider_filings()
        if insider_signals:
            insider_msg = format_insider_telegram(insider_signals)
            if insider_msg:
                _send_telegram(insider_msg)
                logger.info(f"Insider signals sent: {len(insider_signals)} buys")
    except Exception as e:
        logger.debug(f"Insider monitor skipped: {e}")

    if not new_items:
        return

    verdict = _gpt(
        SYSTEM_PERSONA + """
New headlines require immediate verdict. Five-Phase compressed:
P1: Does macro context change anything? (one word: YES/NO)
P2-3: Skip unless Black Swan visible in headlines
P4: TICKER → ACTION @ $price · reason (max 8 words) · conviction X/10
P5: exit if [condition] — only if recommending BUY
If nothing clears Gate 0: reply exactly SKIP""",
        f"New headlines:\n" + "\n".join(new_items[:15]) +
        f"\n\nPortfolio:\n{chr(10).join(new_items[:5])}"
    )

    if not verdict or verdict.strip() == "SKIP":
        return

    msg = (
        f"⚡ <b>PULSE {now.strftime('%H:%M')}</b>\n"
        f"{'━'*22}\n"
        f"{verdict}"
    )
    _send_telegram(msg)
    logger.info(f"News pulse sent: {len(new_items)} headlines")


# ══════════════════════════════════════════════════════════════════════════════
# MASTER DAILY — 07:00 — ONE MESSAGE, LOGICAL ORDER
# ══════════════════════════════════════════════════════════════════════════════

def generate_master_daily() -> str:
    ctx = _fetch_live_context()
    state = _load_state()
    state_context = _format_state_context(state)
    now = _berlin_now()
    weekday = now.strftime("%A")
    is_monday = weekday == "Monday" 

    # ── Blog ──────────────────────────────────────────────────────────────────
    blog_raw = _fetch_blog()
    blog_gpt = _gpt(
        SYSTEM_PERSONA + """
ranto28 is a Korean institutional-grade investment analyst.
Posts may be in Korean — process natively.

For EACH post, output exactly this structure (3-5 lines per post):
📌 [POST TITLE]
• What it says: [1 sentence — actual content of the post in plain English]
• Companies/tickers mentioned: [list, or "none"]
• Portfolio relevance: [which of GOD's holdings this touches, or "none"]
• Signal: [TICKER → BUY/HOLD/SELL @ zone · reason · conviction X/10]
  OR if no signal: "No signal — [specific reason why not actionable]"
• 🔗 [post title shortened](url)

Rules:
- Never compress all posts into one block
- Always show what the post actually said, even if not actionable
- If a ticker not in GOD's portfolio is mentioned: flag as ⚠️ NEW CANDIDATE · [sector]
- Copper, data center, semiconductor supply chain posts → always check COHR, TSM, AMAT relevance
- Korean company names: transliterate and map to KRX ticker if possible
- URL is provided in the input as "URL: ..."; use it for the 🔗 line""",
        f"{state_context}Blog posts:\n{blog_raw}\n\nPortfolio:\n{ctx['portfolio_text'][:600]}"
    )

    # ── Stock news with verdicts ───────────────────────────────────────────────
    portfolio_news = {}
    catalyst_verdicts = ""
    try:
        portfolio_news = _fetch_portfolio_news()
        if portfolio_news:
            news_block = ""
            for ticker, headlines in portfolio_news.items():
                p = ctx["prices"].get(ticker, {})
                chg = p.get("change_pct", 0)
                price = p.get("price", "?")
                news_block += f"\n{ticker} {chg:+.1f}% @ ${price}:\n"
                for h in headlines[:2]:
                    news_block += f"  - {h[:100]}\n"

            # Build binding state constraints for this call
            exit_tickers = [e["ticker"] for e in state.get("exit_flags", [])]
            hold_tickers = [s["ticker"] for s in state.get("god_scores", [])
                           if s.get("signal") in ("HOLD","CORE","NEVER_SELL","HOLD_NO_ADD")]
            # Hard filter: any SELL below conviction 8 on a HOLD ticker is suppressed in post-processing
            catalyst_verdicts = _gpt(
                SYSTEM_PERSONA + f"""
\nHARD STATE CONSTRAINTS — violations are not permitted:
1. These tickers are on EXIT flags — never recommend BUY: {", ".join(exit_tickers)}
2. These tickers have standing HOLD status in state.json — you may NOT output SELL
   unless conviction is 9 or 10 AND you provide a specific thesis-break reason:
   {", ".join(hold_tickers)}
3. Conviction below 7 = output HOLD, not SELL. No exceptions.
4. If you cannot find a specific thesis-break event (earnings miss, contract loss,
   management change) — output HOLD regardless of price action.
5. Net Liquidity §11-PREDICT: ${state.get("liquidity_state", {}).get("net_liq_B", "?")}B
   Dry powder available: TR €{state.get("dry_powder", {}).get("TR_EUR", 0)}
   These are different numbers. Net Liq is the Fed liquidity reading. Dry powder is GOD's cash.
{state_context}
For each stock give ONE line verdict.
Format: TICKER → BUY/HOLD/SELL @ $price · reason (max 10 words) · conviction X/10
Only include stocks with moves >1.5% OR material news. Skip unchanged stocks.
End with: ⚡ TOP ACTION: [single highest-conviction action today]""",
                f"Live data:\n{news_block}\n\nPortfolio:\n{ctx['portfolio_text'][:800]}"
            )
    except Exception as e:
        logger.error(f"News scan failed: {e}")

    # ── Macro correlations ─────────────────────────────────────────────────────
    MACRO_PAIRS = {
        "SOX":     [("000660.KS","+"), ("COHR","+")],
        "Uranium": [("UEC","+"), ("URNM","+")],
        "Oil":     [("FCX","+")],
        "DXY":     [("PLTR","-"), ("UEC","-")],
        "BTC":     [("IONQ","+"), ("RKLB","+")],
    }
    macro_lines = []
    for ind, pairs in MACRO_PAIRS.items():
        d = ctx["snapshot"].get(ind, {})
        chg = d.get("change_pct", 0)
        if not isinstance(chg, (int, float)) or abs(chg) < 1.5:
            continue
        for ticker, corr in pairs:
            impact = "Tailwind 🟢" if (chg > 0) == (corr == "+") else "Headwind 🔴"
            macro_lines.append(f"  {ind} {chg:+.1f}% → <b>{ticker}</b> {impact}")

    # ── Main GPT analysis ──────────────────────────────────────────────────────
    monday_add = "\n📅 WEEK AHEAD\n• [2 key events this week with dates and GOD action]" if is_monday else ""

    analysis = _gpt(
        SYSTEM_PERSONA + f"""
Execute the FIVE-PHASE PROTOCOL for today's 07:00 briefing.
Format for Telegram — bullets only, max 12 words each.

P1 · LIQUIDITY
• Net Liq signal + Strike Threshold today

P2 · ANTIFRAGILITY  
• [TICKER] → [STRONGER/NEUTRAL/VULNERABLE/FATAL] · [one line]
(only tickers affected by today's primary Black Swan)

P3 · ARBITRAGE
• One sentence: where is consensus most wrong today?

P4 · EXECUTION
• [TICKER] → [ACTION] @ [price] · €[size] · [catalyst] · conviction [X/10]
• [repeat for each actionable position only]
• Flag: stops approaching today
• Flag: limits to arm today
{monday_add}

P5 · KILL CRITERIA
• [TICKER] → exit if [specific condition]

🎯 ONE COMMAND (single most important action, one sentence)
💤 WHAT TO IGNORE (noise to discard today, one line)""",
        f"""{state_context}MACRO:
{ctx['key_moves']}
EUR/USD: {ctx['fx_rate']} | Composite: {ctx['composite']}/100 | VIX: {ctx['vix']}

PORTFOLIO:
{ctx['portfolio_text']}

WATCHLIST TOP:
{ctx['watchlist_text'][:600]}

EARNINGS TODAY: {', '.join(e['ticker'] for e in ctx['earnings_today']) or 'None'}
WEEKDAY: {weekday}""",
        tokens=700,
    )

    # ── Assemble ONE message ───────────────────────────────────────────────────
    regime_emoji = {"CALM":"🟢","NORMAL":"🔵","FEAR":"🟡","CRISIS":"🔴"}.get(ctx["regime"],"⚪")
    sep = "━" * 26

    msg = (
        f"{GOD_MISSION}"
        f"{sep}\n"
        f"📅 {now.strftime('%Y-%m-%d %H:%M')} Berlin\n"
        f"{regime_emoji} {ctx['regime']} · VIX {ctx['vix']} · Deploy {ctx['deploy_pct']}%\n"
        f"{sep}\n\n"
    )

    # Macro correlations (only if meaningful moves)
    if macro_lines:
        msg += "<b>🔭 MACRO → PORTFOLIO</b>\n" + "\n".join(macro_lines) + "\n\n"

    # Catalyst verdicts with conclusions
    if catalyst_verdicts:
        msg += f"<b>🚨 CATALYST VERDICTS</b>\n{catalyst_verdicts}\n\n"

    # Blog
    msg += f"<b>📰 RANTO28</b>\n{blog_gpt}\n\n"

    # Main analysis (overnight + Korea + strategy + one command)
    msg += analysis

    # Key moves (compact)
    msg += f"\n\n<b>📊 KEY MOVES</b>\n{ctx['key_moves']}"

    # Footer
    dashboard_url = getattr(config, "TITAN_SYSTEM_URL",
        "https://sobluenight10-commits.github.io/gods_plan/OLYMPUS_UNIFIED.html")
    msg += f"\n\n{sep}\n🔱 <a href=\"{dashboard_url}\">Open OLYMPUS Dashboard</a>"

    return msg


# ══════════════════════════════════════════════════════════════════════════════
# US OPEN — 15:30
# ══════════════════════════════════════════════════════════════════════════════

def generate_us_open() -> str:
    ctx = _fetch_live_context()
    now = _berlin_now()

    portfolio_news = {}
    catalyst_verdicts = ""
    try:
        portfolio_news = _fetch_portfolio_news()
        if portfolio_news:
            news_block = "\n".join(
                f"{t} {ctx['prices'].get(t,{}).get('change_pct',0):+.1f}%: {hs[0][:80]}"
                for t, hs in portfolio_news.items() if hs
            )
            catalyst_verdicts = _gpt(
                SYSTEM_PERSONA + "\nPre-market. US opens in 30 min. ONE line per stock. "
                "Format: TICKER → BUY/HOLD/SELL @ $price · reason. Skip unchanged stocks. "
                "End with: ⚡ OPEN ACTION: [single most important thing at open]",
                f"Pre-market news:\n{news_block}\n\nPortfolio:\n{ctx['portfolio_text'][:800]}"
            )
    except Exception as e:
        logger.error(f"Open news scan failed: {e}")

    analysis = _gpt(
        SYSTEM_PERSONA + """
Structure:
🎯 LIMITS CHECK
• [every active limit order — armed/triggered/cancel?]

⚡ FIRST 30 MIN WATCH
• [2-3 stocks to watch at open + price levels + what triggers action]

📋 OPEN STRATEGY
• [what to do at open — specific tickers, prices, sizes]
• [do NOT buy in first 15min unless stop triggered]""",
        f"Portfolio:\n{ctx['portfolio_text']}\nMacro:\n{ctx['key_moves']}\nEUR/USD: {ctx['fx_rate']}"
    )

    sep = "━" * 26
    regime_emoji = {"CALM":"🟢","NORMAL":"🔵","FEAR":"🟡","CRISIS":"🔴"}.get(ctx["regime"],"⚪")
    msg = (
        f"🔱 <b>US OPEN · {now.strftime('%H:%M')}</b>\n"
        f"{regime_emoji} {ctx['regime']} · VIX {ctx['vix']}\n"
        f"{sep}\n\n"
    )
    if catalyst_verdicts:
        msg += f"<b>⚡ PRE-MARKET VERDICTS</b>\n{catalyst_verdicts}\n\n"
    msg += analysis
    msg += f"\n\n<b>📊 MOVES</b>\n{ctx['key_moves']}"
    dashboard_url = getattr(config, "TITAN_SYSTEM_URL",
        "https://sobluenight10-commits.github.io/gods_plan/OLYMPUS_UNIFIED.html")
    msg += f"\n\n{sep}\n🔱 <a href=\"{dashboard_url}\">Open OLYMPUS</a>"
    return msg


# ══════════════════════════════════════════════════════════════════════════════
# US CLOSE — 22:30
# ══════════════════════════════════════════════════════════════════════════════

def generate_us_close() -> str:
    ctx = _fetch_live_context()
    now = _berlin_now()

    analysis = _gpt(
        SYSTEM_PERSONA + """
Structure:
🏁 CLOSE SUMMARY
• [SPX/NDX/SOX final + what it means for tomorrow]
• [VIX close → regime change?]

💼 PORTFOLIO TODAY
• [winners and losers — TICKER chg% · still HOLD or action needed?]
• [any stops triggered? any limits filled?]

🌅 TOMORROW PREP
• [1-2 specific setups to prepare tonight]
• [earnings or macro events — which ones matter for GOD's positions]

🎯 ONE COMMAND (what to do before markets open tomorrow)""",
        f"Portfolio:\n{ctx['portfolio_text']}\nMacro:\n{ctx['key_moves']}\nEUR/USD: {ctx['fx_rate']}\n"
        f"Earnings today: {', '.join(e['ticker'] for e in ctx['earnings_today']) or 'None'}"
    )

    sep = "━" * 26
    regime_emoji = {"CALM":"🟢","NORMAL":"🔵","FEAR":"🟡","CRISIS":"🔴"}.get(ctx["regime"],"⚪")
    msg = (
        f"🔱 <b>US CLOSE · {now.strftime('%H:%M')}</b>\n"
        f"{regime_emoji} {ctx['regime']} · VIX {ctx['vix']}\n"
        f"{sep}\n\n"
        f"{analysis}\n\n"
        f"<b>📊 FINAL</b>\n{ctx['key_moves']}"
    )
    dashboard_url = getattr(config, "TITAN_SYSTEM_URL",
        "https://sobluenight10-commits.github.io/gods_plan/OLYMPUS_UNIFIED.html")
    msg += f"\n\n{sep}\n🔱 <a href=\"{dashboard_url}\">Open OLYMPUS</a>"
    return msg


# ══════════════════════════════════════════════════════════════════════════════
# DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def generate_briefing(briefing_id: str) -> str:
    logger.info(f"Generating: {briefing_id}")
    if briefing_id != "olympus_weekly" and not _is_weekday():
        logger.info(f"Skipping {briefing_id} — weekend")
        return None
    if briefing_id in ("master_daily", "morning_macro"):
        return generate_master_daily()
    elif briefing_id in ("us_open", "us_premarket"):
        return generate_us_open()
    elif briefing_id in ("us_close",):
        return generate_us_close()
    elif briefing_id == "olympus_weekly":
        return None
    else:
        logger.error(f"Unknown briefing_id: {briefing_id}")
        return None


if __name__ == "__main__":
    run_news_pulse()
