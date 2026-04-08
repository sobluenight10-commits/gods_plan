"""
🔱 OLYMPUS — Price Alert System
Fires IMMEDIATELY when:
1. Any held position drops >8% in a single session (thesis review trigger)
2. Any EXIT_ON_BOUNCE position rises >5% (exit window open)
3. Any active stop level is breached

Runs every 30 minutes during market hours via the scheduler.
This is Lesson 07: the system must warn GOD in real time, not wait for a scheduled brief.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List

import pytz
import requests

logger = logging.getLogger("titan_k.price_alert")

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
ALERT_CACHE = os.path.join("data", "alert_cache.json")

# Thresholds
DROP_ALERT_PCT   = -8.0   # Lesson 05: -8% = thesis review mandatory
BOUNCE_ALERT_PCT = +5.0   # Exit-flagged position bouncing = exit window
STOP_BUFFER_PCT  = 0.02   # Alert when within 2% of stop level


def _load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"State load failed: {e}")
        return {}


def _load_alert_cache() -> dict:
    try:
        with open(ALERT_CACHE, "r") as f:
            return json.load(f)
    except Exception:
        return {"sent": {}}


def _save_alert_cache(cache: dict):
    os.makedirs("data", exist_ok=True)
    with open(ALERT_CACHE, "w") as f:
        json.dump(cache, f, indent=2)


def _already_alerted(cache: dict, key: str) -> bool:
    """Prevent duplicate alerts for the same event on the same day."""
    today = datetime.now().strftime("%Y-%m-%d")
    return cache.get("sent", {}).get(f"{today}_{key}", False)


def _mark_alerted(cache: dict, key: str):
    today = datetime.now().strftime("%Y-%m-%d")
    if "sent" not in cache:
        cache["sent"] = {}
    cache["sent"][f"{today}_{key}"] = True


def _fetch_price(ticker: str) -> dict:
    """Fetch current price and daily change for a single ticker."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = getattr(info, "last_price", None)
        prev  = getattr(info, "previous_close", None)
        if price and prev and prev > 0:
            chg_pct = (price - prev) / prev * 100
            return {"price": round(price, 2), "change_pct": round(chg_pct, 2)}
    except Exception as e:
        logger.debug(f"Price fetch {ticker}: {e}")
    return {}


def _send_alert(message: str):
    """Send immediately to Telegram."""
    import config
    token   = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
        logger.info(f"Alert sent: {message[:80]}")
    except Exception as e:
        logger.error(f"Alert send failed: {e}")


def _send_thesis_plain(message: str):
    """Plain-text Telegram (no HTML) so /price commands and emojis render as intended."""
    import config
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
            timeout=10,
        )
        logger.info(f"Thesis alert sent: {message[:80]}")
    except Exception as e:
        logger.error(f"Thesis alert send failed: {e}")


def check_thesis_alerts():
    """
    Berlin weekdays 15:30–22:00: scan config.THESIS_ALERT_TICKERS with yfinance;
    if session change <= -8%, send one Telegram per ticker per day (Lesson #05).
    Scheduler calls this every 30 minutes; this function no-ops outside the window.
    """
    try:
        _check_thesis_alerts_impl()
    except Exception as e:
        logger.error(f"check_thesis_alerts failed: {e}", exc_info=True)


def _check_thesis_alerts_impl():
    import config

    berlin = pytz.timezone(getattr(config, "TIMEZONE", "Europe/Berlin"))
    now = datetime.now(berlin)
    if now.weekday() >= 5:
        return
    hour = now.hour + now.minute / 60.0
    start = float(getattr(config, "THESIS_ALERT_WINDOW_START_HOUR", 15.5))
    end = float(getattr(config, "THESIS_ALERT_WINDOW_END_HOUR", 22.0))
    if hour < start or hour > end:
        return

    tickers = getattr(config, "THESIS_ALERT_TICKERS", None) or []
    if not tickers:
        return

    cache = _load_alert_cache()
    fired = []
    cache_dirty = False

    for ticker in tickers:
        if _already_alerted(cache, f"thesis_{ticker}"):
            continue
        data = _fetch_price(ticker)
        if not data:
            continue
        chg = data.get("change_pct", 0)
        if chg > DROP_ALERT_PCT:
            continue

        msg = (
            f"🚨 THESIS ALERT — {ticker}\n"
            f"Drop: {chg:+.1f}% today\n"
            f"This triggered Lesson #05 — Company news overrides macro.\n"
            f"ACTION REQUIRED: Check news now. Is thesis broken?\n"
            f"/price {ticker} for current price"
        )
        _send_thesis_plain(msg)
        _mark_alerted(cache, f"thesis_{ticker}")
        cache_dirty = True
        fired.append(f"{ticker} {chg:+.1f}%")

    if cache_dirty:
        _save_alert_cache(cache)
    if fired:
        logger.info(f"check_thesis_alerts fired: {fired}")


def run_price_alerts():
    """
    Main entry point. Called every 30 minutes during market hours.
    Checks three alert conditions and fires Telegram immediately if triggered.
    """
    import config

    berlin = pytz.timezone(config.TIMEZONE)
    now    = datetime.now(berlin)

    # Weekdays only, 14:30–23:00 Berlin (US market hours)
    if now.weekday() >= 5:
        return
    hour = now.hour + now.minute / 60.0
    if hour < 14.5 or hour > 23.0:
        return

    state = _load_state()
    cache = _load_alert_cache()
    alerts_sent = []

    # ── Build ticker lists from state ──────────────────────────────────────
    held_tickers = []
    for score in state.get("god_scores", []):
        sig = score.get("signal", "")
        if sig not in ("LOCKED", "EXIT_ON_BOUNCE", "TARGET"):
            held_tickers.append(score["ticker"])

    exit_tickers = [e["ticker"] for e in state.get("exit_flags", [])]
    stops        = {s["ticker"]: s["stop_USD"] for s in state.get("active_stops", [])}

    # ── Check 1: Held positions dropping >8% ──────────────────────────────
    for ticker in held_tickers:
        if _already_alerted(cache, f"drop_{ticker}"):
            continue
        data = _fetch_price(ticker)
        if not data:
            continue
        chg  = data.get("change_pct", 0)
        price = data.get("price", 0)

        if chg <= DROP_ALERT_PCT:
            # Get kill criteria from state
            kill = state.get("kill_criteria", {}).get(ticker, "Check thesis manually")
            msg = (
                f"🚨 <b>THESIS REVIEW — {ticker}</b>\n"
                f"📉 {chg:+.1f}% today @ ${price}\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Lesson 05: company move &gt;8% requires immediate thesis check.\n\n"
                f"<b>Has the core thesis changed?</b>\n"
                f"Kill criteria: {kill}\n\n"
                f"⚡ Reply: HOLD / SELL / UPDATE STATE"
            )
            _send_alert(msg)
            _mark_alerted(cache, f"drop_{ticker}")
            alerts_sent.append(f"DROP {ticker} {chg:+.1f}%")

    # ── Check 2: Exit-flagged positions bouncing >5% ───────────────────────
    for ticker in exit_tickers:
        if _already_alerted(cache, f"bounce_{ticker}"):
            continue
        data = _fetch_price(ticker)
        if not data:
            continue
        chg   = data.get("change_pct", 0)
        price = data.get("price", 0)

        if chg >= BOUNCE_ALERT_PCT:
            exit_info = next(
                (e for e in state.get("exit_flags", []) if e["ticker"] == ticker), {}
            )
            msg = (
                f"⚡ <b>EXIT WINDOW OPEN — {ticker}</b>\n"
                f"📈 {chg:+.1f}% today @ ${price}\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"This is the bounce. Thesis: {exit_info.get('reason', 'broken')}\n"
                f"Lesson 02: a spike in a broken thesis is an exit gift.\n\n"
                f"<b>Action: SELL NOW on TR/Kiwoom</b>\n"
                f"Do not wait for a higher price."
            )
            _send_alert(msg)
            _mark_alerted(cache, f"bounce_{ticker}")
            alerts_sent.append(f"BOUNCE {ticker} {chg:+.1f}%")

    # ── Check 3: Stop levels approached within 2% ─────────────────────────
    for ticker, stop_level in stops.items():
        if _already_alerted(cache, f"stop_{ticker}"):
            continue
        data = _fetch_price(ticker)
        if not data:
            continue
        price = data.get("price", 0)
        if price <= 0 or stop_level <= 0:
            continue

        distance_pct = (price - stop_level) / stop_level * 100
        if 0 < distance_pct <= STOP_BUFFER_PCT * 100:
            stop_info = next(
                (s for s in state.get("active_stops", []) if s["ticker"] == ticker), {}
            )
            msg = (
                f"⚠️ <b>STOP APPROACHING — {ticker}</b>\n"
                f"Price: ${price} | Stop: ${stop_level}\n"
                f"Distance: {distance_pct:.1f}% above stop\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Reason for stop: {stop_info.get('reason', 'see state.json')}\n\n"
                f"<b>Prepare to execute if stop is breached.</b>"
            )
            _send_alert(msg)
            _mark_alerted(cache, f"stop_{ticker}")
            alerts_sent.append(f"STOP {ticker} @ ${price} vs ${stop_level}")

    _save_alert_cache(cache)

    if alerts_sent:
        logger.info(f"Price alerts fired: {alerts_sent}")
    else:
        logger.debug("Price alert check: no triggers")
