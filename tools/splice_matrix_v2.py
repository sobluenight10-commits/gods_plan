# One-off splice: Master Matrix v2 + remove global Decision Engine hero.
# Run from repo root: python tools/splice_matrix_v2.py

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "OLYMPUS_UNIFIED.html"

CSS_INSERT = """
/* ── SOROS REFLEXIVITY PANEL (Master Matrix tab) ── */
.soros-wrap{padding:16px 40px 20px;background:#070a0e;border-bottom:2px solid rgba(212,175,55,0.45);}
.soros-card{
  background:linear-gradient(165deg,#05080c 0%,#0f141c 45%,#121a26 100%);
  border:3px solid #d4af37;border-radius:14px;padding:22px 26px 20px;
  box-shadow:0 16px 48px rgba(0,0,0,0.35),inset 0 1px 0 rgba(212,175,55,0.1);
}
.soros-h{font-family:'Syne',sans-serif;font-weight:800;font-size:10px;letter-spacing:0.26em;text-transform:uppercase;color:#e8c547;margin-bottom:12px;}
.soros-subh{font-size:9px;font-weight:800;letter-spacing:0.18em;color:#94a3b8;margin:14px 0 8px;text-transform:uppercase;border-top:1px solid rgba(212,175,55,0.2);padding-top:12px;}
.soros-line{font-size:12px;color:#e8e4dc;line-height:1.55;margin-bottom:10px;font-family:'DM Mono',monospace;}
.soros-line .sl-main{display:block;color:#f5f0e6;font-weight:600;}
.soros-line .sl-sub{display:block;font-size:11px;color:#94a3b8;font-weight:400;margin-top:3px;}
.soros-line .sl-soros{display:block;font-size:10px;color:#fbbf24;margin-top:4px;font-weight:700;}
.soros-cmd{margin-top:16px;padding-top:14px;border-top:1px solid rgba(212,175,55,0.35);font-size:14px;font-weight:800;color:#f5e6a3;font-family:'Syne',sans-serif;}
.soros-upd{font-size:9px;color:#64748b;margin-top:8px;font-family:'DM Mono',monospace;}
.pf-line-compact{
  padding:8px 40px;font-family:'DM Mono',monospace;font-size:10px;color:var(--es-ink2);
  border-bottom:1px solid var(--es-rule);background:linear-gradient(90deg,#f8f7f3,#fff);
  white-space:normal;line-height:1.5;
}
.sector-min-warn{
  display:inline-block;margin-left:10px;padding:2px 8px;border-radius:4px;background:#fde8e8;color:#b91c1c;
  font-size:8px;font-weight:800;letter-spacing:0.06em;vertical-align:middle;
}
table.master.matrix-v2 thead th{font-size:8px;padding:8px 6px;}
table.master.matrix-v2 td{padding:7px 6px;vertical-align:middle;}
.mx-tk{font-family:'Syne',sans-serif;font-weight:700;font-size:11px;}
.mx-nm{font-size:9px;color:var(--es-ink4);max-width:140px;white-space:normal;line-height:1.25;}
.sec-badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:7px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#fff;}
.mx-godwrap{display:flex;align-items:center;gap:6px;justify-content:flex-end;}
.mx-godbar{width:40px;height:4px;background:var(--es-paper3);border-radius:2px;overflow:hidden;}
.mx-godfill{height:100%;border-radius:2px;}
.mx-en{font-family:'DM Mono',monospace;font-size:10px;color:var(--es-ink2);white-space:normal;max-width:200px;line-height:1.35;}
.mx-thesis{font-size:11px;font-weight:700;white-space:nowrap;}
.mx-sgap{font-family:'DM Mono',monospace;font-size:10px;color:var(--es-ink3);}
.mx-act{display:inline-block;padding:4px 10px;border-radius:6px;font-size:9px;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;font-family:'Syne',sans-serif;}
.mx-act-buy{background:#eaf4ee;color:#1a5c35;border:1px solid #1a5c35;}
.mx-act-add{background:#e8f5e9;color:#15803d;border:1px solid #15803d;}
.mx-act-hold{background:#fdf6e0;color:#854d0e;border:1px solid #ca8a04;}
.mx-act-trim{background:#fff7ed;color:#c2410c;border:1px solid #ea580c;}
.mx-act-exit{background:#fdf0f0;color:#991b1b;border:1px solid #dc2626;}
.mx-act-watch{background:#f4f4f5;color:#3f3f46;border:1px solid #a1a1aa;}
.mx-act-ipo{background:#f5eeff;color:#5b21b6;border:1px solid #7c3aed;}
.mx-tgt{font-family:'DM Mono',monospace;font-size:10px;font-weight:700;color:var(--es-ink2);}
"""

# (sector_key, band_title, band_desc, dot_css_var, rows)
# row: dict ticker, name, group port|watch|ipo, god, entry_disp, entry_num, entry_mode usd|krw|hkd|eur_from_usd, thesis intact|wounded|dead,
#      soros_pct optional float, soros_tgt str, action, target, tip
SECTOR_DOT = {
    "c1": "var(--c1)",
    "c2": "var(--c2)",
    "c3": "var(--c3)",
    "c4": "var(--c4)",
    "c5": "var(--c5)",
    "c6": "var(--c6)",
    "cr": "var(--c-radar)",
    "lk": "var(--locked)",
    "ex": "var(--exit)",
    "rd": "var(--radar)",
}

MATRIX = [
    ("intelligence", "Intelligence", "AGI · Quantum · Neural Interfaces · Advanced Memory · AI Hardware", "c1", [
        {"t": "000660.KS", "n": "SK Hynix", "g": "port", "god": 95, "ed": "₩85,000", "en": 85000, "em": "krw", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "HBM3E backbone of AGI — NEVER SELL."},
        {"t": "TSM", "n": "TSMC ADR", "g": "port", "god": 90, "ed": "€140", "en": 152, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "Foundry monopoly — N2 / CoWoS demand."},
        {"t": "PLTR", "n": "Palantir", "g": "port", "god": 72, "ed": "$109", "en": 109, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "Stop €95", "tip": "Defense + Maven — stop defines risk."},
        {"t": "1810.HK", "n": "Xiaomi", "g": "port", "god": 68, "ed": "HK$42", "en": 42, "em": "hkd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "EV + phones + IoT scale."},
        {"t": "NVDA", "n": "Nvidia", "g": "watch", "god": 96, "ed": "—", "en": 0, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "BUY", "tg": "Pullback", "tip": "Enter on correction — AGI compute layer."},
    ]),
    ("energy", "Energy", "Uranium · Nuclear Renaissance · Solid-State Batteries", "c2", [
        {"t": "UEC", "n": "Uranium Energy", "g": "port", "god": 78, "ed": "€11", "en": 11.9, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "€11 limit", "tip": "Burke Hollow / spot leverage thesis."},
        {"t": "URNM", "n": "Sprott Uranium ETF", "g": "port", "god": 74, "ed": "€72", "en": 77.8, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "Basket — structural uranium."},
        {"t": "CCJ", "n": "Cameco", "g": "watch", "god": 82, "ed": "—", "en": 0, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "BUY", "tg": "€105 at market", "tip": "Western producer — utility contracts."},
        {"t": "OKLO", "n": "Oklo Inc", "g": "watch", "god": 70, "ed": "—", "en": 0, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "BUY", "tg": "$57", "tip": "SMR + Meta power deal / NRC path."},
    ]),
    ("space", "Space / Logistics", "Orbital Infrastructure · Satellite Networks · Lunar Economy", "c3", [
        {"t": "PL", "n": "Planet Labs", "g": "port", "god": 84, "ed": "€28", "en": 28, "em": "eur_from_usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "NASA contract expansion 2026."},
        {"t": "RKLB", "n": "Rocket Lab", "g": "port", "god": 58, "ed": "€58", "en": 62.6, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "Neutron / NASA cadence."},
        {"t": "ASTS", "n": "AST SpaceMobile", "g": "watch", "god": 72, "ed": "—", "en": 0, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "WATCH", "tg": "—", "tip": "BlueBird / telco LEO."},
        {"t": "xAI", "n": "xAI Corp", "g": "ipo", "god": 88, "ed": "—", "en": 0, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "IPO", "tg": "S-1 H1", "tip": "Colossus cluster — IPO window."},
    ]),
    ("bio", "Bio-Engineering", "CRISPR · Base Editing · Longevity · AI Drug Discovery", "c4", [
        {"t": "TMO", "n": "Thermo Fisher", "g": "port", "god": 68, "ed": "€480", "en": 518, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "Instruments layer for gene editing labs."},
        {"t": "BEAM", "n": "Beam Therapeutics", "g": "watch", "god": 70, "ed": "—", "en": 0, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "BUY", "tg": "Limit", "tip": "Base editing — clinical milestones."},
        {"t": "NTLA", "n": "Intellia", "g": "watch", "god": 55, "ed": "—", "en": 0, "em": "usd", "th": "wounded", "sp": None, "st": "", "ac": "WATCH", "tg": "—", "tip": "Volatility — wait Phase 3 TTR."},
        {"t": "CRSP", "n": "CRISPR Tx", "g": "watch", "god": 48, "ed": "—", "en": 0, "em": "usd", "th": "wounded", "sp": None, "st": "", "ac": "TRIM", "tg": "<$40", "tip": "Dilution overhang — caution."},
    ]),
    ("robotics", "Robotics", "Humanoids · Autonomous Manufacturing · Defense Drones", "c5", [
        {"t": "272210.KS", "n": "Hanwha Systems", "g": "port", "god": 92, "ed": "₩45,000", "en": 45000, "em": "krw", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "K-defense — NEVER SELL."},
        {"t": "KTOS", "n": "Kratos Defense", "g": "port", "god": 80, "ed": "$80", "en": 80, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "Add $80", "tip": "Drones in conflict = revenue."},
        {"t": "ARKQ", "n": "ARK Autonomous ETF", "g": "port", "god": 62, "ed": "$55", "en": 55, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "Robotics basket exposure."},
        {"t": "BOTZ", "n": "Global X Robotics ETF", "g": "port", "god": 60, "ed": "$23", "en": 23, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "Humanoid / automation basket."},
        {"t": "Figure AI", "n": "Figure AI Inc", "g": "ipo", "god": 85, "ed": "—", "en": 0, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "IPO", "tg": "S-1", "tip": "Humanoid BMW deploy — IPO watch."},
    ]),
    ("infra", "Infrastructure", "Photonics · Data Center Power · Semiconductor Equipment", "c6", [
        {"t": "VRT", "n": "Vertiv", "g": "port", "god": 84, "ed": "$65", "en": 65, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "AI power / cooling hyperscale."},
        {"t": "COHR", "n": "Coherent", "g": "port", "god": 76, "ed": "€55", "en": 59.4, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "800G photonics / NVIDIA supply."},
        {"t": "AMAT", "n": "Applied Materials", "g": "watch", "god": 79, "ed": "—", "en": 0, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "BUY", "tg": "Chip capex", "tip": "Semi equipment — Hynix partner."},
    ]),
    ("radar_sec", "Global Issue Radar", "Food Security / Fertilizer · War premium · Review weekly", "cr", [
        {"t": "NTR", "n": "Nutrien", "g": "port", "god": 72, "ed": "€54", "en": 58.3, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "ADD", "tg": "Div", "tip": "War fertilizer / potash levered."},
        {"t": "FCX", "n": "Freeport-McMoRan", "g": "port", "god": 45, "ed": "$52", "en": 52, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "$54.50", "tip": "Kiwoom copper tactical — macro cycle."},
        {"t": "POSCO", "n": "POSCO Holdings", "g": "watch", "god": 65, "ed": "—", "en": 0, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "WATCH", "tg": "—", "tip": "ranto28 — Wolsong / H2 steel."},
    ]),
    ("radar8", "8 · RADAR", "Blog-detected names not in portfolio", "rd", []),
    ("locked", "Locked Position", "TR promotional gift — cannot sell ~1 year", "lk", [
        {"t": "MC.PA", "n": "LVMH", "g": "port", "god": 75, "ed": "Gift", "en": 0, "em": "gift", "th": "intact", "sp": None, "st": "", "ac": "HOLD", "tg": "—", "tip": "Locked TR gift — track only."},
    ]),
    ("tactical", "Tactical · Gold satellite", "Kiwoom / macro overlay — exit sleeve", "ex", [
        {"t": "IAU", "n": "iShares Gold ETF", "g": "port", "god": 30, "ed": "$175", "en": 175, "em": "usd", "th": "intact", "sp": None, "st": "", "ac": "EXIT", "tg": "Next rally", "tip": "Take profit on strength — redeploy."},
    ]),
]


def sort_rows(rows):
    order = {"port": 0, "watch": 1, "ipo": 2}

    def key(r):
        return (order.get(r["g"], 9), -r["god"])

    return sorted(rows, key=key)


def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def thesis_html(th):
    if th == "intact":
        return '<span class="mx-thesis" style="color:var(--buy);">Intact</span>'
    if th == "wounded":
        return '<span class="mx-thesis" style="color:var(--warn);">Wounded</span>'
    return '<span class="mx-thesis" style="color:var(--bear);">Dead</span>'


def action_class(ac):
    m = {
        "BUY": "mx-act-buy",
        "ADD": "mx-act-add",
        "HOLD": "mx-act-hold",
        "TRIM": "mx-act-trim",
        "EXIT": "mx-act-exit",
        "WATCH": "mx-act-watch",
        "IPO": "mx-act-ipo",
    }
    return m.get(ac, "mx-act-watch")


def build_table_html():
    parts = []
    parts.append('<div class="tbl-scroll">')
    parts.append('<table class="master matrix-v2">')
    parts.append(
        "<thead><tr>"
        "<th>Stock</th><th>Sector</th><th class=\"r\">GOD</th>"
        "<th class=\"r\">Entry Now</th><th>Thesis</th><th class=\"r\">Soros</th>"
        "<th>Action</th><th class=\"r\">Target</th>"
        "</tr></thead><tbody>"
    )
    for key, title, desc, dotk, rows in MATRIX:
        dot = SECTOR_DOT[dotk]
        nrow = len(rows)
        if key == "radar8":
            parts.append(
                f'<tr><td colspan="8" style="padding:0"><div class="cat-band">'
                f'<div class="cdot" style="background:{dot}"></div>'
                f'<div class="cname" style="color:{dot}">{esc(title)}</div>'
                f'<div class="cdesc">{esc(desc)}</div></div></td></tr>'
            )
            parts.append(
                '<tr class="rr"><td colspan="8" id="radar-matrix-compact" style="padding:10px 24px;font-family:\'DM Mono\',monospace;font-size:10px;color:var(--es-ink2);background:var(--radar-bg);">Loading blog signals</td></tr>'
            )
            continue
        warn = ""
        if key in ("intelligence", "energy", "space", "bio", "robotics", "infra", "radar_sec") and nrow < 5:
            warn = f'<span class="sector-min-warn">⚠️ {esc(title.split("·")[0].strip())} — only {nrow}/5 minimum — add watchlist position</span>'
        parts.append(
            f'<tr><td colspan="8" style="padding:0"><div class="cat-band">'
            f'<div class="cdot" style="background:{dot}"></div>'
            f'<div class="cname" style="color:{dot}">{esc(title)}</div>{warn}'
            f'<div class="cdesc">{esc(desc)}</div></div></td></tr>'
        )
        for r in sort_rows(rows):
            tid = r["t"].replace(".", "-")
            ac = r["ac"]
            sp = r["sp"]
            sgap = f"{sp:+.1f}%" if isinstance(sp, (int, float)) else "—"
            tip = esc(r["tip"])
            tslug = r["t"].replace(" ", "-")
            data_t = r["t"] if " " not in r["t"] else ""
            id_attr = f'id="price-{r["t"]}"' if " " not in r["t"] else ""
            price_cell = (
                f'<span class="pnow" {id_attr} data-ticker="{esc(data_t)}">—</span>' if data_t else "—"
            )
            en = r["en"]
            em = r["em"]
            parts.append(
                f'<tr class="mx-row" data-ticker="{esc(data_t)}" data-entry-num="{en}" data-entry-mode="{em}" '
                f'data-entry-disp="{esc(r["ed"])}" title="{tip}">'
                f'<td><div class="mx-tk">{esc(r["t"])}</div><div class="mx-nm">{esc(r["n"])}</div></td>'
                f'<td><span class="sec-badge" style="background:{dot}">{esc(title.split("/")[0].strip()[:14])}</span></td>'
                f'<td class="r"><div class="mx-godwrap"><div class="mx-godbar"><div class="mx-godfill" style="width:{r["god"]}%;background:{dot}"></div></div>'
                f'<span class="god-num">{r["god"]}</span></div></td>'
                f'<td class="r mx-en"><span class="mx-ed">{esc(r["ed"])}</span> → <span class="mx-nowwrap">{price_cell}</span>'
                f'<span class="mx-pct" style="display:block;font-size:9px;"></span></td>'
                f'<td>{thesis_html(r["th"])}</td>'
                f'<td class="r mx-sgap">{sgap}</td>'
                f'<td><span class="mx-act {action_class(ac)}">{esc(ac)}</span></td>'
                f'<td class="r mx-tgt">{esc(r["tg"])}</td>'
                f"</tr>"
            )
    parts.append("</tbody></table></div>")
    return "\n".join(parts)


FRAGMENT = f'''<div class="tab-panel active" id="tab-matrix" style="padding:0;background:var(--es-paper);">

<div class="soros-wrap">
  <div class="soros-card">
    <div class="soros-h">SOROS REFLEXIVITY PANEL</div>
    <div class="soros-subh">Inside portfolio</div>
    <div id="soros-inside-portfolio"><div class="soros-line sl-sub">Loading directives…</div></div>
    <div class="soros-subh">Outside portfolio · limits</div>
    <div id="soros-outside-portfolio"></div>
    <div id="soros-one-command" class="soros-cmd">⏳ Awaiting directives…</div>
    <div id="soros-updated" class="soros-upd"></div>
  </div>
</div>

<header class="masthead">
  <div>
    <div class="sys-name">OLYMPUS</div>
    <div class="sys-sub">OLYMPUS Unified · MINERVA Protocol · v7.0 · <span id="dashDate"></span> · Last data: <span id="lastUpdate">2026-04-12</span></div>
  </div>
  <div class="regime-block">
    <div class="regime-pill" id="hdr-regime-pill">⚠ FEAR ZONE — DEPLOY 50%</div>
    <div class="vix-num" id="hdr-vix-num">24.61</div>
    <div class="vix-label">VIX · Live</div>
  </div>
  <div class="masthead-right">
    <div class="meta-line">Composite Score: 54 / 100</div>
    <div class="meta-line">Environment: US–IRAN + FED WATCH</div>
    <div class="meta-line" style="margin-top:6px;font-size:9px;color:var(--ink4)">Upload morning screenshots → Minerva syncs live prices</div>
  </div>
</header>

<div class="alert-bar">
  <div class="alert-lbl">⚑ Alerts</div>
  <div class="alert-chip">🟡 OKLO $57 armed — Meta 1.2GW + NRC 2026</div>
  <div class="alert-chip">🟡 CCJ €105 market armed — uranium blue chip</div>
  <div class="alert-chip">🟡 UEC €11 armed — spot leverage</div>
  <div class="alert-chip">🔵 PLTR stop €95 — thesis intact</div>
  <div class="alert-chip">🟠 ASML April 16 — beat=buy, miss=wait</div>
  <div class="alert-chip">🟢 SpaceX IPO June 2026 — prepare capital</div>
  <div class="alert-chip">🟢 Anthropic IPO Oct 2026 — prepare capital</div>
</div>

<div id="pf-line-compact" class="pf-line-compact">
  TR: <strong id="pf-tr-n">—</strong> positions · Kiwoom: <strong id="pf-kw-n">—</strong> positions · Dry Powder: <strong>€1,500</strong> ·
  Active Limits: OKLO $57 · CCJ €105 market · UEC €11 · Next Catalyst: <strong>KTOS May 6</strong>
</div>

  <div style="font-size:9px;color:var(--es-ink4);font-family:'DM Mono',monospace;padding:6px 16px 0;letter-spacing:0.1em;" id="es-price-status">prices loading...</div>

  <div id="es-panel-matrix">
{build_table_html()}

<script>
(function() {{
  const EURUSD = 1.127;
  const TR_TICKERS = new Set(["TSM","PLTR","UEC","URNM","COHR","1810.HK","NTR","RKLB","PL","MC.PA"]);
  const KW_TICKERS = new Set(["000660.KS","272210.KS","ARKQ","BOTZ","VRT","FCX","IAU","KTOS"]);

  function firstNum(el) {{
    if (!el) return NaN;
    const t = (el.textContent || "").replace(/,/g, "");
    const m = t.match(/-?[\\d.]+/);
    return m ? parseFloat(m[0]) : NaN;
  }}

  function fmtPct(p) {{
    if (p == null || Number.isNaN(p)) return "";
    const c = p >= 0 ? "var(--buy)" : "var(--bear)";
    return '<span style="color:' + c + ';font-weight:800;">' + (p >= 0 ? "+" : "") + p.toFixed(1) + "%</span>";
  }}

  function updateMatrixV2Rows() {{
    document.querySelectorAll("tr.mx-row[data-ticker]").forEach(function (tr) {{
      const tk = tr.getAttribute("data-ticker");
      const mode = tr.getAttribute("data-entry-mode");
      const en = parseFloat(tr.getAttribute("data-entry-num") || "0");
      const ed = tr.getAttribute("data-entry-disp") || "";
      const pEl = document.getElementById("price-" + tk);
      const pctEl = tr.querySelector(".mx-pct");
      if (!pctEl) return;
      if (mode === "gift" || !en) {{
        pctEl.innerHTML = "";
        return;
      }}
      let live = firstNum(pEl);
      if (tk === "PL" && mode === "eur_from_usd" && !Number.isNaN(live)) {{
        const eur = live / EURUSD;
        const pct = ((eur - en) / en) * 100;
        pctEl.innerHTML = fmtPct(pct);
        return;
      }}
      if (mode === "krw") {{
        const raw = (pEl && pEl.textContent) ? pEl.textContent.replace(/,/g, "") : "";
        let v = NaN;
        const m = raw.match(/([\\d.]+)\\s*K/i);
        if (m) v = parseFloat(m[1]) * 1000;
        else v = parseFloat(raw.replace(/[^\\d.\\-]/g, "")) || NaN;
        if (!Number.isNaN(v) && en) pctEl.innerHTML = fmtPct(((v - en) / en) * 100);
        return;
      }}
      if (mode === "hkd") {{
        if (!Number.isNaN(live) && en) pctEl.innerHTML = fmtPct(((live - en) / en) * 100);
        return;
      }}
      if (!Number.isNaN(live) && en) pctEl.innerHTML = fmtPct(((live - en) / en) * 100);
    }});
  }}

  function updatePfCounts() {{
    const trN = document.getElementById("pf-tr-n");
    const kwN = document.getElementById("pf-kw-n");
    if (trN) trN.textContent = String(TR_TICKERS.size);
    if (kwN) kwN.textContent = String(KW_TICKERS.size);
  }}

  updatePfCounts();
  setTimeout(updateMatrixV2Rows, 400);
  setInterval(updateMatrixV2Rows, 30000);
  const mo = new MutationObserver(updateMatrixV2Rows);
  document.querySelectorAll(".pnow").forEach(function (el) {{
    mo.observe(el, {{ subtree: true, characterData: true, childList: true }});
  }});

  window.updateMatrixV2Rows = updateMatrixV2Rows;
  window.updatePortfolioSummaryBar = updatePfCounts;
  window.syncPlPortCardFromMatrix = function () {{}};
  window.updateVsNowMatrix = updateMatrixV2Rows;
}})();
</script>

  </div>
</div>

  <!-- Principles panel -->'''


def main():
    text = HTML.read_text(encoding="utf-8")

    # Remove global Decision Engine block
    de_pat = re.compile(
        r"\n<!-- DECISION ENGINE — first surface after header \+ nav \(directives\.json\) -->.*?"
        r"</div>\n</div>\n\n",
        re.DOTALL,
    )
    text, n = de_pat.subn("\n", text, count=1)
    if n != 1:
        raise SystemExit(f"Expected to remove 1 decision-engine block, removed {n}")

    # Insert CSS before </style>
    if ".soros-wrap" not in text:
        text = text.replace("::-webkit-scrollbar{width:3px;", CSS_INSERT + "\n::-webkit-scrollbar{width:3px;", 1)

    # Replace matrix tab body
    m = re.search(
        r'(<div class="tab-panel active" id="tab-matrix"[^>]*>)([\s\S]*?)(\n  <!-- Principles panel -->)',
        text,
    )
    if not m:
        raise SystemExit("tab-matrix block not found")
    text = text[: m.start()] + FRAGMENT + text[m.end() :]

    HTML.write_text(text, encoding="utf-8")
    print("OK: spliced Master Matrix v2 + removed global Decision Engine + CSS")


if __name__ == "__main__":
    main()
