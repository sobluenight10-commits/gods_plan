"""
🔱 OLYMPUS — Price Alert System
Fires IMMEDIATELY when:
1. Held positions hit tiered session drops (watch / thesis / emergency — see config ALERT_TIER_*)
2. Any EXIT_ON_BOUNCE position rises >5% (exit window open)
3. Any active stop level is breached

Runs thesis/spike scans every 5 minutes during US window via the scheduler; NewsAPI keyword
scan on a separate interval (see main.py).
This is Lesson 07: the system must warn GOD in real time, not wait for a scheduled brief.
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pytz
import requests

logger = logging.getLogger("titan_k.price_alert")

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
ALERT_CACHE = os.path.join("data", "alert_cache.json")
NEWS_ALERT_CACHE = os.path.join("data", "news_alert_cache.json")
BLOG_TICKERS_FILE = os.path.join("data", "blog_tickers.json")

# NewsAPI headline keyword lists (substring match, case-insensitive; longer phrases first where needed)
_NEWS_DANGER_KEYWORDS: Tuple[str, ...] = (
    "sec investigation",
    "contract loss",
    "cancelled",
    "terminated",
    "downgrade",
    "fraud",
    "bankruptcy",
    "recall",
    "sanction",
    "delisted",
)
_NEWS_OPPORTUNITY_KEYWORDS: Tuple[str, ...] = (
    "major contract",
    "government contract",
    "contract awarded",
    "deal signed",
    "fda approval",
    "fda approved",
    "breakthrough",
    "record revenue",
    "beat estimates",
    "strategic acquisition",
    "ipo filed",
    "s-1 filed",
)

# Local thresholds (drop tiers: config.ALERT_TIER_WATCH / THESIS / EMERGENCY)
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
        with open(ALERT_CACHE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("sent", {})
    d.setdefault("critical_48h", {})
    if not isinstance(d.get("critical_48h"), dict):
        d["critical_48h"] = {}
    return d


def _save_alert_cache(cache: dict):
    os.makedirs("data", exist_ok=True)
    if "critical_48h" not in cache or not isinstance(cache.get("critical_48h"), dict):
        cache["critical_48h"] = {}
    with open(ALERT_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def _critical_reason_hash(reason: str) -> str:
    norm = (reason or "").strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:20]


def _should_skip_critical_dedup(ticker: str, reason_key: str) -> bool:
    """Same ticker + same reason hash within 48h → skip CRITICAL-class Telegram."""
    cache = _load_alert_cache()
    bucket = cache.get("critical_48h") or {}
    t = (ticker or "").upper()
    h = _critical_reason_hash(reason_key)
    prev = (bucket.get(t) or {}).get(h)
    if prev is None:
        return False
    ts = float(prev) if not isinstance(prev, dict) else float(prev.get("ts", 0))
    return (time.time() - ts) < (48 * 3600)


def _record_critical_dedup(ticker: str, reason_key: str) -> None:
    cache = _load_alert_cache()
    t = (ticker or "").upper()
    h = _critical_reason_hash(reason_key)
    ch = cache.setdefault("critical_48h", {})
    if t not in ch or not isinstance(ch[t], dict):
        ch[t] = {}
    ch[t][h] = time.time()
    _save_alert_cache(cache)


def _already_alerted(cache: dict, key: str) -> bool:
    """Prevent duplicate alerts for the same event on the same day."""
    today = datetime.now().strftime("%Y-%m-%d")
    return cache.get("sent", {}).get(f"{today}_{key}", False)


def _mark_alerted(cache: dict, key: str):
    today = datetime.now().strftime("%Y-%m-%d")
    if "sent" not in cache:
        cache["sent"] = {}
    cache["sent"][f"{today}_{key}"] = True


def _load_blog_tickers() -> List[str]:
    """Tickers extracted from blog posts (blog_monitor); merged into NewsAPI scan."""
    try:
        with open(BLOG_TICKERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("tickers") or []
        return [str(t).strip() for t in raw if t and str(t).strip()]
    except Exception:
        return []


def _load_news_alert_cache() -> dict:
    try:
        with open(NEWS_ALERT_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"sent": {}}


def _save_news_alert_cache(cache: dict):
    os.makedirs("data", exist_ok=True)
    with open(NEWS_ALERT_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def _headline_digest(title: str) -> str:
    norm = (title or "").strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:20]


def _already_news_headline(cache: dict, ticker: str, headline: str) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    key = f"{ticker}_{_headline_digest(headline)}"
    return cache.get("sent", {}).get(f"{today}_{key}", False)


def _mark_news_headline(cache: dict, ticker: str, headline: str):
    today = datetime.now().strftime("%Y-%m-%d")
    if "sent" not in cache:
        cache["sent"] = {}
    key = f"{ticker}_{_headline_digest(headline)}"
    cache["sent"][f"{today}_{key}"] = True


def _match_news_keyword(
    headline_lower: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (kind, keyword) where kind is 'danger' or 'opportunity'; danger wins if both match."""
    for kw in _NEWS_DANGER_KEYWORDS:
        if kw in headline_lower:
            return "danger", kw
    for kw in _NEWS_OPPORTUNITY_KEYWORDS:
        if kw in headline_lower:
            return "opportunity", kw
    return None, None


def _newsapi_fetch_articles(query: str, api_key: str) -> List[dict]:
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 20,
                "apiKey": api_key,
            },
            timeout=25,
        )
        if r.status_code != 200:
            logger.warning("NewsAPI HTTP %s: %s", r.status_code, (r.text or "")[:240])
            return []
        data = r.json()
        if data.get("status") != "ok":
            logger.warning("NewsAPI: %s", data.get("message", data))
            return []
        return list(data.get("articles") or [])
    except Exception as e:
        logger.error("NewsAPI request failed: %s", e)
        return []


def check_news_alerts():
    """
    Weekdays 06:30–23:30 Berlin: NewsAPI keyword scan per THESIS_ALERT_TICKERS plus
    tickers from data/blog_tickers.json (query = ticker + company name).
    Cached: one Telegram per ticker per headline per day.
    """
    try:
        _check_news_alerts_impl()
    except Exception as e:
        logger.error("check_news_alerts failed: %s", e, exc_info=True)


def _check_news_alerts_impl():
    import config

    api_key = (getattr(config, "NEWS_API_KEY", "") or "").strip()
    if not api_key:
        return

    berlin = pytz.timezone(getattr(config, "TIMEZONE", "Europe/Berlin"))
    now = datetime.now(berlin)
    if now.weekday() >= 5:
        return
    hour = now.hour + now.minute / 60.0
    if hour < 6.5 or hour > 23.5:
        return

    thesis = list(getattr(config, "THESIS_ALERT_TICKERS", None) or [])
    blog_extra = _load_blog_tickers()
    seen: set = set()
    tickers: List[str] = []
    for t in thesis + blog_extra:
        t = str(t).strip()
        if not t or t in seen:
            continue
        seen.add(t)
        tickers.append(t)
    if not tickers:
        return

    cache = _load_news_alert_cache()
    sec_cache = _load_sec_cache()
    critical_map = sec_cache.setdefault("critical_news", {})
    dirty = False
    sec_dirty = False
    fired: List[str] = []

    for ticker in tickers:
        name = config.get_company_name_for_ticker(ticker)
        query = f"{ticker} {name}"
        articles = _newsapi_fetch_articles(query, api_key)
        time.sleep(0.4)

        for art in articles:
            title = (art.get("title") or "").strip()
            if not title:
                continue
            if _already_news_headline(cache, ticker, title):
                continue
            hl = title.lower()
            kind, kw = _match_news_keyword(hl)
            if not kind or not kw:
                continue

            danger_pdata: dict = {}
            crit_reason = ""
            if kind == "danger":
                dig = _headline_digest(title)
                danger_pdata = _fetch_price(ticker)
                bucket = _price_bucket(float(danger_pdata.get("price") or 0))
                if not _critical_news_should_fire(critical_map, ticker, dig, bucket, None):
                    _mark_news_headline(cache, ticker, title)
                    dirty = True
                    continue
                crit_reason = f"news_danger:{kw}:{title[:220]}"
                if _should_skip_critical_dedup(ticker, crit_reason):
                    _mark_news_headline(cache, ticker, title)
                    dirty = True
                    continue
                msg = (
                    f"🔴 NEWS ALERT — {ticker}\n"
                    f"⚠️ DANGER SIGNAL DETECTED\n"
                    f"Headline: {title}\n"
                    f"Keyword: {kw}\n"
                    f"ACTION: Check thesis immediately. Price may not have moved yet."
                )
            else:
                msg = (
                    f"🟢 NEWS ALERT — {ticker}\n"
                    f"💡 OPPORTUNITY SIGNAL\n"
                    f"Headline: {title}\n"
                    f"Keyword: {kw}\n"
                    f"ACTION: Review for entry. Check GOD Score before acting."
                )
            _send_thesis_plain(msg)
            _mark_news_headline(cache, ticker, title)
            dirty = True
            if kind == "danger":
                pdata = danger_pdata if danger_pdata else _fetch_price(ticker)
                bucket = _price_bucket(float(pdata.get("price") or 0))
                _mark_critical_news(
                    critical_map,
                    ticker,
                    _headline_digest(title),
                    bucket,
                    None,
                )
                sec_dirty = True
                if crit_reason:
                    _record_critical_dedup(ticker, crit_reason)
            fired.append(f"{ticker} {kind} {kw[:24]}")

    if dirty:
        _save_news_alert_cache(cache)
    if sec_dirty:
        _save_sec_cache(sec_cache)
    if fired:
        logger.info("check_news_alerts fired: %s", fired)


def _telegram_price_drop_classification(ticker: str, chg: float) -> str:
    """Sector vs company decomposition for -8%+ style alerts (live ETF bench)."""
    try:
        from battle_rhythm import classify_price_drop, sector_drop_for_ticker
        from market_data import fetch_stock_prices

        keys = ["QQQ", "XLE", "URA", "ARKX", "XBI", "BOTZ", "IGV", "DJP"]
        raw = fetch_stock_prices(keys)
        bench = {k: float(raw.get(k, {}).get("change_pct", 0)) for k in keys}
        sec_drop = sector_drop_for_ticker(ticker, bench)
        cls = classify_price_drop(ticker, float(chg), sec_drop, False, [])
        return (
            f"\n\n📊 DROP DECOMPOSITION\n{cls['classification']}\n{cls['action']}\n"
            f"Total: {cls['total_drop']} · Sector proxy: {cls['sector_drop']} · "
            f"Co-specific: {cls['company_specific']}"
        )
    except Exception as e:
        logger.debug("price drop classify: %s", e)
        return ""


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


def _volume_vs_avg_pct(ticker: str) -> Tuple[float, str]:
    """Today's volume vs prior ~30 session average; returns (pct_of_avg, short tag)."""
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="45d")
        if hist is None or hist.empty or "Volume" not in hist.columns:
            return 100.0, "NORMAL"
        vols = hist["Volume"].dropna()
        if len(vols) < 3:
            return 100.0, "NORMAL"
        today_v = float(vols.iloc[-1])
        prior = vols.iloc[:-1]
        if len(prior) >= 30:
            avg_v = float(prior.iloc[-30:].mean())
        else:
            avg_v = float(prior.mean()) if len(prior) else 0.0
        if avg_v <= 0:
            return 100.0, "NORMAL"
        pct = (today_v / avg_v) * 100.0
        if pct < 50:
            tag = "LOW — retail only"
        elif pct <= 100:
            tag = "NORMAL"
        elif pct <= 150:
            tag = "elevated vol"
        else:
            tag = "HIGH VOL — institutional"
        return pct, tag
    except Exception as e:
        logger.debug("volume vs avg %s: %s", ticker, e)
        return 100.0, "NORMAL"


def _headlines_digest_block(articles: List[dict]) -> str:
    lines = []
    for a in (articles or [])[:12]:
        title = (a.get("title") or "").strip()
        if not title or "[Removed]" in title:
            continue
        src = (a.get("source") or "").strip()
        lines.append(f"- [{src}] {title}")
    if not lines:
        return "(No headlines in window — treat as UNKNOWN.)"
    return "\n".join(lines)


def _next_catalyst_for_ticker(ticker: str) -> str:
    """Best-effort next catalyst from state.json calendar (ticker match or next global)."""
    tk = (ticker or "").strip().upper().replace(".", "")
    state = _load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    cal = [c for c in (state.get("calendar") or []) if isinstance(c, dict)]
    cal.sort(key=lambda c: c.get("date") or "")
    fallback = ""
    for c in cal:
        d = c.get("date") or ""
        if d < today:
            continue
        ev = f"{c.get('event', '')} {c.get('action', '')}".upper().replace(".", "")
        blob = f"{d} · {c.get('event', '')}"
        if tk and tk in ev:
            return blob.strip()
        if not fallback:
            fallback = blob.strip()
    return fallback if fallback else "—"


def _parse_gpt_three_lines(raw: str) -> Tuple[str, str, str]:
    raw = (raw or "").strip()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

    def _strip_num_prefix(s: str) -> str:
        u = s.upper()
        for pref in ("LINE 1:", "LINE 2:", "LINE 3:"):
            if u.startswith(pref):
                return s[len(pref) :].strip()
        return s

    out: List[str] = []
    for i in range(3):
        if i < len(lines):
            out.append(_strip_num_prefix(lines[i]))
        else:
            out.append("")
    defaults = (
        "CAUSE: UNKNOWN — no reliable read on drivers in-window.",
        "THESIS: REVIEW NEEDED — confirm vs OLYMPUS / company facts.",
        "ACTION: HOLD · DO NOT CHASE",
    )
    for i in range(3):
        if not out[i]:
            out[i] = defaults[i]
    return out[0], out[1], out[2]


def _gpt_intraday_move_brief(ticker: str, pct: float, headlines: str) -> Tuple[str, str, str]:
    from battle_rhythm import _gpt

    system = "You are MINERVA, a cold-blooded investment analyst."
    user = f"""Ticker: {ticker}
Move: {pct:+.1f}% today
Recent headlines (48h):
{headlines}

Answer in exactly 3 lines:
LINE 1: CAUSE: [NEWS-DRIVEN / MACRO / UNKNOWN] — one sentence max
LINE 2: THESIS: [INTACT / WOUNDED / REVIEW NEEDED] — one sentence max
LINE 3: ACTION: [one of: HOLD · DO NOT CHASE · ENTRY WATCH $XX · EXIT REVIEW]

No other text."""
    raw = _gpt(system, user, tokens=350)
    return _parse_gpt_three_lines(raw)


def _build_minerva_move_alert_text(
    ticker: str,
    pct: float,
    banner: str,
    direction: str,
) -> str:
    """
    banner: first line e.g. '🟡 SPIKE ALERT — TSM'
    direction: 'spike' | 'drop' (move word Rise vs Drop)
    """
    from battle_rhythm import fetch_portfolio_news

    articles = fetch_portfolio_news(ticker=ticker, hours=48)
    headlines = _headlines_digest_block(articles)
    line1, line2, line3 = _gpt_intraday_move_brief(ticker, pct, headlines)
    vol_pct, vol_tag = _volume_vs_avg_pct(ticker)
    next_cat = _next_catalyst_for_ticker(ticker)
    move_word = "Rise" if direction == "spike" else "Drop"
    body = (
        f"{banner}\n"
        f"{move_word}: {pct:+.1f}% · Vol: {vol_pct:.0f}% of avg ({vol_tag})\n\n"
        f"{line1}\n"
        f"{line2}\n"
        f"{line3}\n\n"
        f"─────────────────\n"
        f"Next catalyst: {next_cat}\n"
        f"Do NOT chase. Minerva brief at 16:30."
    )
    return body


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


def _trigger_reflexivity(ticker: str, chg: float, price: float) -> None:
    """Fire-and-forget: run Soros reflexivity analysis in a background thread."""
    import threading
    def _run():
        try:
            from battle_rhythm import analyze_reflexivity
            analyze_reflexivity(ticker, chg, price)
        except Exception as e:
            logger.error(f"Reflexivity analysis failed for {ticker}: {e}")
    threading.Thread(target=_run, daemon=True).start()


def check_thesis_alerts():
    """
    Berlin weekdays 15:30–22:00: scan config.THESIS_ALERT_TICKERS with yfinance;
    tiered drops (config ALERT_TIER_WATCH / THESIS / EMERGENCY) and upside spikes
    (config ALERT_TIER_WATCH_UP / MOMENTUM_UP / BREAKOUT_UP). One Telegram per tier
    per ticker per day; highest tier suppresses lower tiers for that day.
    Scheduler calls this every 5 minutes; this function no-ops outside the window.
    """
    try:
        _check_thesis_alerts_impl()
    except Exception as e:
        logger.error(f"check_thesis_alerts failed: {e}", exc_info=True)


def _check_thesis_alerts_impl():
    import config

    tw = float(getattr(config, "ALERT_TIER_WATCH", -8))
    tt = float(getattr(config, "ALERT_TIER_THESIS", -12))
    te = float(getattr(config, "ALERT_TIER_EMERGENCY", -15))
    uw = float(getattr(config, "ALERT_TIER_WATCH_UP", 5))
    um = float(getattr(config, "ALERT_TIER_MOMENTUM_UP", 10))
    ub = float(getattr(config, "ALERT_TIER_BREAKOUT_UP", 15))

    berlin = pytz.timezone(getattr(config, "TIMEZONE", "Europe/Berlin"))
    now = datetime.now(berlin)
    if now.weekday() >= 5:
        return
    hour = now.hour + now.minute / 60.0
    start = float(getattr(config, "THESIS_ALERT_WINDOW_START_HOUR", 0))
    end = float(getattr(config, "THESIS_ALERT_WINDOW_END_HOUR", 24))
    if hour < start or hour > end:
        return

    tickers = getattr(config, "THESIS_ALERT_TICKERS", None) or []
    if not tickers:
        return

    def _k_watch(t: str) -> str:
        return f"thesis_watch_{t}"

    def _k_thesis(t: str) -> str:
        return f"thesis_thesis_{t}"

    def _k_emergency(t: str) -> str:
        return f"thesis_emergency_{t}"

    def _k_spike_watch(t: str) -> str:
        return f"spike_watch_{t}"

    def _k_spike_momentum(t: str) -> str:
        return f"spike_momentum_{t}"

    def _k_spike_breakout(t: str) -> str:
        return f"spike_breakout_{t}"

    cache = _load_alert_cache()
    fired = []
    cache_dirty = False

    for ticker in tickers:
        data = _fetch_price(ticker)
        if not data:
            continue
        chg = data.get("change_pct", 0)

        kw = _k_watch(ticker)
        kt = _k_thesis(ticker)
        ke = _k_emergency(ticker)
        suw = _k_spike_watch(ticker)
        sumo = _k_spike_momentum(ticker)
        sb = _k_spike_breakout(ticker)

        # ── Downside tiers ────────────────────────────────────────────────
        if chg <= tw:
            # Highest tier only when multiple thresholds apply; suppress lower tiers for the day.
            if chg <= te:
                if _already_alerted(cache, ke):
                    continue
                crit_reason = f"thesis_emergency:{ticker}:{chg:.2f}"
                if _should_skip_critical_dedup(ticker, crit_reason):
                    continue
                msg = _build_minerva_move_alert_text(
                    ticker, chg, f"🔴 DROP ALERT — {ticker}", "drop"
                ) + _telegram_price_drop_classification(ticker, chg)
                _send_thesis_plain(msg)
                _record_critical_dedup(ticker, crit_reason)
                _mark_alerted(cache, ke)
                _mark_alerted(cache, kt)
                _mark_alerted(cache, kw)
                cache_dirty = True
                fired.append(f"{ticker} EMERGENCY {chg:+.1f}%")
                _trigger_reflexivity(ticker, chg, data.get("price", 0))
                continue

            if chg <= tt:
                if _already_alerted(cache, kt) or _already_alerted(cache, ke):
                    continue
                msg = _build_minerva_move_alert_text(
                    ticker, chg, f"🟠 DROP ALERT — {ticker}", "drop"
                ) + _telegram_price_drop_classification(ticker, chg)
                _send_thesis_plain(msg)
                _mark_alerted(cache, kt)
                _mark_alerted(cache, kw)
                cache_dirty = True
                fired.append(f"{ticker} THESIS {chg:+.1f}%")
                _trigger_reflexivity(ticker, chg, data.get("price", 0))
                continue

            # watch tier
            if _already_alerted(cache, kw) or _already_alerted(cache, kt) or _already_alerted(cache, ke):
                continue
            msg = _build_minerva_move_alert_text(
                ticker, chg, f"🟡 DROP ALERT — {ticker}", "drop"
            ) + _telegram_price_drop_classification(ticker, chg)
            _send_thesis_plain(msg)
            _mark_alerted(cache, kw)
            cache_dirty = True
            fired.append(f"{ticker} WATCH {chg:+.1f}%")
            continue

        # ── Upside tiers ─────────────────────────────────────────────────
        if chg >= uw:
            if chg >= ub:
                if _already_alerted(cache, sb):
                    continue
                msg = _build_minerva_move_alert_text(
                    ticker, chg, f"🔴 SPIKE ALERT — {ticker}", "spike"
                )
                _send_thesis_plain(msg)
                _mark_alerted(cache, sb)
                _mark_alerted(cache, sumo)
                _mark_alerted(cache, suw)
                cache_dirty = True
                fired.append(f"{ticker} BREAKOUT {chg:+.1f}%")
                continue

            if chg >= um:
                if _already_alerted(cache, sumo) or _already_alerted(cache, sb):
                    continue
                msg = _build_minerva_move_alert_text(
                    ticker, chg, f"🟠 SPIKE ALERT — {ticker}", "spike"
                )
                _send_thesis_plain(msg)
                _mark_alerted(cache, sumo)
                _mark_alerted(cache, suw)
                cache_dirty = True
                fired.append(f"{ticker} MOMENTUM {chg:+.1f}%")
                continue

            if _already_alerted(cache, suw) or _already_alerted(cache, sumo) or _already_alerted(cache, sb):
                continue
            msg = _build_minerva_move_alert_text(
                ticker, chg, f"🟡 SPIKE ALERT — {ticker}", "spike"
            )
            _send_thesis_plain(msg)
            _mark_alerted(cache, suw)
            cache_dirty = True
            fired.append(f"{ticker} SPIKE {chg:+.1f}%")

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

    drop_watch = float(getattr(config, "ALERT_TIER_WATCH", -8))

    # ── Build ticker lists from state ──────────────────────────────────────
    held_tickers = []
    for score in state.get("god_scores", []):
        sig = score.get("signal", "")
        if sig not in ("LOCKED", "EXIT_ON_BOUNCE", "TARGET"):
            held_tickers.append(score["ticker"])

    exit_tickers = [e["ticker"] for e in state.get("exit_flags", [])]
    stops        = {s["ticker"]: s["stop_USD"] for s in state.get("active_stops", [])}

    # ── Check 1: Held positions at/ past watch-tier drop (config ALERT_TIER_WATCH) ─
    for ticker in held_tickers:
        if _already_alerted(cache, f"drop_{ticker}"):
            continue
        data = _fetch_price(ticker)
        if not data:
            continue
        chg  = data.get("change_pct", 0)
        price = data.get("price", 0)

        if chg <= drop_watch:
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
            ) + _telegram_price_drop_classification(ticker, chg).replace("&", "&amp;")
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

SEC_CACHE = os.path.join("data", "sec_cache.json")
# Danger-class news (🔴 NEWS ALERT) — per-ticker cooldown in sec_cache.json
CRITICAL_NEWS_COOLDOWN_SEC = 48 * 3600


def _price_bucket(price: float) -> int:
    if not price or price <= 0:
        return 0
    return int(float(price) / 5.0) * 5


def _critical_news_should_fire(
    critical_map: dict,
    ticker: str,
    headline_digest: str,
    price_bucket: int,
    filing_id: Optional[str] = None,
) -> bool:
    """
    Within 48h of the last critical-class alert for this ticker, suppress unless
    headline digest, price bucket, or SEC filing id changed (new information).
    """
    prev = critical_map.get(ticker)
    if not prev:
        return True
    now = time.time()
    if now - float(prev.get("ts") or 0) >= CRITICAL_NEWS_COOLDOWN_SEC:
        return True
    if prev.get("digest") != headline_digest:
        return True
    if int(prev.get("bucket", 0) or 0) != int(price_bucket):
        return True
    if filing_id and prev.get("filing_id") != filing_id:
        return True
    return False


def _mark_critical_news(
    critical_map: dict,
    ticker: str,
    headline_digest: str,
    price_bucket: int,
    filing_id: Optional[str] = None,
):
    critical_map[ticker] = {
        "ts": time.time(),
        "digest": headline_digest,
        "bucket": int(price_bucket),
        "filing_id": filing_id or "",
    }


_SEC_FEED = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=8-K&dateb=&owner=include"
    "&count=40&search_text=&output=atom"
)


def _load_sec_cache() -> dict:
    try:
        with open(SEC_CACHE, "r") as f:
            d = json.load(f)
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("seen", [])
    d.setdefault("critical_news", {})
    if not isinstance(d.get("critical_news"), dict):
        d["critical_news"] = {}
    return d


def _save_sec_cache(cache: dict):
    os.makedirs("data", exist_ok=True)
    with open(SEC_CACHE, "w") as f:
        json.dump(cache, f, indent=2)


def check_sec_filings():
    """Fetch SEC EDGAR 8-K feed every 10 min; alert if a THESIS_ALERT_TICKER filed."""
    import config

    tickers = [t.upper() for t in (getattr(config, "THESIS_ALERT_TICKERS", None) or [])]
    if not tickers:
        return

    try:
        resp = requests.get(
            _SEC_FEED,
            headers={"User-Agent": "Minerva/1.0 titan@gods-plan.io"},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"SEC feed fetch failed: {exc}")
        return

    cache = _load_sec_cache()
    seen: list = cache.setdefault("seen", [])
    alerts_sent = []

    import xml.etree.ElementTree as ET
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        logger.warning(f"SEC feed parse error: {exc}")
        return

    for entry in root.findall("atom:entry", ns):
        entry_id = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
        title    = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        updated  = (entry.findtext("atom:updated", default="", namespaces=ns) or "").strip()
        link_el  = entry.find("atom:link", ns)
        link     = link_el.get("href", "") if link_el is not None else ""

        if not entry_id or entry_id in seen:
            continue

        title_upper = title.upper()
        matched = [t for t in tickers if t in title_upper]
        if not matched:
            continue

        seen.append(entry_id)
        for ticker in matched:
            crit_reason = f"sec_8k:{entry_id}:{title[:200]}"
            if _should_skip_critical_dedup(ticker, crit_reason):
                continue
            msg = (
                f"📋 <b>SEC 8-K FILING — {ticker}</b>\n"
                f"📄 {title}\n"
                f"🕐 {updated}\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f'<a href="{link}">View filing on EDGAR</a>\n\n'
                f"<b>Review immediately — 8-Ks often move price.</b>"
            )
            _send_alert(msg)
            _record_critical_dedup(ticker, crit_reason)
            alerts_sent.append(f"SEC 8-K {ticker}")

    cache["seen"] = seen[-500:]
    _save_sec_cache(cache)

    if alerts_sent:
        logger.info(f"SEC filing alerts fired: {alerts_sent}")
    else:
        logger.debug("SEC filing check: no new filings for thesis tickers")
