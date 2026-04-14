#!/bin/bash
set -e
cd /root/gods_plan

echo "=== PULL ==="
git stash push -u -m 'pre-v3b' 2>/dev/null || true
git pull
git stash drop 2>/dev/null || true

echo "=== RUN GEM ==="
python3 run_gem_daily.py 2>&1 | tail -5

echo "=== RUN OLYMPUS ==="
python3 olympus_daily.py 2>&1 | head -5

echo "=== VERIFY ==="
python3 <<'PYEOF'
import json
d = json.load(open("data/dashboard_state.json"))
for t in ["ASML","000660.KS","1810.HK","MC.PA","NVDA","PLTR","NTR"]:
    p = d["positions"].get(t, {})
    proj = p.get("projections", {})
    u1y = proj.get("1y", {}).get("upside_pct")
    price = p.get("price", 0)
    grade = p.get("gem_grade", "?")
    has_sc = "W" in p.get("scenarios", {})
    u1s = f"{u1y:+.1f}%" if u1y is not None else "?"
    print(f"  {t:12s} price={price:>12.2f}  grade={grade}  1y_ev={u1s:>8s}  scenarios={'YES' if has_sc else 'NO'}")
PYEOF

echo "=== DEPLOY ==="
cp OLYMPUS_UNIFIED.html /var/www/html/index.html
mkdir -p /var/www/html/data
cp data/dashboard_state.json /var/www/html/data/dashboard_state.json
systemctl restart minerva
echo "DEPLOYED"
