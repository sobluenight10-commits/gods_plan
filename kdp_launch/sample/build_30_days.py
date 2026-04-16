"""
Generate interior_30_days.html — template unchanged; only weekday + A/B/C aphorisms vary.

Aphorism source: ../quotes_src/*.txt (same merge rules as build_home_to_myself_quotes_master.py)
Book 1, days 1–30: global quote IDs 1–90 (Day N uses IDs (N-1)*3+1, (N-1)*3+2, (N-1)*3+3).

Run from repo root: python kdp_launch/sample/build_30_days.py
Or from this folder: python build_30_days.py
"""
from __future__ import annotations

import base64
import html
import re
from datetime import datetime, timezone
from pathlib import Path

WEEKDAYS = [
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
]

# Relative to kdp_launch/
FRAGMENTS = [
    ("quotes_src/001-180.txt", 1, 180),
    ("quotes_src/181-240.txt", 181, 240),
    ("quotes_src/241-360.txt", 241, 360),
    ("quotes_src/361-450.txt", 361, 450),
    ("quotes_src/451-540.txt", 451, 540),
    ("quotes_src/541-630.txt", 541, 630),
    ("quotes_src/631-720.txt", 631, 720),
    ("quotes_src/721-810.txt", 721, 810),
    ("quotes_src/811-900.txt", 811, 900),
    ("quotes_src/901-990.txt", 901, 990),
    ("quotes_src/991-1080.txt", 991, 1080),
]

KDP_LAUNCH = Path(__file__).resolve().parent.parent


def parse_file(path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    raw = path.read_text(encoding="utf-8")
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\d+)\s+(.+)$", line)
        if not m:
            m = re.match(r"^(\d+)\.\s*(.+)$", line)
        if not m:
            continue
        qid = int(m.group(1))
        text = m.group(2).strip()
        out[qid] = text
    return out


def load_merged_quotes() -> dict[int, str]:
    merged: dict[int, str] = {}
    for rel, lo, hi in FRAGMENTS:
        p = KDP_LAUNCH / rel
        if not p.exists():
            continue
        part = parse_file(p)
        for qid in range(lo, hi + 1):
            if qid in part:
                merged[qid] = part[qid]
    return merged


def quote_triple_for_day(
    merged: dict[int, str],
    day: int,
    book_start_id: int = 1,
    *,
    fallback: bool = False,
) -> tuple[str, str, str]:
    """Day 1..30 → quote IDs book_start_id + (day-1)*3 ... +2 (Book 1 = 1..90)."""
    base = book_start_id + (day - 1) * 3

    def one(qid: int) -> str:
        t = merged.get(qid)
        if not t:
            return f"[Quote #{qid} — add line to quotes_src in kdp_launch]"
        return html.escape(t)

    if not fallback:
        return one(base), one(base + 1), one(base + 2)

    # First 90 strings in global ID order (when 001-180.txt not present yet)
    flat = [merged[k] for k in sorted(merged.keys())]
    idx = (day - 1) * 3
    if idx + 2 >= len(flat):
        return (
            f"[Bank too small: need {idx + 3} quotes, have {len(flat)}]",
            "[—]",
            "[—]",
        )
    return html.escape(flat[idx]), html.escape(flat[idx + 1]), html.escape(flat[idx + 2])


def _png_data_uri(png_path: Path) -> str:
    b64 = base64.standard_b64encode(png_path.read_bytes()).decode("ascii")
    return f"url('data:image/png;base64,{b64}')"


# Placeholder __ART_BG__ = CSS background-image value (data URI embeds PNG once for portable HTML)
_CSS_TEMPLATE = r'''  <style>
    @page { size: 6in 9in; margin: 0; }
    * { box-sizing: border-box; }
    html { background: #333; }
    body {
      margin: 0;
      padding: 12px 0 24px;
      font-family: "Josefin Sans", "Segoe UI", sans-serif;
      color: #111;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }

    .day-sheet {
      width: 6in;
      min-height: 9in;
      margin: 0 auto 14px;
      background: #ffffff;
      position: relative;
      box-shadow: 0 8px 32px rgba(0,0,0,.35);
      page-break-after: always;
      overflow: hidden;
    }

    .day-top {
      padding: 0.32in 0.38in 0;
    }

    .day-art {
      min-height: 3.25in;
      margin: 0 0.22in 0.06in;
      background-color: #fafafa;
      background-image: __ART_BG__;
      background-size: 96% auto;
      background-repeat: no-repeat;
      background-position: center 8px;
    }

    .day-body {
      padding: 0.08in 0.38in 0.36in;
    }

    .head-row {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 0.12in;
      margin-bottom: 0.06in;
    }
    .head-title {
      font-family: "Cormorant Garamond", Georgia, serif;
      font-size: 10pt;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #9a7b3a;
      line-height: 1.2;
    }
    .head-meta {
      font-size: 7pt;
      color: #666;
      letter-spacing: 0.08em;
      margin-top: 2px;
    }
    .chk {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 13px;
      height: 13px;
      border: 1.5px solid #c62828;
      color: #c62828;
      font-size: 8px;
      flex-shrink: 0;
      margin-left: 0.06in;
    }
    .date-cell { min-width: 1.35in; }
    .date-cell label {
      font-size: 6.5pt;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #666;
      display: block;
      margin-bottom: 2px;
    }
    .date-line {
      border-bottom: 1px solid #333;
      min-height: 0.14in;
    }

    .gold-rule {
      border: none;
      border-top: 1px solid #c5a059;
      margin: 0.08in 0 0.09in;
    }

    .block { margin-bottom: 0.07in; }
    .block-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 0.04in;
    }
    .block-label { display: flex; flex-direction: column; gap: 1px; }
    .letter {
      font-family: "Cormorant Garamond", Georgia, serif;
      font-size: 14pt;
      font-weight: 700;
      color: #8b6914;
      line-height: 1;
    }
    .aph-sub {
      font-family: "Great Vibes", cursive;
      font-size: 11pt;
      color: #3d3d3d;
      margin-top: 2px;
    }

    .block-body { display: flex; gap: 0.07in; align-items: stretch; }
    .quote-col {
      flex: 0 1 31%;
      max-width: 31%;
      min-width: 0;
    }
    .quote-bold {
      font-family: "Josefin Sans", sans-serif;
      font-size: 8pt;
      font-weight: 700;
      line-height: 1.4;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      margin: 0;
      padding-top: 0.04in;
      color: #000;
    }

    .journal-box {
      flex: 1 1 69%;
      min-width: 0;
      border: 2px solid #000;
      padding: 0.07in 0.12in 0.09in;
      background: rgba(255,255,255,0.96);
    }
    .final-wrap .journal-box.journal-full {
      flex: 1 1 100%;
      max-width: 100%;
    }
    .journal-box .lbl {
      font-size: 6.5pt;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #111;
      margin: 0.04in 0 0.03in;
    }
    .journal-box .lbl:first-child { margin-top: 0; }

    .ruled {
      font-size: 9pt;
      line-height: 1.22em;
      min-height: calc(1.22em * var(--rows, 1));
      color: transparent;
      background-image: repeating-linear-gradient(
        to bottom,
        #000000 0,
        #000000 1px,
        transparent 1px,
        transparent 1.22em
      );
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }

    .final-wrap {
      margin-top: 0.06in;
      padding-top: 0.07in;
      border-top: 1px solid #c5a059;
    }
    .final-wrap .block-body {
      display: block;
      width: 100%;
    }
    .moon { font-size: 12pt; opacity: 0.5; margin-left: 0.04in; }
    .night-line {
      font-family: "Cormorant Garamond", serif;
      font-size: 8pt;
      font-style: italic;
      color: #555;
      margin: 0.04in 0 0;
      line-height: 1.3;
    }

    .footer {
      text-align: center;
      font-size: 6.5pt;
      letter-spacing: 0.05em;
      color: #999;
      margin-top: 0.1in;
      padding-top: 0.06in;
      border-top: 1px solid #c5a059;
    }
    .leaf { color: #c5a059; opacity: 0.6; }

    @media print {
      html { background: #fff; }
      body { padding: 0; }
      .day-sheet { margin: 0; box-shadow: none; page-break-after: always; }
    }
  </style>'''


def build_css(art_background: str) -> str:
    """Embed PNG as data URI so opening HTML from any path still shows art."""
    return _CSS_TEMPLATE.replace("__ART_BG__", art_background)


def day_block(n: int, qa: str, qb: str, qc: str) -> str:
    wd = WEEKDAYS[(n - 1) % 7]
    return f'''
    <article class="day-sheet" id="day-{n}">
      <div class="day-top">
        <div class="head-row">
          <div>
            <div>
              <span class="head-title">[{wd}]: A SACRED RECLAMATION</span>
              <span class="chk">&#10003;</span>
            </div>
            <div class="head-meta">Day {n} of 30</div>
          </div>
          <div class="date-cell">
            <label>Date</label>
            <div class="date-line"></div>
          </div>
        </div>
        <hr class="gold-rule" />
      </div>
      <div class="day-art" role="img" aria-label=""></div>
      <div class="day-body">
        <section class="block">
          <div class="block-top">
            <div class="block-label">
              <span class="letter">A</span>
              <span class="aph-sub">morning &mdash; The Release</span>
            </div>
            <span class="chk">&#10003;</span>
          </div>
          <div class="block-body">
            <div class="quote-col"><p class="quote-bold">{qa}</p></div>
            <div class="journal-box">
              <div class="lbl">My thoughts</div>
              <div class="ruled" style="--rows:2"></div>
              <div class="lbl">My implementation plan</div>
              <div class="ruled" style="--rows:2"></div>
            </div>
          </div>
          <hr class="gold-rule" />
        </section>

        <section class="block">
          <div class="block-top">
            <div class="block-label">
              <span class="letter">B</span>
              <span class="aph-sub">afternoon &mdash; The Radical Center</span>
            </div>
            <span class="chk">&#10003;</span>
          </div>
          <div class="block-body">
            <div class="quote-col"><p class="quote-bold">{qb}</p></div>
            <div class="journal-box">
              <div class="lbl">My thoughts</div>
              <div class="ruled" style="--rows:2"></div>
              <div class="lbl">My implementation plan</div>
              <div class="ruled" style="--rows:2"></div>
            </div>
          </div>
          <hr class="gold-rule" />
        </section>

        <section class="block">
          <div class="block-top">
            <div class="block-label">
              <span class="letter">C</span>
              <span class="aph-sub">evening &mdash; Welcome Home</span>
            </div>
            <span class="chk">&#10003;</span>
          </div>
          <div class="block-body">
            <div class="quote-col"><p class="quote-bold">{qc}</p></div>
            <div class="journal-box">
              <div class="lbl">My thoughts</div>
              <div class="ruled" style="--rows:2"></div>
              <div class="lbl">My implementation plan</div>
              <div class="ruled" style="--rows:2"></div>
            </div>
          </div>
          <hr class="gold-rule" />
        </section>

        <section class="final-wrap">
          <div class="block-top">
            <div class="block-label">
              <span class="letter">D</span>
              <span class="aph-sub">Your aphorism &mdash; good night<span class="moon">&#9790;</span></span>
            </div>
            <span class="chk">&#10003;</span>
          </div>
          <p class="night-line">Close the day in your own words. Let this be the line you carry into sleep.</p>
          <div class="block-body" style="margin-top:0.06in">
            <div class="journal-box journal-full">
              <div class="lbl">Why this aphorism</div>
              <div class="ruled" style="--rows:2"></div>
              <div class="lbl">My implement this</div>
              <div class="ruled" style="--rows:2"></div>
            </div>
          </div>
        </section>

        <div class="footer">
          <span class="leaf">&#10086;</span>
          &nbsp; THIS BOOK IS ONLY FOR ME &nbsp;|&nbsp; Kai Greatwhite &nbsp;|&nbsp; Day {n} / 30
          &nbsp; <span class="leaf">&#10086;</span>
        </div>
      </div>
    </article>
'''


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build 30-day interior HTML from quote bank.")
    parser.add_argument(
        "--fallback",
        action="store_true",
        help="Force bank-order fill (first 90 lines by ID) even when quotes 1–3 exist.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require quote IDs 1–90; do not fall back (HTML will show [Quote #…] gaps).",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    out = root / "interior_30_days.html"
    png = root / "assets" / "umbrella-woman.png"
    if png.is_file():
        art_bg = _png_data_uri(png)
        print(f"Embedded art: {png.name} ({png.stat().st_size // 1024} KB)")
    else:
        art_bg = "linear-gradient(180deg, #f5f5f5, #ffffff)"
        print("WARN: assets/umbrella-woman.png missing — using plain gradient")

    build_id = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    merged = load_merged_quotes()
    populated = len(merged)
    print(f"Loaded {populated} quote lines from kdp_launch/quotes_src")

    book1_ok = all(merged.get(i) for i in range(1, 91))
    if args.strict:
        use_fallback = False
    elif args.fallback:
        use_fallback = True
    else:
        # Auto: real Book 1 mapping when 001-180.txt supplies IDs 1–90; else use bank order (181+…)
        use_fallback = not book1_ok
        if use_fallback:
            print(
                "Note: quotes 1-90 not all present - using first 90 lines in global ID order. "
                "Add kdp_launch/quotes_src/001-180.txt for true Book 1 text, then rebuild."
            )

    mode = "strict Book 1 (IDs 1–90)" if not use_fallback else "bank order: first 90 quotes by ID (until 001-180.txt added)"
    parts = [
        "<!DOCTYPE html>",
        f"<!-- build {build_id} | {mode} | art embedded | gold header -->",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8" />',
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
        '  <meta http-equiv="Cache-Control" content="no-cache" />',
        "  <title>HOME TO MYSELF — 30 days (Book 1)</title>",
        '  <link rel="preconnect" href="https://fonts.googleapis.com" />',
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />',
        '  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,400&family=Great+Vibes&family=Josefin+Sans:wght@400;600;700&display=swap" rel="stylesheet" />',
        build_css(art_bg),
        "</head>",
        "<body>",
    ]
    missing_any = False
    for n in range(1, 31):
        qa, qb, qc = quote_triple_for_day(merged, n, book_start_id=1, fallback=use_fallback)
        if "Quote #" in qa or "Bank too small" in qa:
            missing_any = True
        parts.append(day_block(n, qa, qb, qc))
    body = "\n".join(parts)
    if missing_any and not use_fallback:
        body = "<!-- WARNING: missing some IDs 1–90 — add quotes_src/001-180.txt -->\n" + body
    body += "\n</body>\n</html>\n"
    out.write_text(body, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
