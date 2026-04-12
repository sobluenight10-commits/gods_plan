"""
🔱 titan_K v2 — Telegram Bot Sender
Sends formatted briefings to Titan via Telegram.

Outbound sends use synchronous HTTP (requests) so delivery works from any context:
scheduler threads, ThreadPoolExecutor workers, and python-telegram-bot's asyncio
loop — no nest_asyncio / run_until_complete on a running loop.
"""
import logging
import time
from typing import Optional

import requests
from telegram.constants import ParseMode
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("titan_k.telegram")

MAX_MESSAGE_LENGTH = 4096  # Telegram limit
TG_API = "https://api.telegram.org/bot{token}/sendMessage"


def _parse_mode_value(parse_mode) -> Optional[str]:
    if parse_mode is None:
        return None
    if hasattr(parse_mode, "value"):
        return str(parse_mode.value)
    return str(parse_mode)


def _chunk_telegram_text(text: str) -> list:
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]
    lines = text.split("\n")
    chunks = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > MAX_MESSAGE_LENGTH:
            if current:
                chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks


def send_telegram(text: str, parse_mode: str = ParseMode.HTML):
    """Send to TELEGRAM_CHAT_ID — always synchronous (safe under PTB run_polling)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("send_telegram: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return

    pm = _parse_mode_value(parse_mode)
    url = TG_API.format(token=TELEGRAM_BOT_TOKEN)
    chunks = _chunk_telegram_text(text)

    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if pm:
            payload["parse_mode"] = pm
        try:
            r = requests.post(url, json=payload, timeout=60)
            if not r.ok:
                logger.error("Telegram HTTP %s: %s", r.status_code, r.text[:300])
                payload.pop("parse_mode", None)
                r2 = requests.post(url, json=payload, timeout=60)
                if not r2.ok:
                    logger.error("Telegram fallback HTTP %s: %s", r2.status_code, r2.text[:300])
        except Exception as e:
            logger.error("Telegram send error (chunk %s): %s", i + 1, e)
        if i < len(chunks) - 1:
            time.sleep(0.5)


def send_blog_briefing(briefing: dict):
    """Format and send the blog analysis briefing."""
    from config import TITAN_SYSTEM_URL

    posts = briefing.get("posts", [])
    summary = briefing.get("summary", "No summary available.")
    timestamp = briefing.get("timestamp", "")

    header = (
        f"🔱 <b>titan_K BLOG BRIEFING</b>\n"
        f"📅 {timestamp} Berlin\n"
        f"📡 ranto28 Naver Blog\n"
        f"{'━' * 28}\n\n"
    )

    body = f"<b>📋 SUMMARY</b>\n{summary}\n\n"

    if posts:
        body += f"<b>📰 {len(posts)} ARTICLES</b>\n\n"
        for i, post in enumerate(posts, 1):
            signal = post.get("watch_signal", "—")
            signal_emoji = "🟢" if "BUY" in signal else "🟡" if "WATCH" in signal else "🔴"
            paradigm = " 🌍" if post.get("paradigm_shift") else ""

            body += (
                f"<b>{i}. {post.get('title', 'Untitled')}</b>{paradigm}\n"
                f"  {signal_emoji} {signal}\n"
                f"  💡 {post.get('investment_insight', '—')}\n"
            )

            companies = post.get("companies", [])
            if companies:
                for c in companies[:3]:
                    gem = "💎" if c.get("hidden_gem") else "•"
                    body += (
                        f"  {gem} {c.get('name', '')} ({c.get('ticker', '?')}) "
                        f"{c.get('titan_k_score', '?')}/10\n"
                    )
            body += "\n"

    footer = (
        f"{'━' * 28}\n"
        f"🔱 <a href=\"{TITAN_SYSTEM_URL}\">Open TITAN SYSTEM</a>\n"
        f"<i>The market comes to your prices.</i>"
    )

    send_telegram(header + body + footer)


def send_macro_briefing(briefing: dict):
    """Format and send the macro + portfolio digest — optimized for phone reading."""
    from config import TITAN_SYSTEM_URL

    timestamp = briefing.get("timestamp", "")
    vix = briefing.get("vix", {})
    regime = briefing.get("regime", "UNKNOWN")
    deploy_pct = briefing.get("deploy_pct", 0)
    composite = briefing.get("composite_score", 0)

    regime_emoji = {
        "CALM": "🟢", "NORMAL": "🔵", "FEAR": "🟡", "CRISIS": "🔴"
    }.get(regime, "⚪")

    vix_val = vix.get("value", "?")
    vix_chg = vix.get("change_pct", 0)

    header = (
        f"🔱 <b>titan_K MACRO DIGEST</b>\n"
        f"📅 {timestamp} Berlin\n"
        f"{'━' * 28}\n\n"
        f"{regime_emoji} <b>{regime}</b> · VIX {vix_val} ({vix_chg:+.1f}%)\n"
        f"📊 Composite {composite}/100 → Deploy {deploy_pct}%\n\n"
    )

    overnight = briefing.get("overnight_summary", "")
    body = f"<b>🌙 OVERNIGHT</b>\n{overnight}\n\n"

    key_moves = briefing.get("key_moves", [])
    if key_moves:
        body += "<b>📊 KEY MOVES</b>\n"
        for move in key_moves:
            direction = "▲" if move.get("change_pct", 0) >= 0 else "▼"
            chg = move.get("change_pct", 0)
            if abs(chg) >= 3:
                body += f"  <b>{direction} {move['name']} {move.get('value', '?')} ({chg:+.1f}%)</b>\n"
            else:
                body += f"  {direction} {move['name']} {move.get('value', '?')} ({chg:+.1f}%)\n"
        body += "\n"

    portfolio_impact = briefing.get("portfolio_impact", "")
    if portfolio_impact:
        body += f"<b>💼 PORTFOLIO</b>\n{portfolio_impact}\n\n"

    actions = briefing.get("todays_actions", "")
    if actions:
        body += f"<b>⚡ TODAY</b>\n{actions}\n\n"

    earnings = briefing.get("earnings_today", [])
    if earnings:
        body += "<b>📅 EARNINGS TODAY</b>\n"
        for e in earnings:
            body += f"  🔴 {e['ticker']} {e.get('timing', '')} — {e.get('importance', '')}\n"
        body += "\n"

    footer = (
        f"{'━' * 28}\n"
        f"🔱 <a href=\"{TITAN_SYSTEM_URL}\">Open TITAN SYSTEM</a>\n"
        f"<i>Limits armed. Go to work.</i>"
    )

    send_telegram(header + body + footer)


def send_olympus_briefing(data: dict):
    """Format and send the Olympus forecast update."""
    from olympus_engine import get_olympus_telegram_summary
    msg = get_olympus_telegram_summary(data)
    send_telegram(msg)


def send_test_ping():
    """Send a test message to verify bot connection."""
    send_telegram(
        "🔱 <b>titan_K v2 — CONNECTION TEST</b>\n\n"
        "✅ Bot is online and connected.\n"
        "📡 Briefings will arrive at 07:00 Berlin time.\n\n"
        "<i>Minerva standing by.</i>"
    )
