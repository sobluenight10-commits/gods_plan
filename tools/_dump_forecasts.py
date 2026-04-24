import json, os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(BASE, "data", "forecasts.json"), encoding="utf-8") as f:
    d = json.load(f)
for tk, v in d["tickers"].items():
    e = v.get("ensemble") or {}
    models = list((v.get("models") or {}).keys())
    print(f"{tk:6s} ev={e.get('ev_pct'):>7}% es5={e.get('es5_pct'):>7}% "
          f"p_win={e.get('p_win')} src={e.get('source')} [{','.join(models)}]")
