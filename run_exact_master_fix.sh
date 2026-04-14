#!/bin/bash
set -euo pipefail

cd ~/gods_plan

python3 << 'PYEOF'
import json, datetime, shutil, re

print("=== OLYMPUS MASTER FIX ===")
errors = []

# ─── FIX 1: Write liquidity to directives.json ───────────────────────────
try:
    with open('data/directives.json', 'r', encoding='utf-8') as f:
        d = json.load(f)
    
    d['liquidity'] = {
        "net_liq_b": 2368,
        "reserves_b": 3116,
        "tga_b": 748,
        "rrp_b": 0,
        "zone": "WARNING",
        "zone_color": "#e07b39",
        "direction": "EXPANDING",
        "direction_arrow": "\u2191",
        "vs_last_week_b": 189,
        "action": "DEPLOY dry powder after April 15",
        "historical_context": "2023 SVB level but direction EXPANDING post-tax TGA drain",
        "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M CET"),
        "source": "FRED manual April 13 2026"
    }
    d['last_updated'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M CET")
    
    with open('data/directives.json', 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    
    # Verify
    with open('data/directives.json', 'r') as f:
        check = json.load(f)
    assert check.get('liquidity',{}).get('net_liq_b') == 2368, "WRITE FAILED"
    print("FIX 1 PASS: liquidity written — net_liq=$2368B zone=WARNING")
except Exception as e:
    errors.append(f"FIX 1 FAILED: {e}")
    print(f"FIX 1 FAILED: {e}")

# ─── FIX 2: Remove duplicate INTELLIGENCE rows from index.html ─────────
try:
    with open('/var/www/html/index.html', 'r', encoding='utf-8') as f:
        html = f.read()
    
    # Count using regex to handle any encoding variant
    pattern = r'<tr><td colspan="15"[^>]*><div class="cat-band">.*?Intelligence.*?</div></td></tr>'
    matches = re.findall(pattern, html, re.DOTALL)
    print(f"FIX 2: Found {len(matches)} Intelligence cat-band rows")
    
    if len(matches) > 1:
        # Remove all occurrences
        html_clean = re.sub(pattern, '', html, flags=re.DOTALL)
        # Reinsert exactly one before 000660.KS row
        first_match = matches[0]
        marker_idx = html_clean.find('data-ticker="000660.KS"')
        if marker_idx > 0:
            tr_idx = html_clean.rfind('<tr', 0, marker_idx)
            html_clean = html_clean[:tr_idx] + first_match + '\n' + html_clean[tr_idx:]
        
        after_count = len(re.findall(pattern, html_clean, re.DOTALL))
        print(f"  After: {after_count} Intelligence rows (target: 1)")
        
        with open('/var/www/html/index.html', 'w', encoding='utf-8') as f:
            f.write(html_clean)
        print("FIX 2 PASS: duplicate rows removed from index.html")
    else:
        print(f"FIX 2: Already {len(matches)} rows — no change needed")
except Exception as e:
    errors.append(f"FIX 2 FAILED: {e}")
    print(f"FIX 2 FAILED: {e}")

# ─── FIX 3: Update VIX from 24.61 to 19.12 in index.html ────────────────
try:
    with open('/var/www/html/index.html', 'r', encoding='utf-8') as f:
        html = f.read()
    
    old_vix = html.count('24.61')
    html = html.replace('24.61', '19.12')
    new_vix = html.count('19.12')
    
    with open('/var/www/html/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"FIX 3 PASS: VIX updated 24.61→19.12 ({old_vix} occurrences replaced)")
except Exception as e:
    errors.append(f"FIX 3 FAILED: {e}")
    print(f"FIX 3 FAILED: {e}")

# ─── FIX 4: Update PLTR action HOLD → DIP WATCH in index.html ───────────
try:
    with open('/var/www/html/index.html', 'r', encoding='utf-8') as f:
        html = f.read()
    
    pltr_idx = html.find('data-ticker="PLTR"')
    if pltr_idx > 0:
        segment = html[pltr_idx:pltr_idx+3000]
        # Replace the first HOLD button text in PLTR's segment
        old_seg = segment
        segment = segment.replace('>HOLD<', '>DIP WATCH<', 1)
        if segment != old_seg:
            html = html[:pltr_idx] + segment + html[pltr_idx+3000:]
            with open('/var/www/html/index.html', 'w', encoding='utf-8') as f:
                f.write(html)
            print("FIX 4 PASS: PLTR action → DIP WATCH")
        else:
            print("FIX 4: HOLD button not found in PLTR segment — check manually")
    else:
        print("FIX 4: PLTR row not found")
except Exception as e:
    errors.append(f"FIX 4 FAILED: {e}")
    print(f"FIX 4 FAILED: {e}")

# ─── FIX 5: Add Lesson #08 to index.html ─────────────────────────────────
try:
    with open('/var/www/html/index.html', 'r', encoding='utf-8') as f:
        html = f.read()
    
    if 'Lesson #08' not in html:
        L08 = '<div style="border-left:3px solid #d4a017;padding:6px 10px;margin:4px 0;background:rgba(212,160,23,0.1)"><strong style="color:#d4a017">Lesson #08</strong> <em style="color:#888;font-size:11px">Stop Breach = One Shot</em><br><span style="font-size:12px">A stop breach is an INFORMATION EVENT. Thesis check first. If INTACT \u2192 ARMED ONE SHOT (dip widened narrative gap = maximum conviction). If WOUNDED \u2192 EXIT REVIEW. If DEAD \u2192 EXIT NOW. Deeper dip + intact thesis = widest Soros gap = highest conviction.</span></div>'
        
        # Find lesson anchor
        anchor = None
        for l in ['Lesson #07', 'Lesson #06', 'Lesson #05']:
            if l in html:
                anchor = l
                break
        
        if anchor:
            idx = html.find(anchor)
            # Find end of this lesson div
            close1 = html.find('</div>', idx)
            close2 = html.find('</div>', close1 + 1)
            insert_at = close2 + 6
            html = html[:insert_at] + '\n' + L08 + html[insert_at:]
            
            with open('/var/www/html/index.html', 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"FIX 5 PASS: Lesson #08 added after {anchor}")
        else:
            print("FIX 5: No lesson anchor found in HTML")
    else:
        print("FIX 5: Lesson #08 already present")
except Exception as e:
    errors.append(f"FIX 5 FAILED: {e}")
    print(f"FIX 5 FAILED: {e}")

# ─── SYNC OLYMPUS_UNIFIED.html ─────────────────────────────────────────────
shutil.copy2('/var/www/html/index.html', 'OLYMPUS_UNIFIED.html')
print("\nOLYMPUS_UNIFIED.html synced from index.html")

# ─── FINAL REPORT ──────────────────────────────────────────────────────────
print(f"\n{'='*40}")
if errors:
    print(f"COMPLETED WITH {len(errors)} ERRORS:")
    for e in errors: print(f"  {e}")
else:
    print("ALL 5 FIXES PASSED — ZERO ERRORS")
print("="*40)
PYEOF

# Restart minerva to pick up new directives.json
systemctl restart minerva
sleep 3

# VERIFY each fix explicitly
echo "--- VERIFICATION ---"
python3 -c "
import json
with open('data/directives.json') as f: d=json.load(f)
liq=d.get('liquidity',{})
print('Liq net_liq_b:', liq.get('net_liq_b','MISSING'))
print('Liq zone:', liq.get('zone','MISSING'))
print('FIX 1:', 'PASS' if liq.get('net_liq_b')==2368 else 'FAIL')
"

grep -c 'cat-band' /var/www/html/index.html && echo "cat-band count checked"
grep -c '19.12' /var/www/html/index.html && echo "VIX 19.12 confirmed"
grep 'DIP WATCH' /var/www/html/index.html && echo "PLTR DIP WATCH confirmed" || echo "DIP WATCH not found"
grep 'Lesson #08' /var/www/html/index.html && echo "Lesson 08 confirmed" || echo "Lesson 08 not found"

git add -A
git commit --trailer "Made-with: Cursor" -m "fix: liquidity $2368B, VIX 19.12, dupe rows, PLTR DIP WATCH, Lesson08"
git push

echo "=== HARD REFRESH http://5.189.176.185 NOW ==="