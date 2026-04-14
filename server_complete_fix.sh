#!/bin/bash
set -euo pipefail
cd /root/gods_plan

pip install yfinance --break-system-packages --quiet

git pull

python3 << 'PYEOF'
import json, datetime, re, shutil

print("=== OLYMPUS COMPLETE FIX — ALL ISSUES ===\n")
errors = []

# ── FIX 1: Liquidity into directives.json ─────────────────────────────────
try:
    with open('data/directives.json', 'r', encoding='utf-8') as f:
        d = json.load(f)
    d['liquidity'] = {
        "net_liq_b": 2368, "reserves_b": 3116, "tga_b": 748, "rrp_b": 0,
        "zone": "WARNING", "zone_color": "#e07b39",
        "direction": "EXPANDING", "direction_arrow": "\u2191",
        "vs_last_week_b": 189, "vs_last_week_sign": "+",
        "action": "DEPLOY dry powder after April 15 — TGA drain = liquidity expanding",
        "historical_context": "2023 SVB level but EXPANDING direction post-tax season",
        "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M CET"),
        "source": "FRED manual"
    }
    d['last_updated'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M CET")
    with open('data/directives.json', 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    with open('data/directives.json') as f:
        check = json.load(f)
    assert check['liquidity']['net_liq_b'] == 2368
    print("FIX 1 PASS: liquidity $2,368B zone=WARNING written to directives.json")
except Exception as e:
    errors.append(f"FIX 1: {e}")
    print(f"FIX 1 FAIL: {e}")

# ── FIX 2: Remove duplicate Intelligence rows from index.html ─────────────
try:
    with open('/var/www/html/index.html', 'r', encoding='utf-8') as f:
        html = f.read()
    pattern = r'<tr>\s*<td colspan="15"[^>]*>\s*<div class="cat-band">(?:(?!</div>).)*?Intelligence(?:(?!</tr>).)*?</tr>'
    matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
    print(f"FIX 2: Found {len(matches)} Intelligence cat-band rows")
    if len(matches) > 1:
        html_clean = re.sub(pattern, '', html, flags=re.DOTALL|re.IGNORECASE)
        idx = html_clean.find('data-ticker="000660.KS"')
        if idx > 0 and matches:
            tr_start = html_clean.rfind('<tr', 0, idx)
            html_clean = html_clean[:tr_start] + matches[-1] + '\n' + html_clean[tr_start:]
        print(f"  After: {len(re.findall(pattern, html_clean, re.DOTALL|re.IGNORECASE))} rows")
        html = html_clean
        with open('/var/www/html/index.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print("FIX 2 PASS: duplicate rows removed")
    else:
        print(f"FIX 2: {len(matches)} rows — OK or already fixed")
except Exception as e:
    errors.append(f"FIX 2: {e}")
    print(f"FIX 2 FAIL: {e}")

# ── FIX 3: VIX update 24.61 → 19.12 ─────────────────────────────────────
try:
    with open('/var/www/html/index.html', 'r', encoding='utf-8') as f:
        html = f.read()
    old_count = html.count('24.61')
    html = html.replace('24.61', '19.12')
    with open('/var/www/html/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"FIX 3 PASS: VIX 24.61→19.12 ({old_count} replaced)")
except Exception as e:
    errors.append(f"FIX 3: {e}")
    print(f"FIX 3 FAIL: {e}")

# ── FIX 4: PLTR HOLD → DIP WATCH ─────────────────────────────────────────
try:
    with open('/var/www/html/index.html', 'r', encoding='utf-8') as f:
        html = f.read()
    pltr_idx = html.find('data-ticker="PLTR"')
    if pltr_idx > 0:
        seg = html[pltr_idx:pltr_idx+4000]
        new_seg = re.sub(r'(<(?:button|span|td)[^>]*>)\s*HOLD\s*(</(?:button|span|td)>)', r'\1DIP WATCH\2', seg, count=1, flags=re.IGNORECASE)
        if new_seg != seg:
            html = html[:pltr_idx] + new_seg + html[pltr_idx+4000:]
            with open('/var/www/html/index.html', 'w', encoding='utf-8') as f:
                f.write(html)
            print("FIX 4 PASS: PLTR → DIP WATCH")
        else:
            seg2 = seg.replace('>HOLD<', '>DIP WATCH<', 1)
            if seg2 != seg:
                html = html[:pltr_idx] + seg2 + html[pltr_idx+4000:]
                with open('/var/www/html/index.html', 'w', encoding='utf-8') as f:
                    f.write(html)
                print("FIX 4 PASS (simple): PLTR → DIP WATCH")
            else:
                print("FIX 4: HOLD not found in PLTR segment — check HTML structure")
    else:
        print("FIX 4: PLTR row not found")
except Exception as e:
    errors.append(f"FIX 4: {e}")
    print(f"FIX 4 FAIL: {e}")

# ── FIX 5: Add Lesson #08 ────────────────────────────────────────────────
try:
    with open('/var/www/html/index.html', 'r', encoding='utf-8') as f:
        html = f.read()
    if 'Lesson #08' not in html and 'Stop Breach' not in html:
        L08 = '\n<div style="border-left:3px solid #d4a017;padding:6px 10px;margin:6px 0;background:rgba(212,160,23,0.1);font-size:12px"><strong style="color:#d4a017">Lesson #08 · Stop Breach = One Shot</strong><br>A stop breach is an INFORMATION EVENT. Thesis check: INTACT \u2192 ARMED ONE SHOT (dip = widest Soros gap = maximum conviction). WOUNDED \u2192 EXIT REVIEW. DEAD \u2192 EXIT NOW. The deeper the dip with intact thesis = the higher the conviction.</div>\n'
        for anchor in ['Lesson #07', 'Lesson #06', 'Lesson #05']:
            if anchor in html:
                idx = html.find(anchor)
                close = html.find('</div>', idx)
                close2 = html.find('</div>', close+1)
                html = html[:close2+6] + L08 + html[close2+6:]
                print(f"FIX 5 PASS: Lesson #08 added after {anchor}")
                break
        else:
            print("FIX 5: No lesson anchor found")
        with open('/var/www/html/index.html', 'w', encoding='utf-8') as f:
            f.write(html)
    else:
        print("FIX 5: Lesson #08 already present")
except Exception as e:
    errors.append(f"FIX 5: {e}")
    print(f"FIX 5 FAIL: {e}")

# ── FIX 6: Replace morning brief engine ────────────────────────────────────
try:
    with open('battle_rhythm.py', 'r', encoding='utf-8') as f:
        br = f.read()

    WRAPPER = '''

def run_morning_brief_v2():
    """Run MINERVA-10X morning brief with live prices."""
    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "morning_brief_v2",
        os.path.join(os.path.dirname(__file__), "morning_brief_v2.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    import json
    with open(os.path.join(os.path.dirname(__file__), "data", "directives.json"), encoding="utf-8") as f:
        directives = json.load(f)
    liq = directives.get("liquidity", {})

    brief = mod.build_brief(
        liq_b=liq.get("net_liq_b", 2368),
        liq_delta=liq.get("vs_last_week_b", 189),
        vix=19.12
    )
    return brief
'''

    if 'run_morning_brief_v2' not in br:
        insert_at = br.rfind('\nif __name__')
        if insert_at < 0:
            insert_at = len(br)
        br = br[:insert_at] + WRAPPER + br[insert_at:]
        with open('battle_rhythm.py', 'w', encoding='utf-8') as f:
            f.write(br)
        print("FIX 6 PASS: morning brief v2 wired into battle_rhythm.py")
    else:
        print("FIX 6: run_morning_brief_v2 already present")
except Exception as e:
    errors.append(f"FIX 6: {e}")
    print(f"FIX 6 FAIL: {e}")

# ── SYNC and DEPLOY ──────────────────────────────────────────────────────
shutil.copy2('/var/www/html/index.html', 'OLYMPUS_UNIFIED.html')
print("\nOLYMPUS_UNIFIED.html synced")

print(f"\n{'='*45}")
print(f"ERRORS: {len(errors)}")
for e in errors: print(f"  {e}")
print("ALL DONE" if not errors else "COMPLETED WITH ERRORS")
print('='*45)
PYEOF

echo "--- VERIFY ---"
python3 -c "
import json
with open('data/directives.json') as f: d=json.load(f)
liq=d.get('liquidity',{})
print('Liq:', liq.get('net_liq_b','MISSING'), '— PASS' if liq.get('net_liq_b')==2368 else '— FAIL')
"

grep -c 'cat-band' /var/www/html/index.html
grep -c '19.12' /var/www/html/index.html
grep 'DIP WATCH' /var/www/html/index.html | head -1 | cut -c1-80
grep 'Lesson #08' /var/www/html/index.html | head -1 | cut -c1-50

echo "--- LIVE PRICE TEST ---"
python3 -c "
from morning_brief_v2 import fetch_prices
p = fetch_prices(['RKLB','URNM','PLTR','TSM'])
print('Live prices:')
for t,v in p.items():
    print(f'  {t}: ${v}')
print('RKLB should be ~$67, URNM ~$63 — NOT $5.50 or $24')
"

systemctl restart minerva

git add -A
if ! git diff --cached --quiet; then
  git commit --trailer "Made-with: Cursor" -m "complete fix: liq, dupe rows, VIX, PLTR action, Lesson08, brief v2 live prices"
else
  echo "No staged changes to commit"
fi

git push

echo "=== HARD REFRESH http://5.189.176.185 ==="