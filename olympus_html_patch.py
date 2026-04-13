#!/usr/bin/env python3
"""Steps 6+7: dedupe INTELLIGENCE rows + GEM sub-row layout."""
import re

with open("OLYMPUS_UNIFIED.html", "r", encoding="utf-8") as f:
    html = f.read()

original_len = len(html)

html = re.sub(
    r'<tr[^>]*data-ticker=""[^>]*data-entry-mode="template"[^>]*>.*?</tr>\s*',
    "",
    html,
    flags=re.DOTALL,
)
html = re.sub(
    r'<tr[^>]*class="[^"]*sector-header-empty[^"]*"[^>]*>.*?</tr>\s*',
    "",
    html,
    flags=re.DOTALL,
)

removed = original_len - len(html)
print(f"Removed {removed} chars of duplicate rows")
print("Done")

old = "gemEl.style.cssText = 'margin-top:4px;font-size:11px;display:flex;gap:6px;flex-wrap:wrap;align-items:center';"
new = "gemEl.style.cssText = 'display:block;width:100%;padding:3px 0 4px 0;font-size:11px;border-top:1px solid rgba(0,0,0,0.06);margin-top:4px;clear:both;';"

if old in html:
    html = html.replace(old, new)
    print("GEM style patched")
else:
    print("Style pattern not found — check manually")

with open("OLYMPUS_UNIFIED.html", "w", encoding="utf-8") as f:
    f.write(html)