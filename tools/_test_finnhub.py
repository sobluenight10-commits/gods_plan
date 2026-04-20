"""Verify Finnhub key + probe endpoints we'll wire in."""
from __future__ import annotations
import os, sys, json, time
import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Load .env
env = os.path.join(BASE, ".env")
if os.path.exists(env):
    for ln in open(env, encoding="utf-8"):
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

KEY = os.environ.get("FINNHUB_API_KEY", "")
if not KEY:
    print("NO KEY")
    sys.exit(2)
print("KEY ok (len", len(KEY), ")")

BASE_URL = "https://finnhub.io/api/v1"

def call(path, **params):
    params["token"] = KEY
    r = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
    print(f"\n>>> {path} {params.get('symbol','')} -> HTTP {r.status_code}")
    if r.ok:
        j = r.json()
        out = json.dumps(j, indent=2)[:800]
        print(out)
        return j
    else:
        print(r.text[:300])
        return None

# 1. Quote
call("/quote", symbol="NVDA")
time.sleep(1.2)

# 2. Company news (last 7d)
from datetime import date, timedelta
frm = (date.today() - timedelta(days=7)).isoformat()
to  = date.today().isoformat()
call("/company-news", symbol="NVDA", **{"from": frm, "to": to})
time.sleep(1.2)

# 3. Earnings calendar (next 30d)
call("/calendar/earnings", **{"from": to, "to": (date.today() + timedelta(days=30)).isoformat()})
time.sleep(1.2)

# 4. Analyst recommendation trends
call("/stock/recommendation", symbol="NVDA")
time.sleep(1.2)

# 5. Upgrade / downgrade feed
call("/stock/upgrade-downgrade", symbol="NVDA")
time.sleep(1.2)

# 6. EPS surprises (beats/misses history)
call("/stock/earnings", symbol="NVDA")
