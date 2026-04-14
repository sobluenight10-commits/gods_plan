"""
🔱 titan_K v2 — Telegram Bot Sender
Sends formatted briefings to Titan via Telegram.

Outbound sends use synchronous HTTP (requests) so delivery works from any context:
scheduler threads, ThreadPoolExecutor workers, and python-telegram-bot's asyncio
loop — no nest_asyncio / run_until_complete on a running loop.

Resilience: urllib3 retries + exponential backoff on connection/TLS resets (common on
Windows to api.telegram.org). Optional TELEGRAM_FORCE_IPV4 (default on Windows) avoids
bad IPv6 paths.
"""
from __future__ import annotations

import contextlib
import logging
import socket
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from telegram.constants import ParseMode
from urllib3.util.retry import Retry

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_FORCE_IPV4,
    TELEGRAM_HTTP_TIMEOUT,
)

logger = logging.getLogger("titan_k.telegram")

MAX_MESSAGE_LENGTH = 4096  # Telegram limit
TG_API = "https://api.telegram.org/bot{token}/sendMessage"

_session: Optional[requests.Session] = None
_orig_getaddrinfo = socket.getaddrinfo


@contextlib.contextmanager
def _ipv4_dns_only():
    """Force IPv4 for DNS resolution during this block (restores after)."""

    def _gai(host, port, family=0, type=0, proto=0, flags=0):
        fam = socket.AF_INET if family in (0, socket.AF_UNSPEC) else family
        return _orig_getaddrinfo(host, port, fam, type, proto, flags)

    socket.getaddrinfo = _gai  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.getaddrinfo = _orig_getaddrinfo  # type: ignore[assignment]


def _network_cm():
    return _ipv4_dns_only() if TELEGRAM_FORCE_IPV4 else contextlib.nullcontext()


def _telegram_session() -> requests.Session:
    global _session
    if _session is not None:
        return _session
    retry = Retry(
        total=6,
        connect=6,
        read=4,
        backoff_factor=0.75,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["POST", "HEAD", "GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    s = requests.Session()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    _session = s
    return s


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


def _post_telegram(url: str, payload: dict, timeout: float) -> Optional[requests.Response]:
    """POST with IPv4 context + manual retries (covers resets after urllib3 retries)."""
    session = _telegram_session()
    transient = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
        requests.exceptions.SSLError,
    )
    last_exc: Optional[BaseException] = None
    for attempt in range(6):
        try:
            with _network_cm():
                return session.post(url, json=payload, timeout=timeout)
        except transient as e:
            last_exc = e
            delay = min(30.0, 0.6 * (2**attempt))
            logger.warning(
                "Telegram transient error (attempt %s/6): %s — retry in %.1fs",
                attempt + 1,
                e,
                delay,
            )
            time.sleep(delay)
    if last_exc is not None:
        logger.error("Telegram send failed after retries: %s", last_exc)
    return None


def send_telegram(text: str, parse_mode: str = ParseMode.HTML) -> bool:
    """Send to TELEGRAM_CHAT_ID — always synchronous (safe under PTB run_polling). Returns success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("send_telegram: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return False

    pm = _parse_mode_value(parse_mode)
    url = TG_API.format(token=TELEGRAM_BOT_TOKEN)
    chunks = _chunk_telegram_text(text)
    timeout = TELEGRAM_HTTP_TIMEOUT
    ok_all = True

    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if pm:
            payload["parse_mode"] = pm
        r = _post_telegram(url, payload, timeout)
        if r is None:
            ok_all = False
        elif not r.ok:
            if r.status_code == 401:
                logger.error(
                    "Telegram HTTP 401 Unauthorized — TELEGRAM_BOT_TOKEN is wrong or revoked. "
                    "Copy the token from @BotFather into .env on this machine."
                )
            else:
                logger.error("Telegram HTTP %s: %s", r.status_code, r.text[:300])
            payload_plain = dict(payload)
            payload_plain.pop("parse_mode", None)
            r2 = _post_telegram(url, payload_plain, timeout)
            if r2 is None or not r2.ok:
                logger.error(
                    "Telegram fallback HTTP %s",
                    getattr(r2, "status_code", "no response"),
                )
                ok_all = False
        if i < len(chunks) - 1:
            time.sleep(0.5)
    return ok_all


def send_blog_briefing(briefing: dict):
    """Format and send the blog analysis briefing."""
    from html import escape as html_escape

    from config import TITAN_SYSTEM_URL, NAVER_BLOG_LABEL

    posts = briefing.get("posts", [])
    summary = briefing.get("summary", "No summary available.")
    timestamp = briefing.get("timestamp", "")

    header = (
        f"🔱 <b>titan_K BLOG BRIEFING</b>\n"
        f"📅 {timestamp} Berlin\n"
        f"📡 {html_escape(NAVER_BLOG_LABEL)} — Naver RSS\n"
        f"{'━' * 28}\n\n"
    )

    body = f"<b>📋 SUMMARY</b>\n{summary}\n\n"

    if posts:
        body += f"<b>📰 {len(posts)} ARTICLES</b>\n\n"
        for i, post in enumerate(posts, 1):
            signal = post.get("watch_signal", "—")
            signal_emoji = "🟢" if "BUY" in signal else "🟡" if "WATCH" in signal else "🔴"
            paradigm = " 🌍" if post.get("paradigm_shift") else ""
            post_url = (post.get("url") or post.get("link") or "").strip()
            if not post_url:
                post_url = "https://blog.naver.com/ranto28"
            href = post_url.replace("&", "&amp;")

            body += (
                f"<b>{i}. {post.get('title', 'Untitled')}</b>{paradigm}\n"
                f"  🔗 <a href=\"{href}\">Read original article</a>\n"
                f"  {signal_emoji} {signal}\n"
                f"  💡 {post.get('investment_insight', '—')}\n"
            )

            bt = post.get("blog_theme")
            if isinstance(bt, dict):
                th = ", ".join(bt.get("themes") or []) or "none"
                cf = ", ".join(bt.get("portfolio_confirmed") or []) or "none"
                nw = ", ".join(bt.get("new_watchlist") or []) or "none"
                body += (
                    f"  🌍 <b>THEME:</b> {html_escape(th)}\n"
                    f"  ✅ <b>CONFIRMS IN PORTFOLIO:</b> {html_escape(cf)}\n"
                    f"  🔍 <b>NEW WATCHLIST CANDIDATES:</b> {html_escape(nw)}\n"
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


def send_test_ping() -> bool:
    """Send a test message to verify bot connection."""
    return send_telegram(
        "🔱 <b>titan_K v2 — CONNECTION TEST</b>\n\n"
        "✅ Bot is online and connected.\n"
        "📡 Briefings will arrive at 07:00 Berlin time.\n\n"
        "<i>Minerva standing by.</i>"
    )
