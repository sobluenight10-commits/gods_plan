# -*- coding: utf-8 -*-
"""One-off patch for OLYMPUS_UNIFIED.html FINAL v7.0 — run from gods_plan root."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "OLYMPUS_UNIFIED.html"
text = path.read_text(encoding="utf-8")

# ── Global string replacements ─────────────────────────────────────────────
repls = [
    ("2036", "2031"),
    ("ISLAND MISSION 2036", "ISLAND MISSION 2031"),
    ("v6.0", "v7.0"),
    ("Last data: 2026-04-09", "Last data: 2026-04-12"),
    ("OPENCLAW", "MINERVA"),
]
for a, b in repls:
    text = text.replace(a, b)

# ── Tab nav: 3 tabs only ───────────────────────────────────────────────────
old_nav = """<!-- TAB NAV -->
<div class="tab-nav">
  <button class="tab-btn active"   onclick="showTab('mission')">🏝️ ISLAND MISSION</button>
  <button class="tab-btn"          onclick="showTab('earthshifters')" style="color:#1e3a6e;font-weight:700;">🌍 §13 EARTH SHIFTERS</button>
  <button class="tab-btn liq-tab"  onclick="showTab('liquidity')">⚡ §11 LIQUIDITY</button>
  <button class="tab-btn"          onclick="showTab('tuition')">📖 TUITION LOG</button>
  <button class="tab-btn"          onclick="showTab('telegram')">📱 TELEGRAM</button>
</div>"""

new_nav = """<!-- TAB NAV -->
<div class="tab-nav">
  <button class="tab-btn active"   onclick="showTab('matrix')">MASTER MATRIX</button>
  <button class="tab-btn"          onclick="showTab('principles')">10 PRINCIPLES</button>
  <button class="tab-btn"          onclick="showTab('telegram')">TELEGRAM</button>
</div>"""

if old_nav not in text:
    raise SystemExit("TAB NAV block not found")
text = text.replace(old_nav, new_nav, 1)

# ── Remove Island Mission tab panel ────────────────────────────────────────
mission_start = '<!-- ═══════════════════════════════════ -->\n<!-- TAB: ISLAND MISSION                -->\n<!-- ═══════════════════════════════════ -->\n<div class="tab-panel active" id="tab-mission">'
mission_end = '<!-- ═══════════════════════════════════ -->\n<!-- TAB: PORTFOLIO                     -->'
i0 = text.find(mission_start)
i1 = text.find(mission_end)
if i0 == -1 or i1 == -1 or i1 <= i0:
    raise SystemExit("Mission tab boundaries not found")
text = text[:i0] + mission_end + text[i1 + len(mission_end) :]

# ── Earth tab → matrix (not active until we set active on matrix) ────────
text = text.replace(
    '<div class="tab-panel" id="tab-earthshifters" style="padding:0;background:var(--es-paper);">',
    '<div class="tab-panel active" id="tab-matrix" style="padding:0;background:var(--es-paper);">',
    1,
)

# ── Remove inner es-inner-nav row ──────────────────────────────────────────
inner_nav = """  <!-- Inner sub-navigation -->
  <div style="font-size:9px;color:var(--es-ink4);font-family:'DM Mono',monospace;padding:6px 16px 0;letter-spacing:0.1em;" id="es-price-status">prices loading...</div>
  <div class="es-inner-nav">
    <button class="es-tab active" onclick="esShowTab('matrix', this)">Master Matrix</button>
    <button class="es-tab" onclick="esShowTab('wednesday', this)">📅 Wed Review</button>
    <button class="es-tab" onclick="esShowTab('bubble', this)">Bubble Chart</button>
    <button class="es-tab" onclick="esShowTab('regime', this)">Regime / VIX</button>
    <button class="es-tab" onclick="esShowTab('principles', this)">10 Principles</button>
  </div>
"""
if inner_nav not in text:
    raise SystemExit("es-inner-nav block not found")
text = text.replace(inner_nav, """  <div style="font-size:9px;color:var(--es-ink4);font-family:'DM Mono',monospace;padding:6px 16px 0;letter-spacing:0.1em;" id="es-price-status">prices loading...</div>
""", 1)

# ── Matrix panel: remove id es-panel-matrix wrapper class juggling ─────────
# Keep single visible matrix: change opening div to not use es-panel (tabs removed)
text = text.replace(
    '<div id="es-panel-matrix" class="es-panel active">',
    '<div id="es-panel-matrix">',
    1,
)

# ── Cut Wednesday + Bubble + Regime panels ─────────────────────────────────
marker_a = "  <!-- Bubble panel -->\n\n  <!-- ═══ WEDNESDAY SECTOR REVIEW ═══ -->"
marker_b = "  <!-- Principles panel -->\n  <!-- ═══ PRINCIPLES ═══ -->"
ja = text.find(marker_a)
jb = text.find(marker_b)
if ja == -1 or jb == -1 or jb <= ja:
    raise SystemExit("Wednesday/Principles markers not found")
text = text[:ja] + text[jb:]

# ── Remove erroneous early </body></html> ─────────────────────────────────
early = "\n</body>\n</html>\n\n\n<!-- ═══════════════════════════════════ -->\n\n<div class=\"tab-panel\" id=\"tab-liquidity\">"
if early in text:
    text = text.replace(early, "\n\n<!-- ═══════════════════════════════════ -->\n\n<div class=\"tab-panel\" id=\"tab-liquidity\">", 1)

# ── Remove liquidity + tuition tab panels entirely ─────────────────────────
liq_start = '<div class="tab-panel" id="tab-liquidity">'
tui_start = '<div class="tab-panel" id="tab-tuition">'
tg_start = '<div class="tab-panel" id="tab-telegram">'
lq = text.find(liq_start)
tu = text.find(tui_start)
tg = text.find(tg_start)
if -1 in (lq, tu, tg) or not (lq < tu < tg):
    raise SystemExit("Liquidity/tuition/telegram order not found")
text = text[:lq] + text[tg:]

# ── Wrap principles: replace es-panel-principles with tab-principles ───────
text = text.replace(
    '<div id="es-panel-principles" class="es-panel">',
    """<div class="tab-panel" id="tab-principles">
<button type="button" id="principles-toggle" class="principles-toggle-btn" onclick="document.getElementById('principles-inner').classList.toggle('open');this.setAttribute('aria-expanded', document.getElementById('principles-inner').classList.contains('open')?'true':'false');" aria-expanded="false">10 PRINCIPLES — click to expand ▾</button>
<div id="principles-inner" class="principles-collapsed">
<div id="es-panel-principles-inner">""",
    1,
)
# Close extra wrappers before ARTICLE X section end — find closing of principles-section inner div
# Original ends with </div>\n</div>\n\n</div>\n\n</div> before footer — fragile; patch closing after ARTICLE X block
old_pr_close = """  </div>

</div>
</div>

</div>

</body>"""
new_pr_close = """  </div>

</div>
</div>
</div>

</div>

</body>"""
if old_pr_close not in text:
    # try alternate (single newline variants)
    old_pr_close = old_pr_close.replace("\n\n", "\n")
if old_pr_close not in text:
    raise SystemExit("Principles close / body not found for wrap")
text = text.replace(old_pr_close, new_pr_close, 1)

# ── Decision Engine HTML block ───────────────────────────────────────────────
old_de = """<!-- DECISION ENGINE — first surface after header + nav (directives.json) -->
<div class="decision-engine-hero-wrap" id="decision-engine-anchor">
  <div class="decision-engine-card">
    <div class="de-h">🎯 DECISION ENGINE</div>
    <div id="de-one-command" class="de-command">⏳ Awaiting next brief — 07:00 Berlin</div>
    <div id="de-deploy" class="de-deploy" style="display:none;"></div>
    <div id="de-updated" class="de-updated"></div>
    <ul id="de-actions" class="de-actions"></ul>
  </div>
</div>"""

new_de = """<!-- DECISION ENGINE — first surface after header + nav (directives.json) -->
<div class="decision-engine-hero-wrap" id="decision-engine-anchor">
  <div class="decision-engine-card">
    <div class="de-h">🎯 DECISION ENGINE</div>
    <div id="de-one-command" class="de-command">⏳ Awaiting next brief — 07:00 Berlin</div>
    <ul id="de-actions" class="de-actions"></ul>
    <div class="de-subh">DEPLOYMENT PLAN</div>
    <div id="de-deployment" class="de-deployment"></div>
    <div id="de-updated" class="de-updated"></div>
  </div>
</div>"""

if old_de not in text:
    raise SystemExit("Decision engine block not found")
text = text.replace(old_de, new_de, 1)

# ── Alert chips ────────────────────────────────────────────────────────────
old_alerts = """  <div class="alert-chip">OKLO limit $44 active — SMR + Meta deal — 5Y hold</div>
  <div class="alert-chip">CCJ limit $100 active — uranium blue chip</div>
  <div class="alert-chip">UEC limit €11 active — spot leverage add</div>
  <div class="alert-chip">PLTR stop €95 — hold above this level</div>
  <div class="alert-chip">ASML April 16 earnings — decision point</div>
  <div class="alert-chip">SpaceX IPO June 2026 — prepare capital</div>
  <div class="alert-chip">Anthropic IPO October 2026 — prepare capital</div>"""

new_alerts = """  <div class="alert-chip">🟡 OKLO $44 armed — Meta 1.2GW + NRC 2026</div>
  <div class="alert-chip">🟡 CCJ $100 armed — uranium blue chip</div>
  <div class="alert-chip">🟡 UEC €11 armed — spot leverage</div>
  <div class="alert-chip">🔵 PLTR stop €95 — thesis intact</div>
  <div class="alert-chip">🟠 ASML April 16 — beat=buy, miss=wait</div>
  <div class="alert-chip">🟢 SpaceX IPO June 2026 — prepare capital</div>
  <div class="alert-chip">🟢 Anthropic IPO Oct 2026 — prepare capital</div>"""

if old_alerts not in text:
    raise SystemExit("Alert chips block not found")
text = text.replace(old_alerts, new_alerts, 1)

# ── PL row: add Track B pill in tsym cell ───────────────────────────────────
text = text.replace(
    '<td><div class="tsym">PL</div><div class="tname">Planet Labs PBC</div></td>\n  <td><span class="badge b-port">Portfolio</span></td>\n  <td><span class="spear-badge">⚔ SPEAR</span></td>',
    '<td><div class="tsym">PL</div><div class="tname">Planet Labs PBC <span class="track-pill track-b" title="Track B — paradigm / inflection">B</span></div></td>\n  <td><span class="badge b-port">Portfolio</span></td>\n  <td><span class="spear-badge">⚔ SPEAR</span></td>',
    1,
)
text = text.replace(
    "Hold. Satellite imagery = AI data layer. NASA contract.",
    "HOLD. Satellite imagery = AI data layer. NASA contract expansion 2026.",
    1,
)

# ── SECTORS heatmap: Bio label + TMO; Infrastructure remove FCX if present ─
text = text.replace(
    '{ name:"Bio",          dot:"#1a4f4f", tickers:["CRSP","NTLA","BEAM","TMO"] },',
    '{ name:"Bio-Engineering", dot:"#1a4f4f", tickers:["CRSP","NTLA","BEAM","TMO"] },',
    1,
)
text = text.replace(
    '{ name:"Infrastructure", dot:"#1e3050", tickers:["COHR","VRT","FCX","LVMH"] },',
    '{ name:"Infrastructure", dot:"#1e3050", tickers:["COHR","VRT","LVMH"] },',
    1,
)

# ── Fix UEC row wrong price id (NVDA typo) ───────────────────────────────────
text = text.replace(
    '<td class="r"><span class="pnow" id="price-NVDA" data-ticker="NVDA">$12.09</span></td>',
    '<td class="r"><span class="pnow" id="price-UEC" data-ticker="UEC">$12.09</span></td>',
    1,
)

# ── injectTrackBadges tickers list: remove IONQ if present ───────────────────
text = text.replace(
    '"000660.KS", "272210.KS", "ARKQ", "BOTZ", "VRT", "IAU", "KTOS", "PL", "FCX",',
    '"000660.KS", "272210.KS", "ARKQ", "BOTZ", "VRT", "IAU", "KTOS", "PL", "FCX",',
    1,
)

path.write_text(text, encoding="utf-8")
print("OK: base structural patch applied — run loadDecisionEngine CSS patch next")
