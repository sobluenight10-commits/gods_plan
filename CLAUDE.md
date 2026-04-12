## OLYMPUS CONSTITUTION (DO NOT MODIFY WITHOUT GOD APPROVAL)
- 8 sectors: Intelligence, Energy, Space, Bio, Robotics, Infrastructure, Global Issue Radar, RADAR
- Track A: established companies, 4/7 Legend Gates required
- Track B: paradigm companies, P1+P2 mandatory
- GOD Score Wednesday recalibration
- Macro Multiplier: Earth Shifter × 1.15
- GOD's Law: sci-fi becomes reality — buy before world knows it is possible
- Mission: €100M by 2031

## CURSOR STANDING RESPONSIBILITIES

### EVERY SUNDAY
Execute Sunday build queue below. No explanation needed.
Read this file. Build everything listed under TODAY'S BUILD QUEUE.

### EVERY WEDNESDAY
1. Read GOD Score recalibration directive from Minerva
2. Update all scores in config.py
3. Show GOD a table: [Ticker | Old Score | New Score | Reason]
4. Wait for approval before saving

### INSTANT COMMANDS (GOD pastes these directly)
- "Add [TICKER] to portfolio" → update config.py + OLYMPUS_UNIFIED.html
- "Update [TICKER] limit to [PRICE]" → update config.py + dashboard
- "Add Lesson [N]: [title]" → add to tuition log in dashboard
- "Reflexivity signal [TICKER] — set limit [PRICE]" → update config.py instantly

### CURSOR RULES
1. Always read CLAUDE.md before starting any task
2. Always show GOD what you changed before git operations
3. Never modify server files — Claude Code handles deployment
4. Never delete existing sections — only add or update
5. When in doubt — ask GOD one question, not five

### BUILD PRIORITY TODAY
P0 — Reflexivity Signal display panel in OLYMPUS dashboard
P0 — Update sector layout to 8 sectors (add Global Issue Radar + RADAR)
P1 — Pre-IPO countdown: SpaceX June 2026 + Anthropic October 2026
P1 — Track A vs Track B badge per stock in matrix

## TODAY'S BUILD QUEUE — TYPE "execute" TO START

### TASK 1 — Open Cursor with this instruction:
"In D:\Cursor\gods_plan\OLYMPUS_UNIFIED.html, add one new section inside §13 Earth Shifters tab, before the stock table:

SECTOR HEATMAP — SIGNAL DETECTION (not decoration)
- 7 cards: Intelligence · Energy · Space · Bio · Robotics · Infrastructure · RADAR
- Each card shows:
  * Sector name + color dot
  * Best performer today: ticker + % change (green)
  * Worst performer today: ticker + % change (red)
  * SECTOR SIGNAL: BULLISH / BEARISH / NEUTRAL based on avg move
- RADAR card (7th): shows tickers recently mentioned in ranto28 blog (read from /data/blog_tickers.json) that are NOT in current portfolio — labeled NEW SIGNAL with date detected
- Data: fetch prices.json from http://5.189.176.185/data/prices.json
- Blog tickers: fetch http://5.189.176.185/data/blog_tickers.json
- Auto-refresh every 5 minutes
- Style: compact, data-dense, no decoration — use existing CSS variables

Save file when done."

### TASK 2 — Open Cursor with this instruction:
"In D:\Cursor\gods_plan\battle_rhythm.py, find the morning brief GPT prompt in generate_master_daily(). Add a new final section called DECISION ENGINE that outputs exactly this format:

🎯 DECISION ENGINE — WHAT TO DO RIGHT NOW
🔴 SELL NOW: [ticker if stop hit or thesis broken] — [one line reason]
🟠 REVIEW: [ticker if -8% or news alert] — [one line reason]
🟡 WATCH: [ticker approaching limit or catalyst] — [one line reason]
🟢 BUY NOW: [ticker + exact EUR price] — [one line reason]
💤 HOLD: [list of tickers] — thesis intact
💰 DEPLOY: €[amount] → [ticker] when [specific condition]

Rules for GPT:
- Use ONLY tickers from GOD holdings: TSM, PLTR, UEC, URNM, COHR, 1810.HK, NTR, RKLB, PL, TMO, LVMH, 000660.KS, 272210.KS, ARKQ, BOTZ, VRT, IONQ, IAU
- Dry powder: €1500 TR
- Active limits: UEC €11, OKLO $60, CCJ $100
- If no action needed for a category, omit that line
- ONE command at the end: THE ONE THING GOD MUST DO TODAY

Save file when done."

### TASK 3 — git add, commit, push, deploy to server, restart minerva

### TASK 4 — Report to GOD when complete
