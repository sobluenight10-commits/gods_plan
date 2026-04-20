"""Peek at risk_latest.json structure to see per-ticker risk dimensions."""
import json, os, sys
from pathlib import Path

p = "data/skill_results/risk_latest.json"
d = json.load(open(p, encoding="utf-8"))
res = d.get("results") or {}
print("tickers:", len(res))
for tk in ["NVDA", "UEC", "ARKQ", "PLTR", "URNM", "CCJ", "PL", "1810.HK"]:
    r = res.get(tk)
    if not r:
        print(f"{tk}: MISSING")
        continue
    print(f"\n=== {tk} ===")
    print(json.dumps(r, indent=2, default=str)[:1500])
