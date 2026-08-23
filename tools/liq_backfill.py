#!/usr/bin/env python3
"""liq_backfill.py — FRED API로 순유동성 5년+ 백필
net_liq = (WALCL − WTREGEN − RRPONTSYD)/1000 → $십억, 주간(수) 기준. 이벤트 마커 포함."""
import json, urllib.request, urllib.parse, os

FRED_KEY = os.environ.get("FRED_API_KEY", "0bc0ed228f83cb0853a6fa1f35b970d3")
def fred(sid, n=400):
    qs = urllib.parse.urlencode({"series_id": sid, "api_key": FRED_KEY, "file_type": "json",
                                 "sort_order": "desc", "limit": n,
                                 "observation_start": "2019-01-01"})
    url = "https://api.stlouisfed.org/fred/series/observations?" + qs
    data = json.loads(urllib.request.urlopen(url, timeout=20).read())
    return {o["date"]: float(o["value"]) for o in data.get("observations", []) if o.get("value") not in (None, ".")}

walcl, tga, rrp = fred("WALCL"), fred("WTREGEN"), fred("RRPONTSYD", 2000)
weds = sorted(set(walcl) & set(tga))
rrp_days = sorted(rrp)
snaps = []
for d in weds:
    rv = rrp.get(d)
    if rv is None:
        prev = [k for k in rrp_days if k <= d]
        rv = rrp[prev[-1]] if prev else 0.0
    snaps.append({"date": d, "net_liq": round((walcl[d]-tga[d]-rv)/1000, 1),
                  "reserves_b": None, "tga_b": round(tga[d]/1000, 1), "rrp_b": round(rv/1000, 1), "src": "FRED-backfill"})

p = "/root/gods_plan/data/liquidity_history.json"
cur = json.load(open(p))
have = {s["date"] for s in cur.get("snapshots", [])}
merged = [s for s in snaps if s["date"] not in have] + cur.get("snapshots", [])
merged.sort(key=lambda s: s["date"])
cur["snapshots"] = merged
cur["events"] = [
    {"date": "2020-03-23", "label": "코로나 무제한 QE"},
    {"date": "2022-03-16", "label": "금리인상 개시"},
    {"date": "2022-06-01", "label": "QT 개시"},
    {"date": "2023-03-13", "label": "SVB 붕괴·BTFP"},
    {"date": "2024-09-18", "label": "금리인하 개시"},
]
json.dump(cur, open(p, "w"))
print("snapshots:", len(merged), "·", merged[0]["date"], "→", merged[-1]["date"])
