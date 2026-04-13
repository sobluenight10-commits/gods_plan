with open("OLYMPUS_UNIFIED.html", "r", encoding="utf-8") as f:
    html = f.read()

DUPE = '<tr><td colspan="15" style="padding:0"><div class="cat-band"><div class="cdot" style="background:var(--c1)"></div><div class="cname" style="color:var(--c1)">Intelligence</div><div class="cdesc">AGI · Quantum · Neural Interfaces · Advanced Memory · AI Hardware</div></div></td></tr>'

count = html.count(DUPE)
print(f"Found {count} INTELLIGENCE headers")

if count > 1:
    html = html.replace(DUPE, "", count)
    marker = 'data-ticker="000660.KS"'
    idx = html.find(marker)
    if idx != -1:
        tr_start = html.rfind("<tr", 0, idx)
        html = html[:tr_start] + DUPE + "\n" + html[tr_start:]
        print("Reinserted 1 header before 000660.KS")
    print(f"After: {html.count(DUPE)} headers remain")
else:
    print("Already correct — no change needed")

with open("OLYMPUS_UNIFIED.html", "w", encoding="utf-8") as f:
    f.write(html)
print("Saved")
