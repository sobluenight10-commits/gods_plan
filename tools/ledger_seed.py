"""
ledger_seed.py — one-time seed of thesis_ledger from current OLYMPUS matrix.

Parses OLYMPUS_UNIFIED.html portfolio rows and inserts BUY decisions with:
  - Entry price (native currency, from data-entry-num)
  - Thesis (from title attribute on the <tr>)
  - Sector-derived thesis_type
  - GOD score → conviction mapping (GOD/10 rounded, min 5)

Idempotent — skips tickers that already have an open decision.
"""
from __future__ import annotations
import os, re, sys
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from thesis_ledger import add_decision, list_open  # noqa: E402

HTML = os.path.join(BASE, "OLYMPUS_UNIFIED.html")

SECTOR_TO_TYPE = {
    "Intelligence": "ai_infra",
    "Energy":       "energy_uranium",
    "Space":        "space_defense",
    "Robotics":     "robotics_defense",
    "Bio-Engineerin": "biotech",
    "Materials":    "materials",
    "Semis":        "semis",
}

ROW_RE = re.compile(
    r'<tr class="mx-row mx-st-pf" '
    r'data-ticker="([^"]+)" '
    r'data-entry-num="([^"]+)" '
    r'data-entry-mode="([^"]+)" '
    r'data-thesis="([^"]*)" '
    r'title="([^"]*)"',
    re.DOTALL,
)
GOD_RE = re.compile(r'<span class="god-num">(\d+)</span>')
SECTOR_RE = re.compile(r'<span class="sec-badge"[^>]*>([^<]+)</span>')


def main() -> int:
    html = Path(HTML).read_text(encoding="utf-8", errors="ignore")

    # Find all <tr ...> blocks for portfolio rows then split per ticker
    rows = []
    for m in ROW_RE.finditer(html):
        tk, entry, mode, thesis_status, title = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        # Find end of this <tr> (next </tr>)
        tail_start = m.end()
        tail_end = html.find("</tr>", tail_start)
        tail = html[tail_start:tail_end] if tail_end > -1 else ""
        god_m = GOD_RE.search(tail)
        sec_m = SECTOR_RE.search(tail)
        rows.append({
            "ticker": tk,
            "entry": float(entry) if entry else None,
            "mode": mode,
            "thesis_status": thesis_status,
            "title": title.strip(),
            "god": int(god_m.group(1)) if god_m else 50,
            "sector": sec_m.group(1).strip() if sec_m else "",
        })

    # Skip tickers with existing open decisions
    open_set = {r["ticker"] for r in list_open()}
    new = 0
    for r in rows:
        if r["ticker"] in open_set:
            print(f"  [skip] {r['ticker']} (already open)")
            continue
        conv = max(5, min(10, round(r["god"] / 10)))
        ttype = SECTOR_TO_TYPE.get(r["sector"], "general")
        thesis = r["title"] or f"Portfolio position — GOD {r['god']}"
        add_decision(
            r["ticker"],
            "BUY",
            r["entry"] or 0.0,
            thesis=thesis,
            catalyst="",
            horizon="3Y",
            conviction=conv,
            thesis_type=ttype,
            exit_criteria="Thesis breach or price target reached",
        )
        print(f"  [+] seeded {r['ticker']} @ {r['entry']} ({r['mode']}) conv={conv} type={ttype}")
        new += 1
    print(f"\n[seed] {new} new decisions added; {len(open_set)} already open.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
