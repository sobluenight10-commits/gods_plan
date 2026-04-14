#!/bin/bash
set -e
cd /root/gods_plan

echo "=== PULL ==="
git stash push -u -m 'pre-v3' 2>/dev/null || true
git pull
git stash drop 2>/dev/null || true

echo "=== PATCH run_gem_daily.py: use LIVE prices ==="
python3 <<'PYEOF'
import re
path = "run_gem_daily.py"
text = open(path).read()

# Check if already patched
if "LIVE PRICE OVERRIDE" not in text:
    # Add live price fetch before the evaluation loop
    old = "    for pos in positions:"
    new = """    # LIVE PRICE OVERRIDE — never use stale hardcoded prices
    try:
        import yfinance as yf
        all_tickers = [p["ticker"] for p in positions]
        print(f"Fetching live prices for {len(all_tickers)} tickers...")
        for p in positions:
            try:
                h = yf.Ticker(p["ticker"]).history(period="2d")
                if not h.empty:
                    live = round(float(h["Close"].iloc[-1]), 4)
                    if live > 0:
                        p["current_price"] = live
            except Exception:
                pass
        print(f"Live prices updated")
    except ImportError:
        print("WARNING: yfinance not available, using input prices")

    for pos in positions:"""
    text = text.replace(old, new, 1)
    open(path, "w").write(text)
    print("  run_gem_daily.py patched with LIVE PRICE OVERRIDE")
else:
    print("  run_gem_daily.py already patched")
PYEOF

echo "=== RUN GEM with LIVE prices ==="
python3 run_gem_daily.py 2>&1 | tail -8

echo "=== RUN OLYMPUS DAILY ==="
python3 olympus_daily.py 2>&1 | head -6

echo "=== VERIFY KEY TICKERS ==="
python3 <<'PYEOF'
import json
d = json.load(open("data/dashboard_state.json"))
for t in ["ASML","NTR","NVDA","PLTR","TMO","000660.KS"]:
    p = d["positions"].get(t, {})
    proj = p.get("projections", {})
    u1y = proj.get("1y", {}).get("upside_pct")
    u5y = proj.get("5y", {}).get("upside_pct")
    ev_1y = proj.get("1y", {}).get("ev")
    sc = p.get("scenarios", {})
    has_sc = "W" in sc
    u1s = f"{u1y:+.1f}%" if u1y is not None else "?"
    u5s = f"{u5y:+.1f}%" if u5y is not None else "?"
    print(f"  {t:12s} price=${p.get('price',0):>10.2f}  grade={p.get('gem_grade','?')}  1y={u1s:>8s}  5y={u5s:>8s}  ev_1y={ev_1y}  scenarios={'YES' if has_sc else 'NO'}")
PYEOF

echo "=== DEPLOY ==="
cp OLYMPUS_UNIFIED.html /var/www/html/index.html
mkdir -p /var/www/html/data
cp data/dashboard_state.json /var/www/html/data/dashboard_state.json
systemctl restart minerva
echo "DEPLOYED"
