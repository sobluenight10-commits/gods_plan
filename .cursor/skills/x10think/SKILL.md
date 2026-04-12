---
name: x10think
description: Opens OLYMPUS_UNIFIED.html in gods_plan, redesigns the Master Matrix tab (Soros reflexivity panel from directives.json, 8-column decision table, compact portfolio summary), and auto-deploys to Minerva via git push and SSH. Use when the user says x10think, /x10think, or wants a full Master Matrix refresh with server sync.
---

# x10think — OLYMPUS Master Matrix refresh

## Preconditions

- Primary file: `gods_plan/OLYMPUS_UNIFIED.html`
- Server: `root@5.189.176.185`, repo path `/root/gods_plan`, web root `/var/www/html/index.html`
- SSH key: `~/.ssh/minerva_laptop` (Windows: `%USERPROFILE%\.ssh\minerva_laptop`)

## Workflow

1. Read `OLYMPUS_UNIFIED.html` end-to-end before editing (structure, scripts, `loadLivePrices`, `directives.json` URLs).
2. Apply Master Matrix changes in **one commit** (Soros panel + table + summary + JS), preserving other tabs and global header/nav.
3. Run deploy sequence:

```powershell
cd D:\Cursor\gods_plan
git add -A
git commit -m "REDESIGN: Master Matrix …"   # user supplies exact message if given
git push origin master
ssh -i $env:USERPROFILE\.ssh\minerva_laptop root@5.189.176.185 "cd /root/gods_plan && git pull && cp OLYMPUS_UNIFIED.html /var/www/html/index.html && systemctl restart minerva && echo DEPLOYED"
```

4. Report `DEPLOYED` or paste the **exact** stderr from git/ssh on failure.

## Design contract (v2)

- **Section 1**: Dark + gold Soros panel inside Master Matrix tab; `directives.json` every 5 minutes; inside vs outside portfolio lines; `ONE COMMAND` at bottom.
- **Section 2**: Eight columns only (ticker+name, sector badge, GOD score, entry→now+% , thesis word, Soros gap %, action badge, target/limit); sector bands; order port → watch → IPO by GOD score; sector minimum warning if `<5` names in that sector.
- **Section 3**: Single-line summary: TR/Kiwoom **counts**, dry powder €, active limits text, next catalyst — **no** portfolio EUR totals.

## Do not

- Store skills under `~/.cursor/skills-cursor/` (reserved).
- Leave duplicate `id="price-*"` on live price cells.
