"""
gem_injector_v2.py
Reads dashboard_state.json and injects W/N/B/EV/vs% into OLYMPUS dashboard.
Handles nested <tr> elements correctly using a depth counter.
"""
import json, re, shutil
from pathlib import Path

HTML  = Path('/var/www/html/index.html')
STATE = Path('/root/gods_plan/data/dashboard_state.json')

def find_outer_row_bounds(html, ticker):
    """
    Find the start and end of the OUTER <tr data-ticker="TICKER"> row.
    Handles nested tables (inner <tr> elements) using depth counting.
    Returns (row_start, row_end) indices or (None, None).
    """
    pattern = f'data-ticker="{re.escape(ticker)}"'
    m = re.search(pattern, html)
    if not m:
        return None, None

    # The <tr> containing data-ticker - find it going backwards
    row_start = html.rfind('<tr ', 0, m.start())
    if row_start < 0:
        row_start = html.rfind('<tr>', 0, m.start())
    if row_start < 0:
        return None, None

    # Now walk forward counting <tr> and </tr> to find the matching </tr>
    pos = row_start + 4  # skip past '<tr '
    depth = 1
    while pos < len(html) and depth > 0:
        next_open  = html.find('<tr', pos)
        next_close = html.find('</tr>', pos)
        if next_close < 0:
            return None, None
        if next_open >= 0 and next_open < next_close:
            # Another <tr opens before the next </tr> - go deeper
            depth += 1
            pos = next_open + 3
        else:
            # </tr> comes next
            depth -= 1
            if depth == 0:
                row_end = next_close + 5  # include </tr>
                return row_start, row_end
            pos = next_close + 5
    return None, None

def fmt(val, ticker=''):
    if val is None or val == 0: return '—'
    if ticker in ('000660.KS','272210.KS'):
        if val >= 1e6: return f'\u20a9{val/1e6:.1f}M'
        if val >= 1e3: return f'\u20a9{val/1e3:.0f}K'
        return f'\u20a9{int(val)}'
    if ticker == '1810.HK': return f'HK${val:.2f}'
    if ticker in ('ASML','MC.PA'):
        return f'\u20ac{val:,.0f}' if val >= 1000 else f'\u20ac{val:.1f}'
    if val >= 1000: return f'${val:,.0f}'
    if val >= 10:   return f'${val:.1f}'
    return f'${val:.2f}'

def pct_span(v, size=10):
    if v is None: return f'<span style="color:#ccc;font-size:{size}px">—</span>'
    c = '#2d7a2d' if v >= 0 else '#c0392b'
    s = '+' if v >= 0 else ''
    return f'<span style="color:{c};font-size:{size}px;font-weight:500">{s}{v:.1f}%</span>'

def build_scenario_table(proj, ticker):
    horizons = ['1m','6m','1y','3y','5y']
    labels = ['1M','6M','1Y','3Y','5Y']

    def row(cls, label, key, lbl_color):
        cells = ''.join(
            f'<td style="text-align:right;padding:0 5px;font-size:10px">{fmt(proj.get(h,{}).get(key),ticker)}</td>'
            for h in horizons
        )
        return (f'<tr class="{cls}">'
                f'<td style="padding:0 5px;font-size:10px;font-weight:600;min-width:16px;color:{lbl_color}">{label}</td>'
                f'{cells}</tr>')

    def ev_row():
        cells = ''
        for h in horizons:
            p   = proj.get(h, {})
            ev  = p.get('ev')
            up  = p.get('vs_current', {}).get('ev_pct') if isinstance(p.get('vs_current'), dict) else None
            if ev and ev > 0:
                c   = '#2d7a2d' if (up or 0) >= 0 else '#c0392b'
                pct = f'<br><span style="font-size:8px">{("+" if (up or 0)>=0 else "")}{up:.0f}%</span>' if up is not None else ''
                cells += f'<td style="text-align:right;padding:0 5px;font-size:10px;font-weight:600;color:{c}">{fmt(ev,ticker)}{pct}</td>'
            else:
                cells += '<td style="text-align:right;padding:0 5px;color:#ccc;font-size:10px">—</td>'
        return (f'<tr style="background:#f0f8f0">'
                f'<td style="padding:0 5px;font-size:10px;font-weight:700;color:#2a6e2a">EV</td>'
                f'{cells}</tr>')

    def vs_row():
        cells = ''
        for h in horizons:
            vc = proj.get(h, {}).get('vs_current')
            up = vc.get('ev_pct') if isinstance(vc, dict) else None
            cells += f'<td style="text-align:right;padding:0 4px">{pct_span(up, size=9)}</td>'
        return (f'<tr style="background:#fafafa;border-top:1px solid #eee">'
                f'<td style="padding:0 5px;font-size:9px;color:#aaa">vs%</td>{cells}</tr>')

    header = ('<tr><td style="padding:0 5px;font-size:9px;color:#aaa"></td>'
              + ''.join(f'<th style="text-align:right;padding:0 5px;font-size:9px;color:#aaa;font-weight:400">{l}</th>'
                        for l in labels) + '</tr>')

    table = (f'<table class="scenario-tbl" style="border-collapse:collapse;width:100%;font-family:monospace">'
             f'{header}'
             f'{row("sc-worst", "W", "worst", "#c0392b")}'
             f'{row("sc-normal","N", "normal","#555")}'
             f'{row("sc-bull",  "B", "bull",  "#2d7a2d")}'
             f'{ev_row()}'
             f'{vs_row()}'
             f'</table>')
    return table

def build_versus(pos):
    pnl = pos.get('pnl_pct')
    u1y = pos.get('gem_u1y')
    proj = pos.get('projections', {})
    ve5  = proj.get('5y', {}).get('vs_entry', {})
    p5y  = ve5.get('ev_pct') if isinstance(ve5, dict) else None

    parts = []
    if pnl  is not None: parts.append(f'<span style="color:#888;font-size:10px">P&L: </span>{pct_span(pnl)}')
    if u1y  is not None: parts.append(f'<span style="color:#888;font-size:10px">vs1y: </span>{pct_span(u1y)}')
    if p5y  is not None: parts.append(f'<span style="color:#888;font-size:10px">entry\u21925y: </span>{pct_span(p5y)}')
    if not parts: return ''
    return (f'<div style="padding:2px 5px 3px;display:flex;gap:10px;flex-wrap:wrap;'
            f'border-top:1px solid #eee;background:#fefefe">'
            f'{"".join(parts)}</div>')

def main():
    with open(STATE) as f: state = json.load(f)
    with open(HTML, 'r', encoding='utf-8') as f: html = f.read()

    positions = state.get('positions', {})
    injected  = 0
    skipped   = []

    for ticker, pos in positions.items():
        proj = pos.get('projections', {})

        # Find outer row bounds using depth-aware search
        rs, re_ = find_outer_row_bounds(html, ticker)
        if rs is None:
            skipped.append(f'{ticker}: row not found')
            continue

        row_html = html[rs:re_]

        # Find colspan="5" td within this row
        span5_idx = row_html.find('colspan="5"')
        if span5_idx < 0:
            skipped.append(f'{ticker}: no colspan=5')
            continue

        td_open  = row_html.rfind('<td', 0, span5_idx)
        td_close = row_html.find('</td>', span5_idx) + 5

        # Build scenario content
        if proj:
            table_html   = build_scenario_table(proj, ticker)
            versus_html  = build_versus(pos)
            inner_content = table_html + versus_html
        else:
            # Watchlist / IPO with no projections — keep existing content
            old_inner = row_html[td_open:td_close]
            inner_start = old_inner.find('>') + 1
            inner_end   = old_inner.rfind('</td>')
            inner_content = old_inner[inner_start:inner_end]

        new_td   = f'<td colspan="5" class="mx-scenarios" style="padding:2px 4px;vertical-align:top">{inner_content}</td>'
        new_row  = row_html[:td_open] + new_td + row_html[td_close:]

        # Update action cell
        action_display = pos.get('action', 'HOLD')
        action_code    = pos.get('action_code', 'HOLD')
        cls_map = {
            'ARMED_ONE_SHOT': 'mx-act-oneshot',
            'ARMED':          'mx-act-armed',
            'ADD':            'mx-act-add',
            'DIP_WATCH':      'mx-act-dipwatch',
            'HOLD':           'mx-act-hold',
            'EXIT':           'mx-act-exit',
            'EXIT_REVIEW':    'mx-act-exitreview',
        }
        act_cls  = cls_map.get(action_code, 'mx-act-hold')
        new_row  = re.sub(
            r'<span class="mx-act[^"]*">[^<]*</span>',
            f'<span class="mx-act {act_cls}">{action_display}</span>',
            new_row, count=1
        )

        html = html[:rs] + new_row + html[re_:]
        injected += 1
        print(f'  {ticker}: injected — {action_display}')

    print(f'\nInjected: {injected} | Skipped: {len(skipped)}')
    for s in skipped: print(f'  SKIP: {s}')

    with open(HTML, 'w', encoding='utf-8') as f: f.write(html)
    shutil.copy2(HTML, '/root/gods_plan/OLYMPUS_UNIFIED.html')
    print('Deployed.')

if __name__ == '__main__':
    main()
