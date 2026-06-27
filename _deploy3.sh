#!/usr/bin/env bash
set -u
cd /root/gods_plan || exit 1
echo "== PULL =="
git pull --no-edit origin master 2>&1 | tail -8
echo "== PUBLISH =="
cp OLYMPUS_UNIFIED.html /var/www/html/index.html && echo "index.html copied"
cp gem_inputs/core_satellite.json /var/www/html/ 2>/dev/null && echo "core_satellite copied" || true
echo "== EMBED PRELOAD =="
python3 tools/embed_dashboard_preload.py /var/www/html/index.html 2>&1 | tail -4 || echo "embed skipped"
echo "== RESTART =="
systemctl restart minerva && echo "minerva restarted"
sleep 2
echo "== VERIFY ENDPOINTS =="
for f in index.html point_a_scan.json active_actions.json forecasts.json; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/$f)
  echo "  $f -> $code"
done
echo "== VERIFY MARKERS =="
echo "  overlay marker: $(grep -c applyGemDowntrendOverlay /var/www/html/index.html)"
echo "  TSLA in GEM_DATA: $(grep -c '\"TSLA\": {grade' /var/www/html/index.html)"
echo "  1810 grade row remaining: $(grep -c '\"1810.HK\": {grade' /var/www/html/index.html)"
echo "DEPLOYED"
