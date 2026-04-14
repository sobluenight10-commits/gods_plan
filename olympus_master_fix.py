#!/usr/bin/env python3
import datetime
import json
import shutil

print("=== OLYMPUS MASTER FIX - April 13 2026 ===\n")

with open("data/directives.json", "r", encoding="utf-8") as f:
    directives = json.load(f)

directives["liquidity"] = {
    "net_liq_b": 2368,
    "reserves_b": 3116,
    "tga_b": 748,
    "rrp_b": 0,
    "zone": "WARNING",
    "zone_color": "#e07b39",
    "direction": "EXPANDING",
    "direction_symbol": "\u2191",
    "vs_last_week_b": 189,
    "vs_last_week_sign": "+",
    "action": "DEPLOY dry powder after April 15 - liquidity expanding, risk-on confirmed",
    "historical_context": "Same level as 2023 SVB crisis - but direction EXPANDING post April 15 TGA drain",
    "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M CET"),
    "source": "FRED: WRESBAL + WTREGEN + RRPONTSYD",
}

directives["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M CET")

with open("data/directives.json", "w", encoding="utf-8") as f:
    json.dump(directives, f, indent=2, ensure_ascii=False)

print("FIX 1 DONE: liquidity injected into directives.json")
print("  Net Liq: $2,368B | Zone: WARNING | Direction: EXPANDING")

FRED_WRITE_PATCH = """

def write_liquidity_to_directives(net_liq, reserves, tga, rrp, vs_last_week=0):
    import json
    import datetime as _dt
    import os
    directives_path = os.path.join(os.path.dirname(__file__), "data", "directives.json")
    try:
        with open(directives_path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    if net_liq < 2000:
        zone, color = "DANGER", "#e05252"
    elif net_liq < 2500:
        zone, color = "WARNING", "#e07b39"
    elif net_liq < 3500:
        zone, color = "NORMAL", "#c4a84f"
    else:
        zone, color = "ABUNDANCE", "#4caf50"
    d["liquidity"] = {
        "net_liq_b": round(net_liq),
        "reserves_b": round(reserves),
        "tga_b": round(tga),
        "rrp_b": round(rrp),
        "zone": zone,
        "zone_color": color,
        "direction": "EXPANDING" if vs_last_week > 0 else "CONTRACTING",
        "direction_symbol": "\u2191" if vs_last_week > 0 else "\u2193",
        "vs_last_week_b": abs(round(vs_last_week)),
        "vs_last_week_sign": "+" if vs_last_week > 0 else "-",
        "action": (
            "DEPLOY dry powder"
            if (net_liq > 2500 or vs_last_week > 0)
            else "HOLD CASH"
        ),
        "last_updated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M CET"),
        "source": "FRED auto-fetch",
    }
    d["last_updated"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M CET")
    with open(directives_path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return d["liquidity"]
"""

OLD_BLOCK_START = "        last_updated = datetime.now().strftime"
OLD_BLOCK_END = '            logger.warning("fetch_fred_liquidity: could not write directives.json: %s", e)'

with open("battle_rhythm.py", "r", encoding="utf-8") as f:
    br = f.read()

if "def write_liquidity_to_directives" not in br:
    idx = br.find("def fetch_fred_liquidity")
    if idx != -1:
        br = br[:idx] + FRED_WRITE_PATCH + "\n" + br[idx:]
        print("FIX 2a: write_liquidity_to_directives function added")

if "def write_liquidity_to_directives" in br and OLD_BLOCK_START in br and OLD_BLOCK_END in br:
    s = br.find(OLD_BLOCK_START)
    e = br.find(OLD_BLOCK_END) + len(OLD_BLOCK_END)
    if s != -1 and e > s:
        br = (
            br[:s]
            + "        write_liquidity_to_directives(net, res_b, tga_b, rrp_b, change)\n"
            + br[e:]
        )
        print("FIX 2b: replaced inline directives write with write_liquidity_to_directives call")
else:
    print("FIX 2b: old block not found or already migrated - skipped")

with open("battle_rhythm.py", "w", encoding="utf-8") as f:
    f.write(br)

HTML_PATH = "/var/www/html/index.html"
with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

DUPE_BYTES = (
    '<tr><td colspan="15" style="padding:0"><div class="cat-band">'
    '<div class="cdot" style="background:var(--c1)"></div>'
    '<div class="cname" style="color:var(--c1)">Intelligence</div>'
    '<div class="cdesc">AGI \xb7 Quantum \xb7 Neural Interfaces \xb7 Advanced Memory \xb7 AI Hardware</div>'
    "</div></td></tr>"
)
DUPE_UNICODE = DUPE_BYTES.replace("\xb7", "\u00b7")

for label, DUPE in (("middot-byte", DUPE_BYTES), ("middot-unicode", DUPE_UNICODE)):
    count = html.count(DUPE)
    if count:
        print(f"\nFIX 3: Using {label} - found {count} INTELLIGENCE headers in index.html")
        if count > 1:
            html = html.replace(DUPE, "", count)
            idx = html.find('data-ticker="000660.KS"')
            if idx != -1:
                tr = html.rfind("<tr", 0, idx)
                html = html[:tr] + DUPE + "\n" + html[tr:]
            print(f"  After fix: {html.count(DUPE)} headers")
        break
else:
    print("\nFIX 3: No matching INTELLIGENCE cat-band pattern in index.html")

L08 = """<div class="lesson-item" style="border-left:3px solid #d4a017;padding:8px 12px;margin:4px 0;background:rgba(212,160,23,0.08)">
  <strong style="color:#d4a017">Lesson #08</strong>
  <em style="color:#888;margin:0 6px">Stop Breach = One Shot</em>
  <span style="font-size:12px">A stop breach is an INFORMATION EVENT, not a loss event. Thesis check first. INTACT &#8594; ARMED ONE SHOT (dip widened narrative gap = maximum conviction). WOUNDED &#8594; EXIT REVIEW. DEAD &#8594; EXIT NOW. The deeper the dip with intact thesis = the wider the Soros gap = the higher the conviction = most aggressive sizing.</span>
</div>"""

if "Lesson #08" not in html and "Stop Breach" not in html:
    anchor = (
        "Lesson #07"
        if "Lesson #07" in html
        else ("Lesson #06" if "Lesson #06" in html else None)
    )
    if anchor:
        idx = html.find(anchor)
        close = html.find("</div>", idx)
        close2 = html.find("</div>", close + 1)
        html = html[: close2 + 6] + "\n" + L08 + html[close2 + 6 :]
        print("FIX 4: Lesson #08 added")
    else:
        print("FIX 4: No lesson anchor found")
else:
    print("FIX 4: Lesson #08 already present")

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)

shutil.copy2(HTML_PATH, "OLYMPUS_UNIFIED.html")

print("\nAll fixes written.")
