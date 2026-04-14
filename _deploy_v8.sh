#!/bin/bash
set -e
cd /root/gods_plan

echo "=== PULL ==="
git reset --hard origin/master
git pull origin master

echo ""
echo "=== TEST RSS FETCH ==="
python3 -c "
import sys; sys.path.insert(0,'.')
from fetch_data import get_ranto28
posts = get_ranto28()
print(f'{len(posts)} blog posts within 48h:')
for p in posts:
    print(f'  [{p.get(\"date\",\"?\")}] {p.get(\"title\",\"\")[:60]}')
    print(f'    tickers={p.get(\"affected_tickers\",[])} sectors={p.get(\"sectors\",[])}')
"

echo ""
echo "=== RUN GEM DAILY ==="
timeout 120 python3 run_gem_daily.py 2>&1 | tail -10

echo ""
echo "=== RUN OLYMPUS DAILY ==="
timeout 120 python3 olympus_daily.py 2>&1

echo ""
echo "=== CHECK TELEGRAM BRIEF RANTO SECTION ==="
python3 -c "
import json
with open('data/dashboard_state.json') as f:
    state = json.load(f)
print('dashboard_state.json exists: OK')
print(f'positions: {len(state.get(\"positions\",{}))}')
"

echo ""
echo "=== CHECK BRIEF OUTPUT FOR RANTO ==="
python3 -c "
import sys; sys.path.insert(0,'.')
from fetch_data import get_all_data
from olympus_engine import run_engine
from output_factory import build_brief
data = get_all_data()
state = run_engine(data)
brief = build_brief(state)
# Find RANTO section
lines = brief.split('\n')
capture = False
for line in lines:
    if 'RANTO' in line.upper():
        capture = True
    if capture:
        print(line)
        if line.strip().startswith('🔭 MACRO') or line.strip().startswith('🚨'):
            break
"

echo ""
echo "=== DEPLOY TO WEB ==="
cp OLYMPUS_UNIFIED.html /var/www/html/index.html
cp data/dashboard_state.json /var/www/html/data/dashboard_state.json
echo "Files copied to web root"

echo ""
echo "=== DONE ==="
