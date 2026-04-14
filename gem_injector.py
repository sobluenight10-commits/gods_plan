"""
gem_injector.py — MINERVA_GEM Auto-Inject Pipeline
Runs daily at 07:06 Berlin (after run_gem_daily.py at 07:05)

What it does:
1. Reads today's gem_results/gem_YYYYMMDD.json
2. Builds GEM_DATA JS object from results
3. Finds the GEM_INJECT markers in OLYMPUS_UNIFIED.html
4. Replaces everything between them with fresh GEM data + summary bar
5. Copies updated HTML to /var/www/html/index.html

Markers required in OLYMPUS_UNIFIED.html:
  <!-- GEM_INJECT_START -->
  ...anything here gets replaced daily...
  <!-- GEM_INJECT_END -->
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

BASE_DIR   = Path(__file__).parent
GEM_DIR    = BASE_DIR / "gem_results"
HTML_SRC   = BASE_DIR / "OLYMPUS_UNIFIED.html"
HTML_DEST  = Path("/var/www/html/index.html")

MARKER_START = "<!-- GEM_INJECT_START -->"
MARKER_END   = "<!-- GEM_INJECT_END -->"


def load_latest_gem():
    files = sorted(GEM_DIR.glob("gem_*.json"))
    if not files:
        raise FileNotFoundError("No GEM result files found in gem_results/")
    latest = files[-1]
    with open(latest) as f:
        return json.load(f), latest.name


GRADE_FG = {"S":"#B8860B","A+":"#3B6D11","A":"#3B6D11","B+":"#185FA5","B":"#185FA5",
            "C+":"#854F0B","C":"#854F0B","D":"#A32D2D","F":"#A32D2D"}
GRADE_BG = {"S":"#FFF8E1","A+":"#EAF3DE","A":"#EAF3DE","B+":"#E6F1FB","B":"#E6F1FB",
            "C+":"#FAEEDA","C":"#FAEEDA","D":"#FCEBEB","F":"#FCEBEB"}
GRADE_ORDER = ["S","A+","A","B+","B","C+","C","D","F"]

def grade_color(grade):
    return GRADE_FG.get(grade, "#888")

def grade_bg(grade):
    return GRADE_BG.get(grade, "#f5f5f5")


def build_inject_block(gem_data: dict, filename: str) -> str:
    results   = gem_data["results"]
    summary   = gem_data["grade_summary"]
    run_date  = gem_data["run_date"]
    run_time  = gem_data["run_time"]
    changes   = gem_data.get("grade_changes", [])

    # ── GEM_DATA JS object ────────────────────────────────────────────────────
    js_entries = []
    for r in results:
        g  = r["grading"]
        vs = r["versus"]
        ticker = r["ticker"].replace('"', '\\"')
        gem_score = g.get("gem_score", 0)
        entry = (
            f'  "{ticker}": {{'
            f'grade:"{g["grade"]}",'
            f'gem_score:{gem_score},'
            f'u1y:{g["upside_1y_pct"]},'
            f'u5y:{g["upside_5y_pct"]},'
            f'worst1y:{g["worst_drop_1y_pct"]},'
            f'unreal:{vs["unrealized_pnl_pct"] if vs["unrealized_pnl_pct"] is not None else "null"},'
            f'cur_vs_1y:{vs["current_vs_ev_1y_pct"]},'
            f'mos:{vs["entry_margin_of_safety_1y_pct"] if vs["entry_margin_of_safety_1y_pct"] is not None else "null"},'
            f'mode:"{r["valuation_mode"]}"'
            f'}}'
        )
        js_entries.append(entry)

    gem_data_js = "{\n" + ",\n".join(js_entries) + "\n}"

    # ── Grade summary badges (9-tier, skip zeros) ────────────────────────────
    summary_badges_parts = []
    for g in GRADE_ORDER:
        n = summary.get(g, 0)
        if n > 0:
            summary_badges_parts.append(
                f'<span style="background:{grade_bg(g)};color:{grade_color(g)};'
                f'font-size:11px;font-weight:600;padding:2px 8px;border-radius:3px">'
                f'{g}: {n}</span>'
            )
    summary_badges = " &nbsp; ".join(summary_badges_parts)

    # ── Grade change alerts ───────────────────────────────────────────────────
    change_html = ""
    if changes:
        items = " &nbsp; ".join(
            f'<span style="color:#854F0B">⚡ {c["ticker"]}: {c["from"]}→{c["to"]}</span>'
            for c in changes
        )
        change_html = (
            f'<div style="background:#FAEEDA;border-left:3px solid #EF9F27;'
            f'padding:4px 10px;margin-bottom:6px;font-size:11px;border-radius:0 4px 4px 0">'
            f'GRADE CHANGES: {items}</div>'
        )

    # ── Full inject block ─────────────────────────────────────────────────────
    block = f"""<!-- GEM_INJECT_START -->
<script>
/* MINERVA_GEM · Auto-injected {run_date} {run_time} from {filename} */
const GEM_DATA = {gem_data_js};

window._GEM_META = {{
  run_date: "{run_date}",
  run_time: "{run_time}",
  source: "{filename}",
  total: {gem_data["total_positions"]},
  grade_summary: {json.dumps(summary)}
}};

function gemBadge(grade) {{
  const bg = {{S:"#FFF8E1","A+":"#EAF3DE",A:"#EAF3DE","B+":"#E6F1FB",B:"#E6F1FB","C+":"#FAEEDA",C:"#FAEEDA",D:"#FCEBEB",F:"#FCEBEB"}};
  const fg = {{S:"#B8860B","A+":"#3B6D11",A:"#3B6D11","B+":"#185FA5",B:"#185FA5","C+":"#854F0B",C:"#854F0B",D:"#A32D2D",F:"#A32D2D"}};
  return `<span style="background:${{bg[grade]||bg.D}};color:${{fg[grade]||fg.D}};font-size:10px;font-weight:600;padding:2px 6px;border-radius:3px">${{grade}}</span>`;
}}

function gemColor(v) {{
  if(v===null||v===undefined) return "#888";
  return v>0?"#3B6D11":v<0?"#A32D2D":"#888";
}}

function gemFmt(v, dec) {{
  dec = dec||1;
  if(v===null||v===undefined) return "—";
  return (v>0?"+":"")+v.toFixed(dec)+"%";
}}

function gemRow(ticker) {{
  const d = GEM_DATA[ticker];
  if(!d) return "";
  return [
    gemBadge(d.grade),
    `<span style="color:${{gemColor(d.u1y)}};font-size:11px">${{gemFmt(d.u1y)}}</span>`,
    `<span style="color:${{gemColor(d.u5y)}};font-size:11px">${{gemFmt(d.u5y)}}</span>`,
    `<span style="color:${{gemColor(d.worst1y)}};font-size:11px">${{gemFmt(d.worst1y)}}</span>`,
    `<span style="color:${{gemColor(d.unreal)}};font-size:11px">${{gemFmt(d.unreal)}}</span>`,
    `<span style="color:${{gemColor(d.cur_vs_1y)}};font-size:11px">${{gemFmt(d.cur_vs_1y)}}</span>`,
    `<span style="color:${{gemColor(d.mos)}};font-size:11px">${{gemFmt(d.mos)}}</span>`,
  ].join(' ');
}}

function injectGemIntoTables() {{
  document.querySelectorAll('[data-ticker]').forEach(el => {{
    const ticker = el.getAttribute('data-ticker');
    if (!ticker) return;
    const d = GEM_DATA[ticker];
    if(!d) return;
    const htmlBits =
      gemBadge(d.grade) +
      ' <span style="color:#888">1y:</span><span style="color:'+gemColor(d.u1y)+'">'+gemFmt(d.u1y)+'</span>' +
      ' <span style="color:#888">5y:</span><span style="color:'+gemColor(d.u5y)+'">'+gemFmt(d.u5y)+'</span>' +
      ' <span style="color:#888">P&L:</span><span style="color:'+gemColor(d.unreal)+'">'+gemFmt(d.unreal)+'</span>' +
      ' <span style="color:#888">vs1y:</span><span style="color:'+gemColor(d.cur_vs_1y)+'">'+gemFmt(d.cur_vs_1y)+'</span>' +
      ' <span style="color:#888">MoS:</span><span style="color:'+gemColor(d.mos)+'">'+gemFmt(d.mos)+'</span>';
    const mainRow = el.closest('tr');
    if (!mainRow) {{
      let gemEl = el.querySelector('.gem-metrics');
      if(!gemEl) {{
        gemEl = document.createElement('div');
        gemEl.className = 'gem-metrics';
        gemEl.style.cssText = 'margin-top:4px;font-size:11px;display:flex;gap:6px;flex-wrap:wrap;align-items:center';
        el.appendChild(gemEl);
      }}
      gemEl.innerHTML = htmlBits;
      return;
    }}
    if (mainRow.nextElementSibling && mainRow.nextElementSibling.classList &&
        mainRow.nextElementSibling.classList.contains('gem-sub-row')) return;
    const ncol = mainRow.children.length;
    if (!ncol) return;
    const sub = document.createElement('tr');
    sub.className = 'gem-sub-row';
    const td = document.createElement('td');
    td.colSpan = ncol;
    td.style.cssText = 'padding:6px 12px;background:#f8f9fa;font-size:11px;border-bottom:1px solid #e8e8e8;';
    const inner = document.createElement('div');
    inner.className = 'gem-metrics';
    inner.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;align-items:center';
    inner.innerHTML = htmlBits;
    td.appendChild(inner);
    sub.appendChild(td);
    mainRow.insertAdjacentElement('afterend', sub);
  }});
}}

function updateGemGradeBar() {{
  var bar = document.getElementById('gem-grade-bar');
  if (!bar) return;
  var counts = {{}};
  var tiers = ['S','A+','A','B+','B','C+','C','D','F'];
  tiers.forEach(function(t){{ counts[t] = 0; }});
  Object.keys(GEM_DATA).forEach(function(k) {{
    var g = GEM_DATA[k].grade;
    if (counts[g] != null) counts[g]++;
    else counts[g] = 1;
  }});
  var bgMap = {{S:"#FFF8E1","A+":"#EAF3DE",A:"#EAF3DE","B+":"#E6F1FB",B:"#E6F1FB","C+":"#FAEEDA",C:"#FAEEDA",D:"#FCEBEB",F:"#FCEBEB"}};
  var fgMap = {{S:"#B8860B","A+":"#3B6D11",A:"#3B6D11","B+":"#185FA5",B:"#185FA5","C+":"#854F0B",C:"#854F0B",D:"#A32D2D",F:"#A32D2D"}};
  var html = '';
  tiers.forEach(function(t) {{
    if (counts[t] > 0) {{
      html += '<span style="background:' + bgMap[t] + ';color:' + fgMap[t] + ';font-size:11px;font-weight:600;padding:2px 8px;border-radius:3px">' + t + ': ' + counts[t] + '</span> &nbsp; ';
    }}
  }});
  bar.innerHTML = html;
}}

function populateGradeSummary() {{
  var body = document.getElementById('grade-summary-body');
  if (!body) return;
  var gradeRank = {{S:0,"A+":1,A:2,"B+":3,B:4,"C+":5,C:6,D:7,F:8}};
  var rows = [];
  Object.keys(GEM_DATA).forEach(function(tk) {{
    var d = GEM_DATA[tk];
    rows.push({{ticker: tk, grade: d.grade, gem: d.gem_score || 0, u1y: d.u1y, u5y: d.u5y}});
  }});
  rows.sort(function(a, b) {{
    var ga = gradeRank[a.grade] != null ? gradeRank[a.grade] : 9;
    var gb = gradeRank[b.grade] != null ? gradeRank[b.grade] : 9;
    if (ga !== gb) return ga - gb;
    return b.gem - a.gem;
  }});
  var bgMap = {{S:"#FFF8E1","A+":"#EAF3DE",A:"#EAF3DE","B+":"#E6F1FB",B:"#E6F1FB","C+":"#FAEEDA",C:"#FAEEDA",D:"#FCEBEB",F:"#FCEBEB"}};
  var fgMap = {{S:"#B8860B","A+":"#3B6D11",A:"#3B6D11","B+":"#185FA5",B:"#185FA5","C+":"#854F0B",C:"#854F0B",D:"#A32D2D",F:"#A32D2D"}};
  var html = '';
  rows.forEach(function(r, i) {{
    var bg = i % 2 === 0 ? '#fff' : '#f8f9fa';
    var evColor = function(v) {{ return v == null ? '#888' : v > 0 ? '#3B6D11' : '#A32D2D'; }};
    var evFmt = function(v) {{ return v == null ? '\u2014' : (v > 0 ? '+' : '') + v.toFixed(1) + '%'; }};
    html += '<tr style="background:' + bg + '">' +
      '<td style="padding:3px 8px;font-weight:600">' + r.ticker + '</td>' +
      '<td style="text-align:center;padding:3px 8px"><span style="background:' + (bgMap[r.grade]||bgMap.D) + ';color:' + (fgMap[r.grade]||fgMap.D) + ';font-size:10px;font-weight:600;padding:1px 5px;border-radius:3px">' + r.grade + '</span></td>' +
      '<td style="text-align:right;padding:3px 8px">' + r.gem.toFixed(1) + '</td>' +
      '<td style="text-align:right;padding:3px 8px;color:' + evColor(r.u1y) + '">' + evFmt(r.u1y) + '</td>' +
      '<td style="text-align:right;padding:3px 8px;color:' + evColor(r.u5y) + '">' + evFmt(r.u5y) + '</td>' +
      '</tr>';
  }});
  body.innerHTML = html;
}}

document.addEventListener('DOMContentLoaded', function() {{
  setTimeout(injectGemIntoTables, 300);
  setTimeout(updateGemGradeBar, 400);
  setTimeout(populateGradeSummary, 500);
}});
</script>

<div id="gem-header-bar" style="background:#f8f9fa;border:0.5px solid #ddd;border-radius:6px;padding:8px 12px;margin-bottom:10px;font-size:12px">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
    <div>
      <span style="font-weight:600;color:#333">MINERVA_GEM</span>
      <span style="color:#888;margin:0 6px">·</span>
      <span id="gem-grade-bar">{summary_badges}</span>
    </div>
    <div style="color:#888;font-size:11px">
      Last run: {run_date} {run_time}
      <span style="color:#854F0B;margin-left:8px">⚡ auto 07:05 Berlin</span>
    </div>
  </div>
  {change_html}
  <div style="margin-top:6px;font-size:11px;color:#888">
    Columns injected on all [data-ticker] elements · Grade = 40/40/20 Worst/Normal/Bull weighted GEM Score
  </div>
</div>
<!-- GEM_INJECT_END -->"""

    return block


def inject_into_html(html: str, block: str) -> str:
    start_idx = html.find(MARKER_START)
    end_idx   = html.find(MARKER_END)

    if start_idx == -1 or end_idx == -1:
        raise ValueError(
            f"Markers not found in HTML.\n"
            f"Add these two lines to OLYMPUS_UNIFIED.html inside §13:\n"
            f"  {MARKER_START}\n"
            f"  {MARKER_END}"
        )

    end_idx += len(MARKER_END)
    return html[:start_idx] + block + html[end_idx:]


def run():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] MINERVA_GEM injector starting...")

    gem_data, fname = load_latest_gem()
    print(f"  Loaded: {fname} ({gem_data['total_positions']} positions)")

    if not HTML_SRC.exists():
        raise FileNotFoundError(f"Source HTML not found: {HTML_SRC}")

    html = HTML_SRC.read_text(encoding="utf-8")
    block = build_inject_block(gem_data, fname)
    new_html = inject_into_html(html, block)

    HTML_SRC.write_text(new_html, encoding="utf-8")
    if HTML_DEST.parent.exists():
        shutil.copy2(HTML_SRC, HTML_DEST)

    changes = gem_data.get("grade_changes", [])
    print(f"  Grade summary: {gem_data['grade_summary']}")
    if changes:
        print(f"  GRADE CHANGES: {changes}")
    print(f"  Deployed → {HTML_DEST}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Done.")


if __name__ == "__main__":
    run()
