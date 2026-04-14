"""Re-inject GEM_DATA into OLYMPUS_UNIFIED.html from latest gem results."""
import json, os, sys, re
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
GEM_DIR = os.path.join(BASE, "gem_results")
HTML_FILE = os.path.join(BASE, "OLYMPUS_UNIFIED.html")

def get_latest_gem():
    files = sorted([f for f in os.listdir(GEM_DIR) if f.startswith("gem_") and f.endswith(".json")], reverse=True)
    if not files:
        print("No GEM results found")
        sys.exit(1)
    path = os.path.join(GEM_DIR, files[0])
    with open(path) as f:
        return json.load(f), files[0]

def _js_num(v):
    """Emit a JS number or null (0 is preserved; only None → null)."""
    if v is None:
        return "null"
    try:
        return str(float(v))
    except (TypeError, ValueError):
        return "null"


def _js_str(s):
    if s is None:
        return ""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def build_gem_data_js(gem, source_file):
    now = datetime.now()
    lines = []
    lines.append(f'/* MINERVA_GEM v5 (risk-integrated) · Auto-injected {now.strftime("%Y-%m-%d %H:%M")} from {source_file} */')
    lines.append('const GEM_DATA = {')

    for r in gem["results"]:
        tk = r["ticker"]
        g = r["grading"]
        vs = r.get("versus", {})
        entry = (
            f'  "{tk}": {{'
            f'grade:"{_js_str(g.get("grade"))}",gem_score:{g["gem_score"]:.1f},'
            f'u1y:{g["upside_1y_pct"]:.2f},u5y:{g["upside_5y_pct"]:.2f},'
            f'worst1y:{g["worst_drop_1y_pct"]:.2f},'
            f'unreal:{_js_num(vs.get("unrealized_pnl_pct"))},'
            f'cur_vs_1y:{_js_num(vs.get("current_vs_ev_1y_pct"))},'
            f'mos:{_js_num(vs.get("entry_margin_of_safety_1y_pct"))},'
            f'risk_avg:{_js_num(g.get("risk_avg"))},'
            f'risk_level:"{_js_str(g.get("risk_level","UNKNOWN"))}",'
            f'risk_int:{str(g.get("risk_integrated",False)).lower()},'
            f'pgrade:"{_js_str(g.get("precision_grade",""))}",'
            f'mode:"{_js_str(r.get("valuation_mode",""))}"}}'
        )
        lines.append(entry + ',')

    lines.append('};')
    lines.append('')
    lines.append('window._GEM_META = {')
    lines.append(f'  run_date: "{gem["run_date"]}",')
    lines.append(f'  run_time: "{gem["run_time"]}",')
    lines.append(f'  source: "{source_file}",')
    lines.append(f'  total: {gem["total_positions"]},')
    gs = json.dumps(gem["grade_summary"])
    lines.append(f'  grade_summary: {gs},')
    lines.append(f'  risk_integrated: true')
    lines.append('};')

    return '\n'.join(lines)

MARK_BEGIN = "// OLYMPUS_GEM_DATA_BEGIN"
MARK_END = "// OLYMPUS_GEM_DATA_END"


def inject(html_content, new_js):
    """Replace ONLY the GEM_DATA + _GEM_META block between line markers — never the rest of the <script>."""
    pattern = r"(" + re.escape(MARK_BEGIN) + r"\r?\n).*?(\r?\n" + re.escape(MARK_END) + r")"
    if not re.search(pattern, html_content, flags=re.DOTALL):
        raise RuntimeError(
            f"{MARK_BEGIN} / {MARK_END} not found in HTML — refusing to overwrite (would delete dashboard JS)."
        )
    return re.sub(pattern, r"\1" + new_js + r"\2", html_content, count=1, flags=re.DOTALL)

def main():
    gem, source = get_latest_gem()
    print(f"Loaded {source}: {gem['total_positions']} positions, grades: {gem['grade_summary']}")

    js = build_gem_data_js(gem, source)

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    new_html = inject(html, js)

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(new_html)

    print(f"Injected into {HTML_FILE}")

if __name__ == "__main__":
    main()
