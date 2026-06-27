#!/bin/bash
set -e
cd /root/gods_plan
echo "== git pull =="
git pull --no-edit 2>&1 | tail -2
echo "== publish dashboard + core/satellite =="
cp OLYMPUS_UNIFIED.html /var/www/html/index.html
cp gem_inputs/core_satellite.json /var/www/html/core_satellite.json
echo "== refresh active_actions into data/ for preload =="
cp -f /var/www/html/active_actions.json data/active_actions.json 2>/dev/null || true
echo "== embed preload into served index.html (repo file untouched) =="
python3 -c "from tools import embed_dashboard_preload as e; print(e.run('/var/www/html/index.html'))"
echo "== verify active_actions is inlined =="
grep -c '\"active_actions\"' /var/www/html/index.html || true
echo "== restart minerva =="
systemctl restart minerva && echo RESTARTED
echo "== endpoint codes =="
for f in index.html core_satellite.json active_actions.json; do printf '%s ' "$f"; curl -s -o /dev/null -w '%{http_code}\n' "http://localhost/$f"; done
