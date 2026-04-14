"""Live Price Daemon — fetches every 60s, writes prices.json + plunge alerts."""
import json, time, os, requests
from datetime import datetime
import pytz
import yfinance as yf

TICKERS = [
    ("000660.KS", "000660.KS", "KRW"),
    ("TSM",       "TSM",       "USD"),
    ("PLTR",      "PLTR",      "USD"),
    ("1810.HK",   "1810.HK",   "HKD"),
    ("IONQ",      "IONQ",      "USD"),
    ("NVDA",      "NVDA",      "USD"),
    ("UEC",       "UEC",       "USD"),
    ("URNM",      "URNM",      "USD"),
    ("CCJ",       "CCJ",       "USD"),
    ("OKLO",      "OKLO",      "USD"),
    ("RKLB",      "RKLB",      "USD"),
    ("ASTS",      "ASTS",      "USD"),
    ("CRSP",      "CRSP",      "USD"),
    ("NTLA",      "NTLA",      "USD"),
    ("BEAM",      "BEAM",      "USD"),
    ("272210.KS", "272210.KS", "KRW"),
    ("KTOS",      "KTOS",      "USD"),
    ("LMT",       "LMT",       "USD"),
    ("NOC",       "NOC",       "USD"),
    ("RTX",       "RTX",       "USD"),
    ("GD",        "GD",        "USD"),
    ("AVAV",      "AVAV",      "USD"),
    ("ARKQ",      "ARKQ",      "USD"),
    ("BOTZ",      "BOTZ",      "USD"),
    ("COHR",      "COHR",      "USD"),
    ("VRT",       "VRT",       "USD"),
    ("TMO",       "TMO",      "USD"),
    ("AMAT",      "AMAT",      "USD"),
    ("NTR",       "NTR",       "USD"),
    ("PKX",       "PKX",       "USD"),
    ("MC.PA",     "MC.PA",     "EUR"),
    ("GEVO",      "GEVO",      "USD"),
    ("HUYA",      "HUYA",      "USD"),
    ("FCX",       "FCX",       "USD"),
    ("IAU",       "IAU",       "USD"),
    ("ASML",      "ASML",      "EUR"),
    ("PL",        "PL",        "USD"),
    ("CWEN",      "CWEN",      "USD"),
]

OUT = "/root/gods_plan/data/prices.json"
ALERT_STATE = "/root/gods_plan/data/plunge_alerts_today.json"
BERLIN = pytz.timezone("Europe/Berlin")
INTERVAL = 60

PLUNGE_THRESHOLD = -5.0
SPIKE_THRESHOLD = 8.0
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def _load_alerted_today():
    """Load set of (ticker, tier) already alerted today."""
    try:
        with open(ALERT_STATE) as f:
            data = json.load(f)
        if data.get("date") == datetime.now(BERLIN).strftime("%Y-%m-%d"):
            return set(tuple(x) for x in data.get("alerted", []))
    except Exception:
        pass
    return set()


def _save_alerted_today(alerted):
    os.makedirs(os.path.dirname(ALERT_STATE), exist_ok=True)
    with open(ALERT_STATE, "w") as f:
        json.dump({
            "date": datetime.now(BERLIN).strftime("%Y-%m-%d"),
            "alerted": list(alerted),
        }, f)


def _send_plunge_alert(ticker, price, change_pct, prev_close, direction):
    """Send immediate Telegram alert for significant price move."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        try:
            from dotenv import load_dotenv
            load_dotenv("/root/gods_plan/.env")
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            chat = os.getenv("TELEGRAM_CHAT_ID", "")
        except Exception:
            return
    else:
        token, chat = TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

    if not token or not chat:
        return

    if direction == "down":
        emoji = "\U0001F534"
        if change_pct <= -15:
            tier = "EMERGENCY"
        elif change_pct <= -10:
            tier = "THESIS DROP"
        else:
            tier = "WATCH"
        msg = (
            f"{emoji} PLUNGE ALERT: {ticker}\n"
            f"Price: ${price:.2f} ({change_pct:+.1f}%)\n"
            f"Prev close: ${prev_close:.2f}\n"
            f"Tier: {tier}\n"
            f"Detected by live_prices daemon (60s scan)"
        )
    else:
        emoji = "\U0001F7E2"
        tier = "SPIKE"
        msg = (
            f"{emoji} SPIKE ALERT: {ticker}\n"
            f"Price: ${price:.2f} ({change_pct:+.1f}%)\n"
            f"Prev close: ${prev_close:.2f}\n"
            f"Detected by live_prices daemon (60s scan)"
        )

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat, "text": msg}, timeout=10)
        print(f"  [ALERT] {ticker} {change_pct:+.1f}% -> Telegram sent", flush=True)
    except Exception as e:
        print(f"  [ALERT] Telegram send failed: {e}", flush=True)


def check_plunge_alerts(prices):
    """Check all prices for significant moves and alert once per ticker per day."""
    alerted = _load_alerted_today()

    for ticker, data in prices.items():
        chg = data.get("change_pct", 0)
        price = data.get("price", 0)
        prev = price / (1 + chg / 100) if chg != 0 else price

        if chg <= PLUNGE_THRESHOLD:
            key = (ticker, "down")
            if key not in alerted:
                _send_plunge_alert(ticker, price, chg, prev, "down")
                alerted.add(key)

        elif chg >= SPIKE_THRESHOLD:
            key = (ticker, "up")
            if key not in alerted:
                _send_plunge_alert(ticker, price, chg, prev, "up")
                alerted.add(key)

    _save_alerted_today(alerted)


def fetch_cycle():
    now = datetime.now(BERLIN)
    prices = {}
    errs = 0
    for did, ytk, cur in TICKERS:
        try:
            t = yf.Ticker(ytk)
            info = t.fast_info
            price = getattr(info, "last_price", None)
            prev = getattr(info, "previous_close", None)
            if price is None:
                h = t.history(period="2d")
                if not h.empty:
                    price = float(h["Close"].iloc[-1])
                    prev = float(h["Close"].iloc[-2]) if len(h) > 1 else price
            if price is None:
                errs += 1
                continue
            chg = round((price - prev) / prev * 100, 2) if prev and prev > 0 else 0.0
            prices[did] = {"price": round(float(price), 2), "change_pct": chg, "currency": cur}
        except Exception:
            errs += 1

    stamp = now.strftime("%Y-%m-%d %H:%M CET")
    payload = {"updated": stamp, "source": "live_prices daemon", "prices": prices}
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, OUT)
    print(f"[{stamp}] {len(prices)} tickers OK, {errs} errors", flush=True)

    check_plunge_alerts(prices)


if __name__ == "__main__":
    print("Live price daemon starting...", flush=True)
    while True:
        try:
            fetch_cycle()
        except Exception as e:
            print(f"Cycle error: {e}", flush=True)
        time.sleep(INTERVAL)
