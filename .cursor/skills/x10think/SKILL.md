---
name: x10think
description: Bulk-edits the Master Matrix in gods_plan (OLYMPUS_UNIFIED.html via tools/_matrix_v3_rows.html + splice_matrix_v3.py), applies Soros / portfolio-badge / sector rules, and auto-deploys to Minerva. Use when the user says x10think, /x10think, or wants matrix + server sync in one pass.
---

# x10think — OLYMPUS Master Matrix (one pass + deploy)

## Preconditions

- Primary HTML: `gods_plan/OLYMPUS_UNIFIED.html`
- Row source of truth (optional bulk edit): `gods_plan/tools/_matrix_v3_rows.html` then run `python tools/splice_matrix_v3.py` (splice anchors on `data-ticker="000660.KS"`).
- Server: `root@5.189.176.185`, repo `/root/gods_plan`, web root `/var/www/html/index.html`
- SSH key (Windows): `%USERPROFILE%\.ssh\minerva_laptop` — in PowerShell: `$env:USERPROFILE\.ssh\minerva_laptop`

## Workflow

1. Read the user blocks end-to-end (matrix rows, Soros statics, `KW_TICKERS` / `TR_TICKERS` / `HELD_SET` / `PORT`, sector warnings, `prices.json` keys for new `price-*` ids).
2. Edit `_matrix_v3_rows.html` for tbody rows; re-run splice; patch HTML-only concerns in `OLYMPUS_UNIFIED.html` (CSS, Soros blocks outside the spliced region, inline scripts).
3. Align `prices.json` keys with `id="price-{TICKER}"` cells (e.g. `POSCO` alias → same yfinance symbol as PKX).
4. Deploy:

```powershell
cd D:\Cursor\gods_plan
git add -A
git commit -m "…"   # use the user’s exact message when provided
git push origin master
ssh -i $env:USERPROFILE\.ssh\minerva_laptop root@5.189.176.185 "cd /root/gods_plan && git pull && cp OLYMPUS_UNIFIED.html /var/www/html/index.html && systemctl restart minerva && echo DEPLOYED"
```

5. Report per-block ✅/❌ and `DEPLOYED` or paste exact git/SSH stderr on failure.

## Design contract (v3 matrix)

- **14 columns**: Stock (badge + ticker + name), Sector, GOD, Entry, Today, VS Today, 1M–5Y, Soros gap, Action, Target.
- **Row classes**: `mx-st-pf` (portfolio — green pill ●, inset green bar, row tint), `mx-st-watch` (○ WATCHLIST, blue bar, no tint), `mx-st-ipo` (◈ IPO year, purple), `mx-st-locked` (🔒 LOCKED, gold). `updateVsNowMatrix` skips `watch`, `gift`, `tbc`, `ipo`.
- **Sector minimum warnings**: only on bands still below 5 names after row edits (e.g. Space 4/5, Infrastructure 4/5, Global 3/5); not on RADAR.
- **Soros “outside portfolio”**: static catalyst lines may sit **above** `#soros-outside-portfolio`; JS only fills that div from `directives.json`.

## Do not

- Store skills under `~/.cursor/skills-cursor/` (reserved).
- Duplicate `id="price-*"` on live cells.
