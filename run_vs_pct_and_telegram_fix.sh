#!/bin/bash
set -euo pipefail
cd /root/gods_plan

python3 << 'PYEOF'
"""
Three fixes in one pass:
1. vs% row: use upside_pct directly (not vs_current.ev_pct)
2. versus line: use upside_pct for vs1y
3. Telegram token: read from config.py (where the working token lives)
"""
import json, re, shutil
from pathlib import Path

HTML  = Path('/var/www/html/index.html')
STATE = Path('/root/gods_plan/data/dashboard_state.json')

# Fix 1+2: Patch gem_injector_v2.py to use correct key names
with open('/root/gods_plan/gem_injector_v2.py', 'r') as f:
    code = f.read()

# Fix vs_row: replace vs_current dict lookup with direct upside_pct
old_vs = "(proj.get(x,{}).get('vs_current') or {}).get('ev_pct')"
new_vs = "proj.get(x,{}).get('upside_pct')"
if old_vs in code:
    code = code.replace(old_vs, new_vs)
    print("Fix 1: vs_row key corrected")

# Fix ev_row vs_current lookup
old_ev = "vc = p.get('vs_current') if isinstance(p.get('vs_current'), dict) else {}\n        up = vc.get('ev_pct')"
new_ev = "up = p.get('upside_pct')"
if old_ev in code:
    code = code.replace(old_ev, new_ev)
    print("Fix 2: ev_row key corrected")

# Fix versus p5y key
old_p5 = "(proj.get('5y',{}).get('vs_entry') or {}).get('ev_pct')"
new_p5 = "proj.get('5y',{}).get('upside_pct')"
code = code.replace(old_p5, new_p5)

# Fix u1y from gem
old_u1 = "proj.get('1y',{}).get('vs_current',{}).get('ev_pct')"
new_u1 = "proj.get('1y',{}).get('upside_pct')"
code = code.replace(old_u1, new_u1)

with open('/root/gods_plan/gem_injector_v2.py', 'w') as f:
    f.write(code)
print("gem_injector_v2.py updated")

# Fix 3: Get correct Telegram token from config.py
import sys
sys.path.insert(0, '/root/gods_plan')
try:
    import config
    token   = getattr(config, 'TELEGRAM_BOT_TOKEN', None) or getattr(config, 'TELEGRAM_TOKEN', None)
    chat_id = getattr(config, 'TELEGRAM_CHAT_ID', None) or getattr(config, 'CHAT_ID', None)
    print(f"Token from config: {token[:20]}..." if token else "Token not in config")
    print(f"Chat ID: {chat_id}")
except Exception as e:
    print(f"Config import error: {e}")
    # Try reading directly
    with open('/root/gods_plan/config.py') as f:
        cfg = f.read()
    import re as re2
    t = re2.search(r'TELEGRAM[_A-Z]*TOKEN\s*=\s*["\']([^"\']+)["\']', cfg)
    c = re2.search(r'CHAT_ID\s*=\s*["\']?(\d+)["\']?', cfg)
    token   = t.group(1) if t else None
    chat_id = c.group(1) if c else None
    print(f"Token from file: {token[:20]}..." if token else "Token not found")
    print(f"Chat ID: {chat_id}")

if token:
    # Update .env with correct token
    with open('/root/gods_plan/.env', 'w') as f:
        f.write(f'OLYMPUS_BOT_TOKEN={token}\n')
        f.write(f'OLYMPUS_CHAT_ID={chat_id or "8738097837"}\n')
    print("✓ .env updated with correct token")

    # Test immediately
    import requests, os
    r = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': chat_id or '8738097837',
              'text': '🔱 MINERVA · Telegram reconnected · April 14 2026'}
    )
    print(f"Telegram test: {'PASS' if r.ok else 'FAIL'} {r.status_code}")
PYEOF

python3 gem_injector_v2.py

python3 -c "
with open('/var/www/html/index.html','r',encoding='utf-8') as f: h=f.read()
import re
pltr_idx = h.find('data-ticker=\\\"PLTR\\\"')
seg = h[pltr_idx:pltr_idx+3000]
has_vs_pct = re.search(r'-\\d+\\.\\d+%|[+]\\d+\\.\\d+%', seg)
print('vs% values found:', bool(has_vs_pct))
print('sc-worst count:', h.count('sc-worst'))
print('PASS' if h.count('sc-worst') > 15 else 'FAIL')
"

systemctl restart minerva

git add -A
git commit --trailer "Made-with: Cursor" -m "fix: vs% row key upside_pct, telegram token from config" || true
git push

echo "DONE"