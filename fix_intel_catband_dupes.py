with open('OLYMPUS_UNIFIED.html', 'r', encoding='utf-8') as f:
    html = f.read()

# The exact duplicate string — confirmed from live DOM inspection
DUPE = '<tr><td colspan="15" style="padding:0"><div class="cat-band"><div class="cdot" style="background:var(--c1)"></div><div class="cname" style="color:var(--c1)">Intelligence</div><div class="cdesc">AGI · Quantum · Neural Interfaces · Advanced Memory · AI Hardware</div></div></td></tr>'

count_before = html.count(DUPE)
print(f'Found {count_before} occurrences of INTELLIGENCE cat-band')

if count_before == 3:
    # Replace all 3 with empty string, then put back exactly 1
    html = html.replace(DUPE, '')
    # Find the correct insertion point — just before the first PORTFOLIO row of Intelligence sector
    # The first portfolio row of Intelligence is 000660.KS — insert header before its TR
    INSERT_BEFORE = 'data-ticker="000660.KS"'
    idx = html.find(INSERT_BEFORE)
    if idx != -1:
        # Find the opening <tr of this row
        tr_start = html.rfind('<tr', 0, idx)
        html = html[:tr_start] + DUPE + '\n' + html[tr_start:]
        print('Re-inserted 1 INTELLIGENCE header before 000660.KS row')
    else:
        # Fallback: just put one back at start of the intelligence section
        html = DUPE + html
        print('Fallback: inserted at top')
elif count_before < 3:
    print(f'Only {count_before} found — checking if already fixed')
else:
    print(f'Unexpected count {count_before} — check manually')

count_after = html.count(DUPE)
print(f'After fix: {count_after} occurrences (should be 1)')

with open('OLYMPUS_UNIFIED.html', 'w', encoding='utf-8') as f:
    f.write(html)

print('File saved.')