"""Quick on-server lookup helper — pulls CCJ across all signal layers."""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _safe_load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"_error": str(e), "_path": path}


def _show(label, payload):
    print(f"--- {label} ---")
    print(json.dumps(payload, indent=2, default=str)[:1500])
    print()


sc = _safe_load(os.path.join(BASE, "data", "strike_cards.json"))
pool = (sc.get("cards") or []) + (sc.get("shortlist") or [])
ccj_card = next((c for c in pool if c.get("ticker") == "CCJ"), None) or {
    "note": "CCJ not in strike_cards (status=watchlist, no held position to score)"
}
_show("STRIKE CARD", ccj_card)

fc = _safe_load(os.path.join(BASE, "data", "forecasts.json"))
fc_ccj = (fc.get("tickers") or {}).get("CCJ") or fc.get("CCJ") or {
    "note": "no CCJ forecast"
}
_show("FORECAST", fc_ccj)

ops = _safe_load(os.path.join(BASE, "data", "premium_score.json"))
ops_ccj = ops.get("CCJ") or {"note": "no CCJ ops"}
_show("OPS", ops_ccj)

gg = _safe_load(os.path.join(BASE, "data", "gem_grades.json"))
gg_ccj = None
if isinstance(gg, dict):
    gg_ccj = gg.get("CCJ") or next(
        (g for g in (gg.get("grades") or []) if g.get("ticker") == "CCJ"), None
    )
elif isinstance(gg, list):
    gg_ccj = next((g for g in gg if g.get("ticker") == "CCJ"), None)
_show("GEM GRADE", gg_ccj or {"note": "no CCJ grade"})

dp = _safe_load(os.path.join(BASE, "data", "deploy_plan.json"))
dp_picks = (dp.get("picks") or []) + (dp.get("ranked") or []) + (dp.get("rejected") or [])
dp_ccj = next((p for p in dp_picks if p.get("ticker") == "CCJ"), {"note": "not in deploy plan"})
_show("DEPLOY PLAN", dp_ccj)
