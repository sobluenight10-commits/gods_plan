#!/bin/bash
set -euo pipefail

# Fix 1: Telegram env vars (permanent for all processes)
# Write to /etc/environment (read at login)
grep -v 'OLYMPUS_BOT_TOKEN\|OLYMPUS_CHAT_ID' /etc/environment > /tmp/env_clean.txt
echo 'OLYMPUS_BOT_TOKEN=8626741270:AAETXM3xCOztG7fP1LrDrziGNa6OsZWjb4o' >> /tmp/env_clean.txt
echo 'OLYMPUS_CHAT_ID=8738097837' >> /tmp/env_clean.txt
cp /tmp/env_clean.txt /etc/environment

# Also write to /etc/profile.d/ for all shell sessions
echo 'export OLYMPUS_BOT_TOKEN=8626741270:AAETXM3xCOztG7fP1LrDrziGNa6OsZWjb4o' > /etc/profile.d/olympus.sh
echo 'export OLYMPUS_CHAT_ID=8738097837' >> /etc/profile.d/olympus.sh
chmod 644 /etc/profile.d/olympus.sh

# Write to gods_plan/.env for direct Python loading
cd /root/gods_plan
echo 'OLYMPUS_BOT_TOKEN=8626741270:AAETXM3xCOztG7fP1LrDrziGNa6OsZWjb4o' > .env
echo 'OLYMPUS_CHAT_ID=8738097837' >> .env

# Export for current session
export OLYMPUS_BOT_TOKEN=8626741270:AAETXM3xCOztG7fP1LrDrziGNa6OsZWjb4o
export OLYMPUS_CHAT_ID=8738097837

# Fix output_factory.py to load .env as fallback
python3 << 'PYEOF'
with open('/root/gods_plan/output_factory.py', 'r') as f:
    content = f.read()

dotenv_block = '''import os
# Load .env file if env vars not set
def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())
_load_env()
'''

if '_load_env' not in content:
    if 'import os' in content:
        idx = content.find('import os')
        end = content.find('\n', idx) + 1
        content = content[:end] + dotenv_block.replace('import os\n', '') + content[end:]
    else:
        content = dotenv_block + content
    with open('/root/gods_plan/output_factory.py', 'w') as f:
        f.write(content)
    print('output_factory.py patched with .env loader')
else:
    print('already has .env loader')
PYEOF

# Test Telegram immediately
python3 -c "
import os, requests
# Load .env
env = open('/root/gods_plan/.env').read()
for line in env.strip().split('\\n'):
    k,v = line.split('=',1)
    os.environ[k] = v

token = os.environ.get('OLYMPUS_BOT_TOKEN')
chat  = os.environ.get('OLYMPUS_CHAT_ID')
print('Token:', token[:20] + '...' if token else 'MISSING')
r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
    json={'chat_id': chat, 'text': '🔱 MINERVA · Telegram LIVE · Pipeline test OK'})
print('Result:', 'PASS' if r.ok else 'FAIL', r.status_code)
"

# Fix 2: Run gem_injector_v2.py
cd /root/gods_plan
git pull

python3 -c "
import json
with open('data/dashboard_state.json') as f: d = json.load(f)
pltr = d['positions'].get('PLTR',{})
proj = pltr.get('projections',{})
print('PLTR projections:', list(proj.keys()))
print('1y worst:', proj.get('1y',{}).get('worst'))
print('1y normal:', proj.get('1y',{}).get('normal'))
print('1y bull:', proj.get('1y',{}).get('bull'))
"

python3 gem_injector_v2.py

python3 -c "
with open('/var/www/html/index.html','r',encoding='utf-8') as f: h=f.read()
worst = h.count('sc-worst')
armed = h.count('mx-act-armed') + h.count('mx-act-dipwatch')
versus = h.count('entry\\u21925y')
print(f'sc-worst rows: {worst} (target >15)')
print(f'Action updates: {armed}')
print(f'Versus rows: {versus}')
print('PASS' if worst > 15 else 'FAIL')
"

# Run full pipeline to confirm end-to-end
python3 olympus_daily.py

# Commit and restart
systemctl restart minerva
git add -A
git commit --trailer "Made-with: Cursor" -m "fix: telegram env, gem_injector_v2 depth-aware, full pipeline" || true
git push

echo "=== DONE — hard refresh http://5.189.176.185 ==="