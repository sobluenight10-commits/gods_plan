---
name: x10think
description: Runs a pre-alert triage on OLYMPUS matrix prompts (resolve contradictions, recount sectors, verify badges vs holdings), edits gods_plan via _matrix_v3_rows.html + splice, patches OLYMPUS-only CSS/JS, and auto-deploys to Minerva. Use for /x10think, x10think, or any full Master Matrix + server sync.
---

# x10think — OLYMPUS Master Matrix (pre-alert + one pass + deploy)

## Preconditions

- Primary HTML: `gods_plan/OLYMPUS_UNIFIED.html`
- Bulk rows: `gods_plan/tools/_matrix_v3_rows.html` → `python tools/splice_matrix_v3.py` (splice anchors on `data-ticker="000660.KS"` + `rfind("<tr")`).
- Server: `root@5.189.176.185`, `/root/gods_plan`, web `/var/www/html/index.html`
- SSH (Windows): `$env:USERPROFILE\.ssh\minerva_laptop`

---

## Phase 0 — Pre-alert system (do this before editing)

**Do not execute the user’s blocks blindly.** Run this checklist and fix the prompt mentally (or ask one sharp question if still ambiguous).

### 0.1 Multi-prompt merge rule

- If the user pastes **more than one** instruction set and says contradictions resolve toward a **specific** one (e.g. “second wins”), **material facts from that version override** the other for: sector placement, row counts, warnings, entry/limit copy, GOD scores, deploy message.
- If no merge rule is stated, **flag contradictions** in the final report and apply the **last materially specific** instruction (later message usually refines earlier).

### 0.2 Sector integrity pass (surgical)

After any row add/move/delete, **recompute each sector’s name count** (matrix `mx-row` only, not band rows). Canonical bands:

| Band | Typical tickers / names | Min for “full” |
|--------|-------------------------|----------------|
| Intelligence | listed equities + watch + IPO rows **in that band** | 5 unless user sets otherwise |
| Energy | … | 5 |
| Space | … | 5 |
| Bio | … | 5 |
| Robotics | … | 5 |
| Infrastructure | … | 5 |
| Global Issue | … | 5 |
| RADAR | blog-only | **no** minimum warning |

- Turn **on** `sector-min-warn` only where count **&lt; 5** (or user-defined threshold).
- Turn **off** warnings where count **≥ 5**.
- **Taxonomy check:** e.g. enterprise foundation model IPO belongs under **Intelligence** (compute / agent layer), not Bio, unless the user explicitly keeps it in Bio.

### 0.3 Holdings vs badge audit

Cross-check `mx-st-pf` / `mx-st-watch` / `mx-st-ipo` / `mx-st-locked` against the user’s TR list, Kiwoom list, watchlist, IPO list, and **LOCKED overrides** (`MC.PA` → locked, not green portfolio).

Align scripted sets in `OLYMPUS_UNIFIED.html`:

- `TR_TICKERS`, `KW_TICKERS` (counts for compact bar)
- `HELD_SET` inside `loadDecisionEngine` (outside-portfolio Soros lines)
- `PORT` inside `OLY_fillRadar` (blog dedupe; include **all** matrix tickers the user treats as “already on the board,” including watchlist symbols and IPO display names as needed)

### 0.4 Price wire-up

Every `id="price-TICKER"` must have a matching key in `prices.json` (or intentional `—` for pre-IPO). Add **aliases** (e.g. `POSCO` → same yf as `PKX`) when display ticker ≠ Yahoo key.

### 0.5 Catalyst / limit clarity

- Watchlist + **limit armed**: Entry column must read as **intent**, not as if shares were held (e.g. explicit “WATCHLIST — Limit €X armed” + optional `mx-limit-armed` pill).
- **Earnings / IPO dates**: Soros static block + alert chips should agree on the same date and rule (beat / miss / wait).

### 0.6 Deploy hygiene

- One coherent commit message (user-supplied message wins).
- After push, SSH pull → `cp` → `systemctl restart minerva` → confirm `DEPLOYED` or paste **exact** stderr.

---

## Phase 1 — Execute

1. Apply matrix changes in `_matrix_v3_rows.html`; run `python tools/splice_matrix_v3.py`.
2. Patch `OLYMPUS_UNIFIED.html` for CSS, Soros chrome, inline scripts not covered by splice.
3. Update `prices.json` if new live cells.
4. Deploy (PowerShell):

```powershell
cd D:\Cursor\gods_plan
git add -A
git commit -m "…"
git push origin master
ssh -i $env:USERPROFILE\.ssh\minerva_laptop root@5.189.176.185 "cd /root/gods_plan && git pull && cp OLYMPUS_UNIFIED.html /var/www/html/index.html && systemctl restart minerva && echo DEPLOYED"
```

5. **Final report:** Pre-alert notes (contradictions resolved), each user FIX/block ✅/❌, `DEPLOYED` or errors.

---

## Design contract (v3 matrix)

- **14 columns**: Stock (badge + ticker + name), Sector, GOD, Entry, Today, VS Today, 1M–5Y, Soros gap, Action, Target.
- **Row classes**: `mx-st-pf`, `mx-st-watch`, `mx-st-ipo`, `mx-st-locked`. `updateVsNowMatrix` skips `watch`, `gift`, `tbc`, `ipo`.
- **Sector warnings**: `sector-min-warn` only on bands below threshold after edits (commonly Space, Infrastructure, Global; **Bio when 4 names** after moving IPO names out, etc.).
- **Soros**: static catalyst lines may precede `#soros-outside-portfolio`; JS fills only that div from `directives.json`.

## Do not

- Store this skill under `~/.cursor/skills-cursor/` (reserved).
- Duplicate `id="price-*"`.
