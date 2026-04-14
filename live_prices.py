"""Live Price Daemon — fetches every 60s, writes /var/www/html/data/prices.json"""
import json, time, os
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

OUT = "/var/www/html/data/prices.json"
BERLIN = pytz.timezone("Europe/Berlin")
INTERVAL = 60


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


if __name__ == "__main__":
    print("Live price daemon starting...", flush=True)
    while True:
        try:
            fetch_cycle()
        except Exception as e:
            print(f"Cycle error: {e}", flush=True)
        time.sleep(INTERVAL)
