"""
Generate interior_30_days.html — one page per day: header (weekday + date) + hero art + footer.
Journal blocks A–D are omitted by design.

Run from repo root: python kdp_launch/sample/build_30_days.py
Or from this folder: python build_30_days.py
"""
from __future__ import annotations

import base64
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
      display: flex;
      flex-direction: column;
    }

    .day-top {
      padding: 0.32in 0.38in 0;
    }

    .day-art {
      flex: 1 1 auto;
      min-height: 3.25in;
      margin: 0 0.22in 0.06in;
      background-color: #fafafa;
      background-image: __ART_BG__;
      background-size: 96% auto;
      background-repeat: no-repeat;
      background-position: center 8px;
    }

    .day-body {
      flex-shrink: 0;
      padding: 0.12in 0.38in 0.36in;
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


def day_block(n: int) -> str:
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
        <div class="footer">
          <span class="leaf">&#10086;</span>
          &nbsp; THIS BOOK IS ONLY FOR ME &nbsp;|&nbsp; Kai Greatwhite &nbsp;|&nbsp; Day {n} / 30
          &nbsp; <span class="leaf">&#10086;</span>
        </div>
      </div>
    </article>
'''


def main() -> None:
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
    parts = [
        "<!DOCTYPE html>",
        f"<!-- build {build_id} | header + hero art; sections A–D omitted -->",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8" />',
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
        '  <meta http-equiv="Cache-Control" content="no-cache" />',
        "  <title>HOME TO MYSELF — 30 days (Book 1)</title>",
        '  <link rel="preconnect" href="https://fonts.googleapis.com" />',
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />',
        '  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,400&family=Josefin+Sans:wght@400;600;700&display=swap" rel="stylesheet" />',
        build_css(art_bg),
        "</head>",
        "<body>",
    ]
    for n in range(1, 31):
        parts.append(day_block(n))
    body = "\n".join(parts) + "\n</body>\n</html>\n"
    out.write_text(body, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
