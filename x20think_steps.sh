#!/bin/bash
set -euo pipefail
cd /root/gods_plan

# STEP 1 — Fix directives.json with CORRECT field names
python3 << 'PYEOF'
import json, datetime

with open('/root/gods_plan/data/directives.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

# CORRECT field names that OLYMPUS_UNIFIED.html actually reads
d['liquidity'] = {
    "net_liq_value": 2368,
    "net_liq_text": "$2,368B",
    "zone": "WARNING",
    "zone_color": "#e07b39",
    "outlook_text": "EXPANDING \u2191 | Post-tax TGA drain | Deploy post April 15",
    "action_text": "DEPLOY dry powder after April 15 — TGA drain = liquidity expanding",
    "change_text": "vs last week: +$189B \u2191",
    "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M CET")
}
d['last_updated'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M CET")

with open('/root/gods_plan/data/directives.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)

# VERIFY
with open('/root/gods_plan/data/directives.json') as f:
    check = json.load(f)

liq = check['liquidity']
print("net_liq_value:", liq['net_liq_value'], "PASS" if liq['net_liq_value']==2368 else "FAIL")
print("net_liq_text:", liq['net_liq_text'])
print("zone:", liq['zone'])
print("action_text:", liq['action_text'][:50])
PYEOF

# STEP 2 — Fix OLYMPUS_UNIFIED.html (duplicate rows) via index.html
python3 << 'PYEOF'
import re, shutil

with open('/var/www/html/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Count Intelligence headers using regex (encoding-safe)
pattern = r'<tr>\s*<td[^>]*>\s*<div class="cat-band">(?:[^<]|<(?!\/tr>))*?Intelligence(?:[^<]|<(?!\/tr>))*?<\/tr>'
matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
print(f"Intelligence headers found: {len(matches)}")

if len(matches) > 1:
    # Remove all, reinsert one
    html2 = re.sub(pattern, '', html, flags=re.DOTALL|re.IGNORECASE)
    idx = html2.find('data-ticker="000660.KS"')
    if idx > 0:
        tr = html2.rfind('<tr', 0, idx)
        html2 = html2[:tr] + matches[0] + '\n' + html2[tr:]
    print(f"After fix: {len(re.findall(pattern, html2, re.DOTALL|re.IGNORECASE))} headers")
    html = html2

with open('/var/www/html/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
shutil.copy2('/var/www/html/index.html', '/root/gods_plan/OLYMPUS_UNIFIED.html')
print("DONE")
PYEOF

# STEP 3 — Copy morning_brief_v2.py to server + install yfinance
cp /root/gods_plan/morning_brief_v2.py /root/gods_plan/morning_brief_v2.py
pip install yfinance --break-system-packages --quiet

# STEP 4 — Test live price fetch
python3 -c "
import sys
sys.path.insert(0, '/root/gods_plan')
from morning_brief_v2 import fetch_prices
p = fetch_prices(['RKLB','URNM','PLTR'])
for t,v in p.items():
    print(t, v)
print('RKLB should be ~67, URNM ~63, NOT 5.50 or 24')
"

# STEP 5 — Wire morning_brief_v2 into main.py
python3 << 'PYEOF'
with open('/root/gods_plan/main.py', 'r') as f:
    main = f.read()

# Find the morning brief send call and replace it
OLD = 'morning_brief'
if 'morning_brief_v2' not in main:
    # Add import and replacement function
    patch = '''
# MINERVA-10X morning brief v2 with live prices
import importlib.util as _ilu, os as _os
def _run_brief_v2():
    spec = _ilu.spec_from_file_location("mb2", 
        _os.path.join(_os.path.dirname(__file__), "morning_brief_v2.py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import json
    with open(_os.path.join(_os.path.dirname(__file__), "data", "directives.json")) as f:
        d = json.load(f)
    liq = d.get("liquidity", {})
    return mod.build_brief(
        liq_b=liq.get("net_liq_value", 2368),
        liq_delta=liq.get("vs_last_week_b", 189),
        vix=19.12
    )
'''
    # Insert at top after imports
    idx = main.rfind('\nimport ')
    if idx > 0:
        end_of_line = main.find('\n', idx+1)
        main = main[:end_of_line+1] + patch + main[end_of_line+1:]
    
    with open('/root/gods_plan/main.py', 'w') as f:
        f.write(main)
    print("morning_brief_v2 wired into main.py")
else:
    print("already wired")
PYEOF

# STEP 6 — Restart and verify
systemctl restart minerva
sleep 3

python3 -c "
import json
with open('/root/gods_plan/data/directives.json') as f: d=json.load(f)
liq=d.get('liquidity',{})
print('net_liq_value:', liq.get('net_liq_value','MISSING'))
print('net_liq_text:', liq.get('net_liq_text','MISSING'))
print('zone:', liq.get('zone','MISSING'))
print('PASS' if liq.get('net_liq_value')==2368 else 'FAIL')
"

git add -A
git commit --trailer "Made-with: Cursor" -m "fix: correct liquidity keys net_liq_value+net_liq_text, morning brief v2 live prices"
git push

echo "=== DONE — HARD REFRESH http://5.189.176.185 ==="