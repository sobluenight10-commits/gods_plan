#!/usr/bin/env bash
# One-shot: apply FRED refresh + olympus_daily + grade diff + install FRED cron.
set -e
cd /root/gods_plan

echo '---FRED refresh---'
python3 - <<'PY'
from battle_rhythm import fetch_fred_liquidity
o = fetch_fred_liquidity() or {}
print('FRED ok:', o.get('net_liq_value') or o.get('net'))
PY

echo '---liquidity block---'
python3 - <<'PY'
import json
d = json.load(open('data/directives.json'))
liq = d.get('liquidity', {})
print('net:', liq.get('net_liq_value'), 'B')
print('zone:', liq.get('zone'))
print('last_updated:', liq.get('last_updated'))
print('velocity_7d_b:', liq.get('velocity_7d_b'))
print('corridor:', liq.get('corridor_status'))
PY

echo '---olympus_daily pipeline---'
python3 olympus_daily.py 2>&1 | tail -18

echo '---grade diff digest (dedupes per gem file)---'
python3 tools/gem_grade_diff.py 2>&1 | tail -5

echo '---install FRED cron (21:00 UTC = 23:00 Berlin summer, after 4:30pm ET release)---'
( crontab -l 2>/dev/null | grep -v 'fetch_fred_liquidity' ; \
  echo '0 21 * * * cd /root/gods_plan && /usr/bin/python3 -c "from battle_rhythm import fetch_fred_liquidity as f; f()" >> /var/log/olympus_fred.log 2>&1' \
) | crontab -
crontab -l | tail -8

echo '---redeploy dashboard---'
cp OLYMPUS_UNIFIED.html /var/www/html/index.html
systemctl restart minerva
echo DONE
