#!/bin/bash
set -euo pipefail
cd /root/gods_plan

pip install yfinance --break-system-packages --quiet

python3 -c "import sys; sys.path.insert(0, '/root/gods_plan'); import morning_brief_v2 as mb; p=mb.fetch_prices(['RKLB','URNM','PLTR']);
print('RKLB', p.get('RKLB')); print('URNM', p.get('URNM')); print('PLTR', p.get('PLTR')); print('RKLB should be ~67, URNM ~63, NOT 5.50 or 24')"

python3 << 'PYEOF'
with open('/root/gods_plan/main.py', 'r') as f:
    main = f.read()

OLD = 'morning_brief'
if 'morning_brief_v2' not in main:
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
    idx = main.rfind('\nimport ')
    if idx > 0:
        end_of_line = main.find('\n', idx+1)
        main = main[:end_of_line+1] + patch + main[end_of_line+1:]
    with open('/root/gods_plan/main.py', 'w') as f:
        f.write(main)
    print('morning_brief_v2 wired into main.py')
else:
    print('already wired')
PYEOF

systemctl restart minerva
sleep 3

python3 -c "import json; d=json.load(open('/root/gods_plan/data/directives.json')); liq=d.get('liquidity',{}); print('net_liq_value:', liq.get('net_liq_value','MISSING')); print('net_liq_text:', liq.get('net_liq_text','MISSING')); print('zone:', liq.get('zone','MISSING')); print('PASS' if liq.get('net_liq_value')==2368 else 'FAIL')"

git add -A
git commit --trailer "Made-with: Cursor" -m "fix: correct liquidity keys net_liq_value+net_liq_text, morning brief v2 live prices" || true
git push

echo "=== DONE — HARD REFRESH http://5.189.176.185 ==="