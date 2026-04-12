---
name: x20think
description: >-
  Runs a full OLYMPUS_UNIFIED.html pass in gods_plan — matrix, RADAR, Soros,
  liquidity tab, CLAUDE standing rules, then git commit/push and Minerva SSH
  deploy. Use when the user invokes /x20think, says "x20think", or asks for a
  one-pass OLYMPUS + auto-deploy workflow with FINAL REPORT checkmarks.
---

# x20think — OLYMPUS one-pass + deploy

## When this applies

User says `/x20think`, "x20think", or wants **all** HTML/JS/CSS blocks in `OLYMPUS_UNIFIED.html` completed in **one pass** with **auto-deploy** after.

## Workflow

1. Open `OLYMPUS_UNIFIED.html` in this repo and read the **entire** file (or every section you will touch).
2. Keep `tools/_matrix_v3_rows.html` in sync when matrix rows change; run `python tools/splice_matrix_v3.py` when that is the tbody source of truth.
3. Apply edits in one coherent batch.
4. Update `CLAUDE.md` in the same commit when standing rules are in scope.
5. **Deploy** from repo root:

```powershell
git add -A
git commit -m "<user-supplied message>"
git push origin master
ssh -i $env:USERPROFILE\.ssh\minerva_laptop -o StrictHostKeyChecking=accept-new root@5.189.176.185 "cd /root/gods_plan && git pull && cp OLYMPUS_UNIFIED.html /var/www/html/index.html && systemctl restart minerva && echo DEPLOYED"
```

6. Reply with **FINAL REPORT** checkmarks and deploy URL.

## Standing rules

- **Action changes:** see `CLAUDE.md` → ACTION CHANGE VERIFICATION.
- **RADAR:** `blog_tickers.json` + `renderRadarSector8` / `PORT` stay aligned with the matrix.
- **Liquidity:** `runLiq()` + `#liqOutput` only; guard optional legacy DOM nodes.

## Anti-patterns

- Sector-only action flips; deploy without successful `git push` / SSH `0` exit.
