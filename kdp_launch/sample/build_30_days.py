"""
Generate interior_30_days.html from the umbrella-woman template.
Run: python build_30_days.py
"""
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

CSS = r'''  <style>
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
      text-align: center;
      padding: 0.28in 0.35in 0.12in;
      background: linear-gradient(180deg, #fafafa 0%, #fff 100%);
    }
    .day-art img {
      max-width: 88%;
      max-height: 2.35in;
      width: auto;
      height: auto;
      display: block;
      margin: 0 auto;
      object-fit: contain;
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
      color: #1a1a1a;
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

    .block-body { display: flex; gap: 0.08in; align-items: stretch; }
    .quote-col {
      flex: 0 1 38%;
      max-width: 38%;
      min-width: 0;
    }
    .quote-bold {
      font-family: "Josefin Sans", sans-serif;
      font-size: 7.5pt;
      font-weight: 700;
      line-height: 1.4;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      margin: 0;
      padding-top: 0.04in;
      color: #000;
    }

    .journal-box {
      flex: 1 1 62%;
      min-width: 0;
      border: 1px solid #000;
      padding: 0.06in 0.1in 0.08in;
      background: rgba(255,255,255,0.92);
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
      line-height: 1.18em;
      min-height: calc(1.18em * var(--rows, 1));
      color: transparent;
      background-image: repeating-linear-gradient(
        to bottom,
        #000000 0,
        #000000 1px,
        transparent 1px,
        transparent 1.18em
      );
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }

    .final-wrap {
      margin-top: 0.06in;
      padding-top: 0.07in;
      border-top: 1px solid #c5a059;
    }
    .final-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 0.05in;
    }
    .final-h {
      font-family: "Great Vibes", cursive;
      font-size: 15pt;
      color: #222;
      margin: 0;
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
      border-top: 1px solid #e0e0e0;
    }
    .leaf { color: #c5a059; opacity: 0.6; }

    @media print {
      html { background: #fff; }
      body { padding: 0; }
      .day-sheet { margin: 0; box-shadow: none; page-break-after: always; }
    }
  </style>'''

QUOTES_A = [
    "You are not a backup plan for your own life.",
    "Your needs are not an inconvenience.",
    "You survived every hard day before this one.",
] * 10  # 30 days - rotate or use same 3 per day cycle for template

def day_block(n: int) -> str:
    wd = WEEKDAYS[(n - 1) % 7]
    # Placeholder quotes cycle (template — replace in production)
    qa = QUOTES_A[(n - 1) % 3]
    qb = QUOTES_A[(n) % 3]
    qc = QUOTES_A[(n + 1) % 3]
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
      <div class="day-art">
        <img src="assets/umbrella-woman.png" alt="" width="900" />
      </div>
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
              <div class="ruled" style="--rows:1"></div>
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
              <div class="ruled" style="--rows:1"></div>
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
              <div class="ruled" style="--rows:1"></div>
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
            <div class="quote-col"></div>
            <div class="journal-box">
              <div class="lbl">Why this aphorism</div>
              <div class="ruled" style="--rows:1"></div>
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

def main():
    root = Path(__file__).resolve().parent
    out = root / "interior_30_days.html"
    parts = [
        "<!DOCTYPE html>",
        "<!-- 30-day interior — generated by build_30_days.py; art: assets/umbrella-woman.png -->",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8" />',
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
        "  <title>HOME TO MYSELF — 30 days (template)</title>",
        '  <link rel="preconnect" href="https://fonts.googleapis.com" />',
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />',
        '  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,400&family=Great+Vibes&family=Josefin+Sans:wght@400;600;700&display=swap" rel="stylesheet" />',
        CSS,
        "</head>",
        "<body>",
        '  <p style="text-align:center;font-size:6pt;color:#888;margin:8px">Template: 30 pages &middot; Print: Save as PDF &middot; 6&times;9 in</p>',
    ]
    for n in range(1, 31):
        parts.append(day_block(n))
    parts.extend(["</body>", "</html>"])
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
