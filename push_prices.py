"""
🔱 OLYMPUS — Live Price Pusher
Runs on Minerva server (5.189.176.185) via cron at 07:05 and 15:35 Berlin.
Fetches live prices for all matrix stocks → writes prices.json → pushes to GitHub.
Dashboard reads prices.json via raw.githubusercontent.com (no auth needed).

Cron entry (add with: crontab -e):
  5 7 * * 1-5  cd /root/gods_plan && python3 push_prices.py >> push_prices.log 2>&1
  35 15 * * 1-5 cd /root/gods_plan && python3 push_prices.py >> push_prices.log 2>&1
"""

import json
import os
import subprocess
import sys
from datetime import datetime
import pytz
import yfinance as yf

# ── Ticker universe ──────────────────────────────────────────────────────────
# format: (display_id_in_html, yfinance_ticker, currency)
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
    ("TMO",       "TMO",       "USD"),
    ("AMAT",      "AMAT",      "USD"),
    ("NTR",       "NTR",       "USD"),
    ("PKX",       "PKX",       "USD"),   # POSCO ADR
    ("MC.PA",     "MC.PA",     "EUR"),
    ("GEVO",      "GEVO",      "USD"),
    ("HUYA",      "HUYA",      "USD"),
    ("FCX",       "FCX",       "USD"),
    ("IAU",       "IAU",       "USD"),
    # Portfolio watchlist additions
    ("TSMC",      "TSM",       "USD"),   # alias
    ("ASML",      "ASML",      "EUR"),
    ("PL",        "PL",        "USD"),
    ("TMO",       "TMO",       "USD"),
]

# Deduplicate by display ID
seen = set()
TICKERS_DEDUPED = []
for entry in TICKERS:
    if entry[0] not in seen:
        seen.add(entry[0])
        TICKERS_DEDUPED.append(entry)


def fetch_prices():
    """Fetch current price and daily change for all tickers."""
    berlin = pytz.timezone("Europe/Berlin")
    now = datetime.now(berlin)
    prices = {}
    errors = []

    print(f"[{now.strftime('%Y-%m-%d %H:%M')} Berlin] Fetching {len(TICKERS_DEDUPED)} tickers...")

    for display_id, yf_ticker, currency in TICKERS_DEDUPED:
        try:
            t = yf.Ticker(yf_ticker)
            info = t.fast_info
            price = getattr(info, "last_price", None)
            prev_close = getattr(info, "previous_close", None)

            if price is None:
                # Fallback: history
                hist = t.history(period="2d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
                    prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price

            if price is None:
                errors.append(f"{yf_ticker}: no price")
                continue

            chg_pct = 0.0
            if prev_close and prev_close > 0:
                chg_pct = round((price - prev_close) / prev_close * 100, 2)

            prices[display_id] = {
                "price":      round(float(price), 2),
                "change_pct": chg_pct,
                "currency":   currency,
                "yf":         yf_ticker,
            }
            print(f"  ✅ {display_id}: {price:.2f} ({chg_pct:+.2f}%)")

        except Exception as e:
            errors.append(f"{yf_ticker}: {e}")
            print(f"  ❌ {display_id}: {e}")

    if errors:
        print(f"\nErrors ({len(errors)}): {', '.join(errors[:5])}")

    return prices, now.strftime("%Y-%m-%d %H:%M")


def write_json(prices, updated):
    """Write prices.json to repo root."""
    payload = {
        "updated": updated,
        "source":  "Minerva server · yfinance",
        "prices":  prices,
    }
    path = os.path.join(os.path.dirname(__file__), "prices.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\nWritten: {path} ({len(prices)} tickers)")
    return path


def push_to_github():
    """Git add → commit → push."""
    try:
        subprocess.run(["git", "add", "prices.json"], check=True, capture_output=True)
        result = subprocess.run(
            ["git", "commit", "-m", f"prices: auto-update {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
            capture_output=True, text=True
        )
        if "nothing to commit" in result.stdout:
            print("Git: nothing to commit (prices unchanged)")
            return
        subprocess.run(["git", "push"], check=True, capture_output=True)
        print("✅ Pushed to GitHub → dashboard will refresh within 60s")
    except subprocess.CalledProcessError as e:
        print(f"❌ Git push failed: {e.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    prices, updated = fetch_prices()
    if not prices:
        print("No prices fetched — aborting push")
        sys.exit(1)
    write_json(prices, updated)
    push_to_github()
    print(f"\n🔱 Done. {len(prices)} tickers live on dashboard.")
