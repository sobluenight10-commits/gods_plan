#!/usr/bin/env python3
import shutil

HTML_PATH = "/var/www/html/index.html"
with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

L08 = """<div class="lesson-item" style="border-left:3px solid #d4a017;padding:8px 12px;margin:4px 0;background:rgba(212,160,23,0.08)">
  <strong style="color:#d4a017">Lesson #08</strong>
  <em style="color:#888;margin:0 6px">Stop Breach = One Shot</em>
  <span style="font-size:12px">A stop breach is an INFORMATION EVENT, not a loss event. Thesis check first. INTACT &#8594; ARMED ONE SHOT (dip widened narrative gap = maximum conviction). WOUNDED &#8594; EXIT REVIEW. DEAD &#8594; EXIT NOW. The deeper the dip with intact thesis = the wider the Soros gap = the higher the conviction = most aggressive sizing.</span>
</div>"""

if "Lesson #08" in html or "Stop Breach = One Shot" in html:
    print("Lesson #08 already present — skip")
else:
    anchor = "<b>Lesson 06:</b>"
    idx = html.find(anchor)
    if idx == -1:
        print("ERROR: Lesson 06 anchor not found")
    else:
        end = html.find("</div>", idx)
        if end == -1:
            print("ERROR: no closing div after Lesson 06")
        else:
            html = html[: end + 6] + "\n" + L08 + html[end + 6 :]
            print("FIX 4b: Lesson #08 inserted after Lesson 06 block")
            with open(HTML_PATH, "w", encoding="utf-8") as f:
                f.write(html)
            shutil.copy2(HTML_PATH, "OLYMPUS_UNIFIED.html")
            print("Saved index.html and OLYMPUS_UNIFIED.html")
