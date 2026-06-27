#!/bin/bash
cd /root/gods_plan
echo "== http codes =="
for f in active_actions.json forecasts.json strike_cards.json point_b_scan.json directives.json; do
  printf '%s ' "$f"; curl -s -o /dev/null -w '%{http_code}\n' "http://localhost/$f"
done
echo "== webroot files =="
ls -la /var/www/html/active_actions.json /var/www/html/forecasts.json 2>&1
echo "== active_actions structure =="
python3 - <<'PY'
import json,os
p="/var/www/html/active_actions.json"
if not os.path.exists(p):
    print("MISSING", p)
else:
    d=json.load(open(p))
    print("top keys:", list(d.keys())[:20])
    print("has actions:", bool(d.get("actions")), "n=", len(d.get("actions") or {}))
    print("drawdown_guardian.state:", (d.get("drawdown_guardian") or {}).get("state"))
    print("kernel.freeze_all:", (d.get("kernel") or {}).get("freeze_all"))
    print("liquidity_gate.vector_title:", (d.get("liquidity_gate") or {}).get("vector_title"))
    print("so_what_mandate:", str(d.get("so_what_mandate"))[:80])
PY
echo "== forecasts tickers =="
python3 - <<'PY'
import json,os
p="/var/www/html/forecasts.json"
if not os.path.exists(p):
    print("MISSING", p)
else:
    d=json.load(open(p))
    tk=d.get("tickers") or d.get("forecasts") or {}
    print("n forecasts:", len(tk))
    for t in ("TSLA","SPCX","SpaceX","NVDA","OKLO","NTLA"):
        print(" ", t, "in forecasts:", t in tk)
PY
