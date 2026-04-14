"""
🔱 titan_K v2 — Interactive Telegram Bot (v3 Upgrade)
Fixes: slow replies, hanging on commands, real-time conversation flow.

Key changes:
  - Async data fetching (non-blocking)
  - Cached prices (refresh every 60s, not every message)
  - Smart context: simple questions skip heavy data fetch
  - Conversation memory within session
"""
import logging
import asyncio
import time
from datetime import datetime
from typing import Dict
import concurrent.futures

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode, ChatAction

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPENAI_API_KEY,
    PORTFOLIO, WATCHLIST, TITAN_SYSTEM_URL,
)

logger = logging.getLogger("titan_k.interactive")

# ── Price Cache (prevents re-fetching every message) ──────────────────────────
_price_cache: Dict = {}
_cache_time: float = 0
CACHE_TTL = 60  # seconds

# ── Conversation Memory (per-session, keyed by chat_id) ───────────────────────
_conversation_history: Dict[str, list] = {}
HISTORY_MAX_TURNS = 20  # keep last 20 user+assistant pairs = 40 messages


def _get_cached_prices() -> Dict:
    """Return cached prices or fetch fresh if stale."""
    global _price_cache, _cache_time
    if time.time() - _cache_time < CACHE_TTL and _price_cache:
        return _price_cache
    try:
        from market_data import fetch_stock_prices
        tickers = set()
        for broker, positions in PORTFOLIO.items():
            for pos in positions:
                tickers.add(pos["ticker"])
        for w in WATCHLIST:
            tickers.add(w["ticker"])
        _price_cache = fetch_stock_prices(list(tickers))
        _cache_time = time.time()
    except Exception as e:
        logger.warning(f"Price cache refresh failed: {e}")
    return _price_cache


def _get_vix_quick() -> str:
    """Fast VIX fetch."""
    try:
        import yfinance as yf
        h = yf.Ticker("^VIX").history(period="2d")
        return str(round(float(h["Close"].iloc[-1]), 2)) if len(h) > 0 else "?"
    except:
        return "?"


def _footer() -> str:
    return f'\n\n🔱 <a href="{TITAN_SYSTEM_URL}">TITAN SYSTEM</a>'


# ══════════════════════════════════════════════════════════════════════════════
# COMMANDS — all fast, non-blocking
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    em = update.effective_message
    if not em:
        return
    chat_id = str(update.effective_chat.id)
    configured_id = str(TELEGRAM_CHAT_ID).strip()
    if configured_id and chat_id != configured_id:
        await em.reply_text(
            f"⚠️ <b>This chat is not configured for briefings.</b>\n\n"
            f"Your chat ID: <code>{chat_id}</code>\n"
            f"Add to .env on your server (Android/laptop):\n"
            f"<code>TELEGRAM_CHAT_ID={chat_id}</code>\n\n"
            f"Then restart the bot. Briefings and alarms go only to the configured chat.",
            parse_mode=ParseMode.HTML,
        )
        return
    await em.reply_text(
        "🔱 <b>titan_K — Minerva Online</b>\n\n"
        "<b>Commands:</b>\n"
        "• /macro — Macro briefing now\n"
        "• /blog — Blog analysis now\n"
        "• /olympus — Olympus dashboard update + Telegram\n"
        "• /price PLTR UEC — Live prices\n"
        "• /score — Portfolio scorecard\n"
        "• /regime — VIX regime\n"
        "• /news — Scan all sources\n"
        "• /risk — Portfolio risk summary\n"
        "• /risk PL — Deep risk screen for ticker\n"
        "• /fund NVDA — Quarterly fundamentals\n"
        "• /reset — Clear conversation memory\n\n"
        "<b>Or just type:</b>\n"
        "\"CRISPR status\" · \"should I buy UEC?\" · \"oil today?\"\n"
        + _footer(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_macro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    em = update.effective_message
    if not em:
        return
    await em.reply_text("🔱 Running macro... 30s")
    try:
        loop = asyncio.get_event_loop()
        msg = await loop.run_in_executor(None, _sync_macro)
        if msg:
            from telegram_bot import send_telegram
            send_telegram(msg)
            await em.reply_text("✅ Macro briefing sent to your configured chat.", disable_web_page_preview=True)
    except Exception as e:
        await em.reply_text(f"⚠️ {str(e)[:200]}")


def _sync_macro() -> str:
    from battle_rhythm import generate_briefing
    return generate_briefing("morning_macro", force=True)


async def cmd_olympus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    em = update.effective_message
    if not em:
        return
    await em.reply_text("🏛 Running Olympus update... ~60s")
    try:
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_olympus),
            timeout=120,
        )
        if result:
            from telegram_bot import send_telegram
            send_telegram(result)
            await em.reply_text("✅ Olympus summary sent to your configured chat.", disable_web_page_preview=True)
    except asyncio.TimeoutError:
        await em.reply_text("⚠️ Olympus timed out (120s). Try again later.")
    except Exception as e:
        await em.reply_text(f"⚠️ {str(e)[:200]}")


def _sync_olympus() -> str:
    """run_olympus_update() writes data/directives.json (see olympus_engine.write_directives_json)."""
    from olympus_engine import run_olympus_update, get_olympus_telegram_summary
    result = run_olympus_update()
    return get_olympus_telegram_summary(result)


async def cmd_blog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    em = update.effective_message
    if not em:
        return
    await em.reply_text("🔱 Scraping blog... max 45s")
    try:
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_blog),
            timeout=60,
        )
        if result == "no_posts":
            await em.reply_text("📭 No new posts in 3 days.")
        elif result == "done":
            await em.reply_text(
                "✅ Blog briefing generated and sent to your configured chat "
                "(same channel as scheduled briefings).",
                disable_web_page_preview=True,
            )
        else:
            await em.reply_text(f"⚠️ {result}")
    except asyncio.TimeoutError:
        await em.reply_text("⚠️ Blog timed out (60s). Naver may be slow.")
    except Exception as e:
        await em.reply_text(f"⚠️ {str(e)[:200]}")


def _sync_blog() -> str:
    from scraper import fetch_blog_posts
    from analyzer import analyze_post, generate_blog_summary
    from telegram_bot import send_blog_briefing

    posts = fetch_blog_posts(days_back=1, max_posts=3)
    if not posts:
        posts = fetch_blog_posts(days_back=3, max_posts=3)
    if not posts:
        return "no_posts"

    from blog_monitor import classify_blog_theme

    analyses = []
    for p in posts:
        r = analyze_post(p)
        if r.get("error"):
            continue
        direct = [c.get("ticker") for c in r.get("companies", []) if c.get("ticker")]
        txt = (p.get("content", "") or "") + "\n" + (p.get("title", "") or "") + "\n" + (r.get("title") or "")
        r["blog_theme"] = classify_blog_theme(txt, direct)
        analyses.append(r)

    if not analyses:
        return "GPT analysis failed for all posts"

    summary = generate_blog_summary(analyses)
    import pytz
    berlin_now = datetime.now(pytz.timezone("Europe/Berlin"))
    send_blog_briefing({
        "timestamp": berlin_now.strftime("%Y-%m-%d %H:%M"),
        "posts": analyses, "summary": summary,
    })
    return "done"


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    em = update.effective_message
    if not em:
        return
    if not context.args:
        await em.reply_text("Usage: /price PLTR  or  /price UEC KTOS")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    tickers = [a.upper() for a in context.args]

    loop = asyncio.get_event_loop()
    prices = await loop.run_in_executor(None, _fetch_specific_prices, tickers)

    try:
        fx = await loop.run_in_executor(None, _get_fx)
    except:
        fx = 1.155

    lines = []
    for t in tickers:
        d = prices.get(t)
        if d:
            chg = d["change_pct"]
            arrow = "▲" if chg >= 0 else "▼"
            eur = round(d["price"] / fx, 2)
            score = _get_score(t)
            score_txt = f" · {score}/10" if score else ""
            lines.append(f"<b>{arrow} {t}</b> ${d['price']} ({chg:+.1f}%) · €{eur}{score_txt}")
        else:
            lines.append(f"❌ {t} — no data")

    lines.append(f"\n💱 EUR/USD: {fx}" + _footer())

    await em.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


def _fetch_specific_prices(tickers):
    from market_data import fetch_stock_prices
    return fetch_stock_prices(tickers)


def _get_fx():
    from market_data import fetch_fx_rate
    return fetch_fx_rate()


async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    em = update.effective_message
    if not em:
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    loop = asyncio.get_event_loop()
    prices = await loop.run_in_executor(None, _get_cached_prices)

    positions = []
    for broker, pos_list in PORTFOLIO.items():
        for pos in pos_list:
            positions.append({**pos, "broker": broker})
    positions.sort(key=lambda x: x.get("score") or 0, reverse=True)

    lines = ["🔱 <b>SCORECARD</b>\n"]
    for pos in positions:
        t = pos["ticker"]
        score = pos.get("score") or 0
        p = prices.get(t, {})
        price = p.get("price", "?")
        chg = p.get("change_pct", 0)
        action = pos.get("action", "HOLD")
        badge = "🟢" if score >= 8 else "🟡" if score >= 5 else "🔴" if score >= 1 else "⚪"
        arrow = "▲" if chg >= 0 else "▼"
        lines.append(f"{badge} <b>{t}</b> {score}/10 ${price} ({arrow}{abs(chg):.1f}%) {action}")

    lines.append(_footer())
    await em.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def cmd_regime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    em = update.effective_message
    if not em:
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    loop = asyncio.get_event_loop()
    vix = await loop.run_in_executor(None, _get_vix_quick)

    try:
        vix_f = float(vix)
        if vix_f >= 30:
            regime, deploy, label = "CRISIS", 100, "FULL DEPLOY"
        elif vix_f >= 20:
            regime, deploy, label = "FEAR", 50, "DEPLOY 50%"
        elif vix_f >= 15:
            regime, deploy, label = "NORMAL", 25, "SELECTIVE"
        else:
            regime, deploy, label = "CALM", 0, "HOLD CASH"
    except:
        regime, deploy, label = "?", 0, "?"

    emoji = {"CALM": "🟢", "NORMAL": "🔵", "FEAR": "🟡", "CRISIS": "🔴"}.get(regime, "⚪")

    await em.reply_text(
        f"🔱 <b>REGIME</b>\n\n"
        f"{emoji} <b>{regime}</b> — {label}\n"
        f"• VIX: {vix}\n"
        f"• Deploy: {deploy}%"
        + _footer(),
        parse_mode=ParseMode.HTML, disable_web_page_preview=True,
    )


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    em = update.effective_message
    if not em:
        return
    await em.reply_text("🔱 Scanning sources... 15s")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    try:
        loop = asyncio.get_event_loop()
        sources = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_news),
            timeout=30,
        )

        lines = ["🔱 <b>NEWS</b>\n"]

        blog = sources.get("blog_posts", [])
        if blog:
            lines.append(f"<b>📰 ranto28 ({len(blog)})</b>")
            for p in blog[:3]:
                lines.append(f"• {p['title'][:60]}")
            lines.append("")

        yahoo = sources.get("yahoo_news", [])
        if yahoo:
            lines.append(f"<b>📡 Yahoo ({len(yahoo)})</b>")
            for p in yahoo[:5]:
                lines.append(f"• [{p.get('ticker','')}] {p['title'][:55]}")
            lines.append("")

        kr = sources.get("kr_news", [])
        if kr:
            lines.append(f"<b>🇰🇷 Korean ({len(kr)})</b>")
            for p in kr[:3]:
                lines.append(f"• {p['title'][:60]}")

        if not any([blog, yahoo, kr]):
            lines.append("📭 No news found.")

        lines.append(_footer())
        await em.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    except asyncio.TimeoutError:
        await em.reply_text("⚠️ News scan timed out.")
    except Exception as e:
        await em.reply_text(f"⚠️ {str(e)[:200]}")


def _sync_news():
    from scraper import fetch_all_sources
    return fetch_all_sources(1)


# ══════════════════════════════════════════════════════════════════════════════
# FREE-FORM MESSAGE — fast GPT with minimal data fetch
# ══════════════════════════════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
        return

    em = update.effective_message
    if not em or not em.text:
        return
    user_msg = em.text
    if len(user_msg.strip()) < 2:
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    loop = asyncio.get_event_loop()

    # Fetch data in background (non-blocking)
    prices_future = loop.run_in_executor(None, _get_cached_prices)
    vix_future = loop.run_in_executor(None, _get_vix_quick)

    try:
        prices = await asyncio.wait_for(prices_future, timeout=10)
    except:
        prices = {}

    try:
        vix = await asyncio.wait_for(vix_future, timeout=5)
    except:
        vix = "?"

    # Compact portfolio context
    port_lines = []
    for broker, pos_list in PORTFOLIO.items():
        for pos in pos_list:
            t = pos["ticker"]
            p = prices.get(t, {})
            port_lines.append(
                f"{t} ${p.get('price','?')} ({p.get('change_pct',0):+.1f}%) "
                f"Score:{pos.get('score','?')}/10 {pos.get('action','HOLD')}"
            )

    watch_lines = [
        f"{w['ticker']} Entry:{w['entry']} Score:{w.get('score','?')}/10"
        for w in WATCHLIST
    ]

    system = (
        f"You are Minerva — Titan's AI advisor. LIVE data below.\n"
        f"RULES: Bullet points. Max 15 words per bullet. No disclaimers. Direct.\n"
        f"You have full conversation memory — reference prior context naturally.\n"
        f"VIX: {vix}\n\nPORTFOLIO:\n" + "\n".join(port_lines) +
        "\n\nWATCHLIST:\n" + "\n".join(watch_lines)
    )

    # ── Conversation Memory ────────────────────────────────────────────────────
    chat_id = str(update.effective_chat.id)
    if chat_id not in _conversation_history:
        _conversation_history[chat_id] = []

    history = _conversation_history[chat_id]
    history.append({"role": "user", "content": user_msg})

    # Trim to max turns (keep last N pairs)
    if len(history) > HISTORY_MAX_TURNS * 2:
        history = history[-(HISTORY_MAX_TURNS * 2):]
        _conversation_history[chat_id] = history

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                *history,
            ],
            temperature=0.4,
            max_tokens=800,
        )
        reply_text = resp.choices[0].message.content
        # Store assistant reply in history
        history.append({"role": "assistant", "content": reply_text})
        _conversation_history[chat_id] = history

        reply = reply_text + _footer()
        await em.reply_text(reply, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"GPT error: {e}")
        await em.reply_text(f"⚠️ {str(e)[:200]}")


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run risk screener for a ticker or show portfolio risk summary."""
    em = update.effective_message
    if not em:
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    ticker = context.args[0].upper() if context.args else None

    loop = asyncio.get_event_loop()
    try:
        if ticker:
            await em.reply_text(f"🔱 Screening risk for {ticker}... ~15s")
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_risk_single, ticker), timeout=30
            )
            lines = [f"🛡 <b>RISK SCREEN: {ticker}</b>\n"]
            if result.get("error"):
                lines.append(f"⚠️ {result['error']}")
            else:
                lines.append(f"Risk Level: <b>{result.get('risk_level','?')}</b> (avg {result.get('avg_risk','?')}/9)\n")
                for dim, score in (result.get("scores") or {}).items():
                    label = dim.replace("_", " ").title()
                    narr = (result.get("narratives") or {}).get(dim, "")
                    icon = "🔴" if score >= 7 else "🟡" if score >= 5 else "🟢"
                    lines.append(f"{icon} <b>{label}</b>: {score}/9\n   {narr}")
        else:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_risk_latest), timeout=5
            )
            lines = ["🛡 <b>PORTFOLIO RISK SUMMARY</b>\n"]
            if not result:
                lines.append("No risk data yet. Run /risk <TICKER> or wait for daily pipeline.")
            else:
                summary = result.get("summary", {})
                for level in ["critical", "high", "moderate", "low"]:
                    items = summary.get(level, [])
                    if items:
                        icon = {"critical": "🔴", "high": "🟡", "moderate": "🟠", "low": "🟢"}[level]
                        lines.append(f"\n{icon} <b>{level.upper()}</b>")
                        for item in items:
                            crits = ", ".join(c.replace("_", " ") for c in item.get("critical_risks", []))
                            extra = f" [{crits}]" if crits else ""
                            lines.append(f"  {item['ticker']} — avg {item['avg_risk']}/9{extra}")

        lines.append(_footer())
        await em.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except asyncio.TimeoutError:
        await em.reply_text("⚠️ Risk screen timed out.")
    except Exception as e:
        await em.reply_text(f"⚠️ {str(e)[:200]}")


def _sync_risk_single(ticker):
    from skills.risk_screener import RiskScreener
    rs = RiskScreener()
    return rs.run_single(ticker)


def _sync_risk_latest():
    from skills.base import SkillRunner
    return SkillRunner.load_latest("risk")


async def cmd_fundamentals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show financial fundamentals for a ticker."""
    em = update.effective_message
    if not em:
        return
    if not context.args:
        await em.reply_text("Usage: /fundamentals PLTR  or  /fund UEC")
        return

    ticker = context.args[0].upper()
    await em.reply_text(f"🔱 Pulling fundamentals for {ticker}... ~10s")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_fund_single, ticker), timeout=30
        )
        if result.get("error"):
            await em.reply_text(f"⚠️ {result['error']}")
            return

        rev = result.get("revenue", {})
        mar = result.get("margins", {})
        bs = result.get("balance_sheet", {})
        val = result.get("valuation", {})
        fcf = result.get("cash_flow", {})

        def _f(v, fmt=",.0f"):
            if v is None:
                return "—"
            if abs(v) >= 1e9:
                return f"${v/1e9:.1f}B"
            if abs(v) >= 1e6:
                return f"${v/1e6:.0f}M"
            return f"${v:{fmt}}"

        def _p(v):
            return f"{v:.1f}%" if v is not None else "—"

        lines = [
            f"📊 <b>FUNDAMENTALS: {ticker}</b>\n",
            f"<b>Revenue</b>: {_f(rev.get('latest_q'))} (trend: {rev.get('trend','?')})",
            f"<b>Margins</b>: Gross {_p(mar.get('gross',{}).get('latest'))} | Op {_p(mar.get('operating',{}).get('latest'))} | Net {_p(mar.get('net',{}).get('latest'))}",
            f"<b>FCF</b>: {_f(fcf.get('latest_fcf'))} (trend: {fcf.get('trend','?')})",
            f"<b>Balance Sheet</b>: Cash {_f(bs.get('cash'))} | Debt {_f(bs.get('total_debt'))} | D/E {bs.get('de_ratio','—')}",
            f"<b>Valuation</b>: P/E {val.get('pe_forward') or val.get('pe_trailing') or '—'} | P/S {val.get('ps_ratio') or '—'} | EV/EBITDA {val.get('ev_ebitda') or '—'}",
        ]
        lines.append(_footer())
        await em.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except asyncio.TimeoutError:
        await em.reply_text("⚠️ Fundamentals fetch timed out.")
    except Exception as e:
        await em.reply_text(f"⚠️ {str(e)[:200]}")


def _sync_fund_single(ticker):
    from skills.financial_analysis import FinancialAnalysis
    fa = FinancialAnalysis()
    return fa.run_single(ticker)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear conversation history for this chat."""
    em = update.effective_message
    if not em:
        return
    chat_id = str(update.effective_chat.id)
    _conversation_history.pop(chat_id, None)
    await em.reply_text(
        "🔱 Conversation memory cleared. Fresh context." + _footer(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_score(ticker: str) -> int:
    for broker, positions in PORTFOLIO.items():
        for pos in positions:
            if pos["ticker"].upper() == ticker.upper():
                return pos.get("score") or 0
    for w in WATCHLIST:
        if w["ticker"].upper() == ticker.upper():
            return w.get("score") or 0
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# BOT RUNNER
# ══════════════════════════════════════════════════════════════════════════════

async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler — logs + tries to notify user."""
    logger.error(f"Bot error: {context.error}", exc_info=context.error)
    if update and hasattr(update, "effective_chat") and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ Error: {str(context.error)[:200]}\nPlease retry.",
            )
        except Exception:
            pass


def register_interactive_handlers(app: Application) -> None:
    """Register Telegram handlers. CommandHandlers first (group 0); free-text last (group 1)."""
    app.add_handler(CommandHandler("start", cmd_start), group=0)
    app.add_handler(CommandHandler("help", cmd_start), group=0)
    app.add_handler(CommandHandler("macro", cmd_macro), group=0)
    app.add_handler(CommandHandler("blog", cmd_blog), group=0)
    app.add_handler(CommandHandler("olympus", cmd_olympus), group=0)
    app.add_handler(CommandHandler("price", cmd_price), group=0)
    app.add_handler(CommandHandler("score", cmd_score), group=0)
    app.add_handler(CommandHandler("regime", cmd_regime), group=0)
    app.add_handler(CommandHandler("news", cmd_news), group=0)
    app.add_handler(CommandHandler("risk", cmd_risk), group=0)
    app.add_handler(CommandHandler("fundamentals", cmd_fundamentals), group=0)
    app.add_handler(CommandHandler("fund", cmd_fundamentals), group=0)
    app.add_handler(CommandHandler("reset", cmd_reset), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message), group=1)
    app.add_error_handler(_error_handler)


def start_interactive_bot():
    import time as _time
    logger.info("Starting interactive bot...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    register_interactive_handlers(app)

    for attempt in range(1, 6):
        try:
            logger.info(f"Bot polling attempt {attempt}/5...")
            app.run_polling(allowed_updates=Update.ALL_TYPES)
            break
        except Exception as e:
            logger.warning(f"Bot start failed (attempt {attempt}): {e}")
            if attempt < 5:
                _time.sleep(5 * attempt)
            else:
                logger.error("Bot failed after 5 attempts. Running scheduler only.")
                raise
