"""OLYMPUS Correlation Engine — 60-second cross-referencing daemon.

Reads live prices every cycle and cross-references with:
  - GEM grades & projections
  - Risk screener scores
  - Financial fundamentals
  - News sentiment
  - Previous price snapshots (momentum)

Detects correlated danger/opportunity patterns and fires Telegram alerts.

Runs as a systemd service alongside live_prices.py.
"""
import json
import os
import time
import math
import requests
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

import pytz

BERLIN = pytz.timezone("Europe/Berlin")
BASE = Path("/root/gods_plan")
DATA = BASE / "data"
PRICES_FILE = DATA / "prices.json"
CORR_STATE_FILE = DATA / "correlation_state.json"
CORR_LOG_FILE = DATA / "correlation_alerts.json"

SKILL_DIR = DATA / "skill_results"
GEM_DIR = BASE / "gem_results"

INTERVAL = 60

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def _watchlist_only_from_config():
    """
    Tickers in THESIS_ALERT_TICKERS but not in PORTFOLIO holdings — matches
    Master Matrix watchlist (no broker core position). Used to soften EXIT copy.
    """
    try:
        from config import PORTFOLIO, THESIS_ALERT_TICKERS

        held = set()
        for _bk, lst in PORTFOLIO.items():
            for p in lst:
                held.add(p["ticker"])
        return frozenset(t for t in THESIS_ALERT_TICKERS if t not in held)
    except Exception:
        return frozenset()


WATCHLIST_ONLY_TICKERS = _watchlist_only_from_config()


SECTOR_MAP = {
    "PLTR": "Intelligence", "TSM": "Intelligence", "000660.KS": "Intelligence",
    "NVDA": "Intelligence", "1810.HK": "Intelligence", "ASML": "Infra",
    "AMAT": "Infra", "COHR": "Infra", "VRT": "Infra",
    "UEC": "Energy", "URNM": "Energy", "CCJ": "Energy", "OKLO": "Energy",
    "UUUU": "Energy", "CWEN": "Energy",
    "RKLB": "Space", "PL": "Space", "ASTS": "Space",
    "BEAM": "Bio", "NTLA": "Bio", "CRSP": "Bio", "TMO": "Bio",
    "KTOS": "Defense", "272210.KS": "Defense", "AVAV": "Defense",
    "ARKQ": "Robotics", "BOTZ": "Robotics",
    "NTR": "Global", "FCX": "Global", "GEVO": "Global",
    "MC.PA": "Luxury", "IAU": "Tactical", "PKX": "Global",
    "HUYA": "Other",
}


def _load_env():
    global TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    if not TELEGRAM_TOKEN:
        try:
            from dotenv import load_dotenv
            load_dotenv(BASE / ".env")
            TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
            TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
        except Exception:
            pass


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _load_latest_file(directory, prefix):
    try:
        files = sorted(
            [f for f in os.listdir(directory) if f.startswith(prefix) and f.endswith(".json")],
            reverse=True
        )
        if files:
            return _load_json(os.path.join(directory, files[0]))
    except Exception:
        pass
    return None


def _send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        print(f"  [CORR] Telegram failed: {e}", flush=True)


def load_all_skills():
    """Load the latest results from all skill engines."""
    gem = _load_latest_file(str(GEM_DIR), "gem_")
    risk = _load_latest_file(str(SKILL_DIR), "risk_")
    fund = _load_latest_file(str(SKILL_DIR), "fundamentals_")
    sent = _load_latest_file(str(SKILL_DIR), "sentiment_")
    return {
        "gem": gem,
        "risk": risk,
        "fundamentals": fund,
        "sentiment": sent,
    }


def load_state():
    """Load persistent correlation state (price history, alert cooldowns)."""
    data = _load_json(str(CORR_STATE_FILE))
    if data and data.get("date") == datetime.now(BERLIN).strftime("%Y-%m-%d"):
        return data
    return {
        "date": datetime.now(BERLIN).strftime("%Y-%m-%d"),
        "price_history": {},
        "alerts_sent": {},
        "sector_alerts": {},
    }


def save_state(state):
    state["date"] = datetime.now(BERLIN).strftime("%Y-%m-%d")
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = str(CORR_STATE_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, str(CORR_STATE_FILE))


def _alert_cooldown_ok(state, alert_key, cooldown_minutes=30):
    """Prevent alert spam — at least N minutes between same alert type."""
    last = state["alerts_sent"].get(alert_key)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return (datetime.now(BERLIN) - last_dt).total_seconds() > cooldown_minutes * 60
    except Exception:
        return True


def _mark_alerted(state, alert_key):
    state["alerts_sent"][alert_key] = datetime.now(BERLIN).isoformat()


def _build_gem_map(gem_data):
    """Build {ticker: gem_result} from GEM daily output."""
    if not gem_data:
        return {}
    return {r["ticker"]: r for r in gem_data.get("results", [])}


def _build_risk_map(risk_data):
    """Build {ticker: risk_result} from risk screener output."""
    if not risk_data:
        return {}
    return risk_data.get("results", {})


def _build_fund_map(fund_data):
    if not fund_data:
        return {}
    return fund_data.get("results", {})


def _build_sent_map(sent_data):
    if not sent_data:
        return {}, {}
    return sent_data.get("ticker_news", {}), sent_data.get("sector_sentiment", {})


def track_price_momentum(state, prices):
    """Record price snapshots for momentum detection."""
    now = datetime.now(BERLIN).strftime("%H:%M")
    hist = state.setdefault("price_history", {})
    for ticker, data in prices.items():
        if ticker not in hist:
            hist[ticker] = []
        hist[ticker].append({
            "time": now,
            "price": data.get("price", 0),
            "change_pct": data.get("change_pct", 0),
        })
        # Keep last 60 snapshots (~1 hour)
        if len(hist[ticker]) > 60:
            hist[ticker] = hist[ticker][-60:]


def detect_correlated_signals(state, prices, skills):
    """Core correlation logic. Returns list of alert dicts."""
    alerts = []
    gem_map = _build_gem_map(skills["gem"])
    risk_map = _build_risk_map(skills["risk"])
    fund_map = _build_fund_map(skills["fundamentals"])
    tk_sent, sec_sent = _build_sent_map(skills["sentiment"])

    # ── PATTERN 1: High-risk stock dropping (DANGER CONVERGENCE) ─────────
    for ticker, pdata in prices.items():
        chg = pdata.get("change_pct", 0)
        risk = risk_map.get(ticker, {})
        risk_level = risk.get("risk_level", "UNKNOWN")
        risk_avg = risk.get("avg_risk", 0)
        gem = gem_map.get(ticker, {})
        grade = gem.get("grading", {}).get("grade", "?")

        # PATTERN 1a: CRITICAL risk + dropping > 3% = DANGER
        if risk_level == "CRITICAL" and chg <= -3.0:
            key = f"danger_{ticker}"
            if _alert_cooldown_ok(state, key, 60):
                crits = ", ".join(risk.get("critical_risks", [])[:3])
                alerts.append({
                    "type": "DANGER_CONVERGENCE",
                    "ticker": ticker,
                    "severity": "CRITICAL",
                    "msg": (
                        f"\U0001F6A8 <b>DANGER CONVERGENCE: {ticker}</b>\n"
                        f"Price: {chg:+.1f}% today\n"
                        f"Risk: {risk_level} (avg {risk_avg:.1f}/9)\n"
                        f"Critical: {crits}\n"
                        f"GEM Grade: {grade}\n"
                        f"<i>High risk + price decline = correlated danger</i>"
                    ),
                    "key": key,
                })

        # PATTERN 1b: LOW grade (D/F) + any drop > 2% = EXIT SIGNAL
        if grade in ("D", "F") and chg <= -2.0:
            key = f"exit_{ticker}"
            if _alert_cooldown_ok(state, key, 120):
                wl = ticker in WATCHLIST_ONLY_TICKERS
                foot = (
                    "<i>Watchlist only (no core PORTFOLIO line) — pass on adding / "
                    "trim spec thesis; not a full position exit.</i>"
                    if wl
                    else "<i>Low grade + declining price = consider exit</i>"
                )
                title = (
                    f"\u26A0\uFE0F <b>EXIT / PASS SIGNAL: {ticker}</b>"
                    if wl
                    else f"\u26A0\uFE0F <b>EXIT SIGNAL: {ticker}</b>"
                )
                alerts.append({
                    "type": "EXIT_SIGNAL",
                    "ticker": ticker,
                    "severity": "HIGH",
                    "msg": (
                        f"{title}\n"
                        f"GEM Grade: {grade} + Price: {chg:+.1f}%\n"
                        f"Risk: {risk_level}\n"
                        f"{foot}"
                    ),
                    "key": key,
                })

        # PATTERN 1c: Accelerating decline (momentum)
        hist = state.get("price_history", {}).get(ticker, [])
        if len(hist) >= 5:
            recent_5 = [h["change_pct"] for h in hist[-5:]]
            # If every snapshot shows worsening decline
            if all(r < recent_5[0] - 0.5 for r in recent_5[1:]) and chg <= -4.0:
                key = f"accel_{ticker}"
                if _alert_cooldown_ok(state, key, 60):
                    alerts.append({
                        "type": "ACCELERATING_DECLINE",
                        "ticker": ticker,
                        "severity": "HIGH",
                        "msg": (
                            f"\U0001F4C9 <b>ACCELERATING DECLINE: {ticker}</b>\n"
                            f"Current: {chg:+.1f}%\n"
                            f"5-min trend: {recent_5[0]:+.1f}% \u2192 {recent_5[-1]:+.1f}%\n"
                            f"<i>Price dropping with increasing speed</i>"
                        ),
                        "key": key,
                    })

    # ── PATTERN 2: Sector-wide weakness ──────────────────────────────────
    sector_changes = defaultdict(list)
    for ticker, pdata in prices.items():
        sector = SECTOR_MAP.get(ticker)
        if sector:
            sector_changes[sector].append({
                "ticker": ticker,
                "change": pdata.get("change_pct", 0),
            })

    for sector, members in sector_changes.items():
        if len(members) < 2:
            continue
        avg_chg = sum(m["change"] for m in members) / len(members)
        declining = [m for m in members if m["change"] < -2.0]

        # If sector average is strongly negative AND majority declining
        if avg_chg <= -3.5 and len(declining) >= len(members) * 0.66:
            key = f"sector_{sector}"
            if _alert_cooldown_ok(state, key, 240):
                tickers_str = ", ".join(
                    f"{m['ticker']}({m['change']:+.1f}%)" for m in
                    sorted(members, key=lambda x: x["change"])[:5]
                )
                sent_signal = sec_sent.get(sector, {}).get("signal", "N/A")
                alerts.append({
                    "type": "SECTOR_WEAKNESS",
                    "sector": sector,
                    "severity": "HIGH",
                    "msg": (
                        f"\U0001F30A <b>SECTOR WEAKNESS: {sector}</b>\n"
                        f"Avg change: {avg_chg:+.1f}%\n"
                        f"Declining: {tickers_str}\n"
                        f"Sentiment: {sent_signal}\n"
                        f"<i>{len(declining)}/{len(members)} stocks dropping</i>"
                    ),
                    "key": key,
                })

    # ── PATTERN 3: Fundamental deterioration + price drop ────────────────
    for ticker, pdata in prices.items():
        chg = pdata.get("change_pct", 0)
        if chg > -2.0:
            continue
        fund = fund_map.get(ticker, {})
        margins = fund.get("margins", {})
        rev = fund.get("revenue", {})
        rev_trend = rev.get("trend", "")
        margin_trend = margins.get("operating", {}).get("trend", "")

        if rev_trend == "declining" and margin_trend == "declining" and chg <= -3.0:
            key = f"fundweak_{ticker}"
            if _alert_cooldown_ok(state, key, 180):
                alerts.append({
                    "type": "FUNDAMENTAL_DETERIORATION",
                    "ticker": ticker,
                    "severity": "MODERATE",
                    "msg": (
                        f"\U0001F4CA <b>FUNDAMENTALS WEAKENING: {ticker}</b>\n"
                        f"Revenue trend: {rev_trend}\n"
                        f"Margin trend: {margin_trend}\n"
                        f"Price: {chg:+.1f}% today\n"
                        f"<i>Declining fundamentals confirmed by price action</i>"
                    ),
                    "key": key,
                })

    # ── PATTERN 4: Bearish sentiment + price weakness ────────────────────
    for ticker, pdata in prices.items():
        chg = pdata.get("change_pct", 0)
        if chg > -2.0:
            continue
        t_sent = tk_sent.get(ticker, {})
        net = t_sent.get("net_sentiment", 0)
        if net <= -2:
            key = f"sentbear_{ticker}"
            if _alert_cooldown_ok(state, key, 120):
                headlines = t_sent.get("headlines", [])[:2]
                hl_str = "\n".join(f"  \u2022 {h}" for h in headlines) if headlines else "  (no headlines)"
                alerts.append({
                    "type": "NEGATIVE_CONVERGENCE",
                    "ticker": ticker,
                    "severity": "MODERATE",
                    "msg": (
                        f"\U0001F4F0 <b>BEARISH CONVERGENCE: {ticker}</b>\n"
                        f"Sentiment: {net} (bearish)\n"
                        f"Price: {chg:+.1f}%\n"
                        f"Headlines:\n{hl_str}\n"
                        f"<i>Negative news + price decline = sentiment-confirmed drop</i>"
                    ),
                    "key": key,
                })

    # ── PATTERN 5: Opportunity detection (positive convergence) ──────────
    for ticker, pdata in prices.items():
        chg = pdata.get("change_pct", 0)
        gem = gem_map.get(ticker, {})
        grade = gem.get("grading", {}).get("grade", "?")
        u5 = gem.get("grading", {}).get("upside_5y_pct", 0)
        risk = risk_map.get(ticker, {})
        risk_level = risk.get("risk_level", "UNKNOWN")

        # A-grade stock dipping > 3% with manageable risk = potential buy
        if grade in ("A", "A+", "S") and chg <= -3.0 and risk_level in ("LOW", "MODERATE"):
            key = f"buydip_{ticker}"
            if _alert_cooldown_ok(state, key, 180):
                alerts.append({
                    "type": "BUY_DIP_SIGNAL",
                    "ticker": ticker,
                    "severity": "INFO",
                    "msg": (
                        f"\U0001F7E2 <b>DIP OPPORTUNITY: {ticker}</b>\n"
                        f"GEM Grade: {grade} | 5Y upside: {u5:+.0f}%\n"
                        f"Today: {chg:+.1f}% | Risk: {risk_level}\n"
                        f"<i>High-grade stock dipping with manageable risk</i>"
                    ),
                    "key": key,
                })

    return alerts


def _alerts_allowed_now() -> bool:
    """Weekday + extended US window only — kills 24/7 weekend/overnight spam."""
    try:
        from tools.alert_gate import noise_allowed
        return noise_allowed()
    except Exception:
        # Fallback: weekday 13:30–23:30 Berlin
        now = datetime.now(BERLIN)
        if now.weekday() >= 5:
            return False
        h = now.hour + now.minute / 60.0
        return 13.5 <= h <= 23.5


def _enrich_with_why(alert: dict) -> str:
    """Append a causal diagnosis + action so the alert is linked to a decision,
    not just an exposed result (Lesson #09). Best-effort; never blocks the send."""
    try:
        from tools.why_engine import diagnose_and_record, format_card
        subject = alert.get("ticker") or alert.get("sector") or ""
        # Strip HTML tags from the alert body to feed the engine clean text.
        import re as _re
        body = _re.sub(r"<[^>]+>", "", alert.get("msg", ""))
        card = diagnose_and_record(
            result_text=body[:400],
            ticker=alert.get("ticker"),
            context=f"Correlation-engine alert type: {alert.get('type')} · subject: {subject}",
        )
        return "\n\n" + format_card(card)
    except Exception as exc:  # noqa: BLE001
        print(f"  [CORR] why-engine enrich failed: {exc}", flush=True)
        return ""


def run_cycle(state, skills):
    """Single correlation cycle."""
    now = datetime.now(BERLIN)
    prices_data = _load_json(str(PRICES_FILE))
    if not prices_data:
        print(f"[{now:%H:%M}] No prices.json", flush=True)
        return state

    prices = prices_data.get("prices", {})
    if not prices:
        print(f"[{now:%H:%M}] Empty prices", flush=True)
        return state

    track_price_momentum(state, prices)

    # GOD directive (Jun 27 2026): no autonomous Telegram on weekends, and no
    # correlation spam outside the US session. Keep tracking momentum (cheap),
    # but do not detect/send alerts when the gate is closed.
    if not _alerts_allowed_now():
        if now.minute % 30 == 0:
            print(f"[{now:%H:%M}] Gate closed (weekend/off-hours) — no alerts", flush=True)
        save_state(state)
        return state

    alerts = detect_correlated_signals(state, prices, skills)

    if alerts:
        for a in alerts:
            msg = a["msg"]
            # Lesson #09: every alert must carry its cause + the action it implies.
            if a.get("type") in ("SECTOR_WEAKNESS", "EXIT_SIGNAL", "DANGER_CONVERGENCE"):
                msg = msg + _enrich_with_why(a)
            _send_telegram(msg)
            _mark_alerted(state, a["key"])
            print(f"  [ALERT] {a['type']}: {a.get('ticker', a.get('sector', '?'))}", flush=True)

        log = _load_json(str(CORR_LOG_FILE)) or {"alerts": []}
        for a in alerts:
            log["alerts"].append({
                "timestamp": now.isoformat(),
                "type": a["type"],
                "ticker": a.get("ticker", ""),
                "severity": a["severity"],
            })
        log["alerts"] = log["alerts"][-500:]
        with open(str(CORR_LOG_FILE), "w") as f:
            json.dump(log, f)
    else:
        if now.minute % 10 == 0:
            print(f"[{now:%H:%M}] Correlation scan: {len(prices)} tickers, no alerts", flush=True)

    save_state(state)
    return state


def main():
    _load_env()
    print("OLYMPUS Correlation Engine starting...", flush=True)
    print(f"  Interval: {INTERVAL}s", flush=True)
    print(f"  Prices: {PRICES_FILE}", flush=True)

    skills = load_all_skills()
    skills_loaded = {k: v is not None for k, v in skills.items()}
    print(f"  Skills loaded: {skills_loaded}", flush=True)

    state = load_state()

    # Reload skills every 15 minutes to pick up daily runs
    last_skill_reload = time.time()
    SKILL_RELOAD_INTERVAL = 900

    while True:
        try:
            if time.time() - last_skill_reload > SKILL_RELOAD_INTERVAL:
                skills = load_all_skills()
                last_skill_reload = time.time()

            state = run_cycle(state, skills)
        except Exception as e:
            print(f"[CORR] Cycle error: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
