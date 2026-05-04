## OLYMPUS CONSTITUTION (DO NOT MODIFY WITHOUT GOD APPROVAL)
- 8 sectors: Intelligence, Energy, Space, Bio, Robotics, Infrastructure, Global Issue Radar, RADAR
- Track A: established companies, 4/7 Legend Gates required
- Track B: paradigm companies, P1+P2 mandatory
- GOD Score Wednesday recalibration
- Macro Multiplier: Earth Shifter × 1.15
- GOD's Law: sci-fi becomes reality — buy before world knows it is possible
- Mission: €100M by 2031

## ACTION CHANGE VERIFICATION (MANDATORY)

Before changing any stock action in `OLYMPUS_UNIFIED.html`:

1. Has **this** company's specific contract, revenue, or thesis changed? If **no**, do not change the action.
2. Is there a verified SEC filing or specific, attributable news? If **no**, do not change the action.
3. Sector sentiment alone **never** justifies an action change.
4. **KTOS example:** Another defense name exiting (e.g. AVAV) is not a KTOS thesis break — different companies, different contracts.
5. **UEC example:** A live limit at €11 is **ARMED**, not HOLD and not ADD — the system waits for the fill; GOD does not second-guess the order.

## OLYMPUS-SENTINEL — PRIME DIRECTIVE KERNEL (PHASE 1)

The Sentinel stack is **above** prediction. A forecaster cannot buy. A risk agent can always refuse. Order of evaluation: `kernel → drawdown_guardian → liquidity_gate → ops_gate → position_sizer → PRIME_MINISTER` in `tools/build_active_actions.py`.

**Four immutable invariants** (`kernel/prime_directive.py`):

- **I1 — PORTFOLIO_DD_HARD_CAP = 15%** · trailing drawdown ≥ cap → `freeze_all`.
- **I2 — SINGLE_POSITION_CAP = 20%** · no position may exceed 20% of NAV.
- **I3 — SECTOR_CAP = 35%** · no sector may exceed 35% of NAV.
- **I4 — CASH_FLOOR = 5%** · dry powder must never fall below 5% of NAV.

**Ring enforcement**:

- **Drawdown Guardian** (`risk/drawdown_guardian.py`) — state machine GREEN / YELLOW / ORANGE / RED with risk-budget multipliers `1.00 / 0.75 / 0.40 / 0.00`. Feeds `risk_budget_multiplier` into sizer.
- **Position Sizer** (`risk/position_sizer.py`) — fractional Kelly (×0.25), loss aversion λ=1.5, CVaR penalty on ES5 > 25%, ambiguity shrinkage when conviction < 5/10. Emits `ev_pct, es5_pct, p_win, kelly_frac, size_pct_nav, conviction, stop_price, vetoes`.
- **Dashboard** — `#sentinel-strip` shows DD / kernel / cash / liquidity status; matrix tooltip shows per-ticker EV / ES5 / p_win / conviction / stop / vetoes.

**Rule above all rules**: every action in `active_actions.json` must carry its EV **and** its ES5. If ES5 > EV in magnitude and vetoes ≠ empty, the ticker is `WATCH` regardless of grade or narrative.

## OLYMPUS-SENTINEL — FORECASTER ENSEMBLE (PHASE 2)

Per-ticker 1-year forecasts now come from three independent voices, Bayesian-averaged by forecaster track record:

- **GEM / Heston** (`minerva_gem.py`) — stochastic-vol Monte Carlo with sector-aware multiples.
- **Analog k-NN** (`agents/analog_forecaster.py`) — empirical forward-return distribution from the same ticker's 40 nearest historical windows (cosine distance in z-scored feature space: mom_21/63/252, vol_21, dd_from_52wk_hi, rsi_14).
- **OLS + bootstrap** (`agents/ml_forecaster.py`) — pure-numpy linear regression on the same features with bootstrap residual quantiles and 20% shrinkage toward the historical mean.

**Orchestrator**: `tools/run_forecasters.py` writes `data/forecasts.json` with per-ticker ensemble quantiles (p05/p25/p50/p75/p95), EV, ES5, p_win, and the weight each voice received. Cache lasts 12 h unless `--force`. Webroot mirror at `/var/www/html/forecasts.json`.

**Weights**: `data/model_weights.json` seeded at `gem 0.50 / analog 0.30 / ml 0.20`. When GEM has no row for a ticker the remaining weights auto-renormalize to `analog 0.60 / ml 0.40`. `reflection/post_mortem.py` refits weights via pinball-loss / CRPS once ≥ 20 lesson cards accumulate in `data/lessons/`; until then defaults stand.

**Consumption**: `tools/build_active_actions.py` constructs a "virtual GEM row" from the ensemble for every ticker and feeds it to `position_sizer`. The result: EV / ES5 / size / stop / conviction in the matrix tooltip are **ticker-specific**, not priors. The tooltip carries `Forecast: gem+analog+ml [gem=50% analog=30% ml=20%]`.

**Daily wiring** (`olympus_daily.py`): `_refit_weights → _run_forecasters → _build_active_actions`.

## OLYMPUS-SENTINEL — PORTFOLIO GUARDS + KILL-SWITCH (PHASE 3)

Phase 1 guarded each position. Phase 2 produced calibrated forecasts. Phase 3 guards the **portfolio as a whole** and the **system's own trustworthiness**.

- **Correlation Auditor** (`risk/correlation_auditor.py`) — eigendecomposes the daily-return correlation matrix of the held book. Publishes `pc1_share`, `pc2_share`, `eff_bets = exp(H[λ])`, `top_cluster`. For every expansionary verb (BUY/ADD) it also runs `check_candidate(tk)`:
  - `VETO_NEIGHBOR` when the candidate's mean correlation to the book ≥ **0.70**.
  - `VETO_PC1` when PC1 share ≥ **0.55** (the book is already one bet).
  - `VETO_DOUBLE` when PC1 ≥ 0.45 **and** ρ ≥ 0.55 (adding doubles the bet).
  - Dashboard: `CORE DIGEST · PC1` pill, red when concentration state = RED.
- **Stop Engine** (`risk/stop_engine.py`) — per-position stop plan, tightest of:
  - `ATR × 2.0` below spot (or trailing below 60d high once up ≥ 15%),
  - `18%` hard floor below entry (satellite) or `35%` (core),
  - Explicit `thesis_invalidation_price` from `portfolio_all.json`.
  - Cores honor only HARD + THESIS, never ATR — we hold winners through vol; we do not hold them through thesis death. Kind flags: `trailing | hard | thesis | triggered`.
- **Tail Hedger** (`risk/tail_hedger.py`) — composite score over VIX/VIX3M inversion, HYG 20d drawdown, SPY-vs-200DMA, equal-weight-vs-cap-weight 20d ratio, QQQ−SPY vol gap. Maps to **DEFCON 5→1**:
  - `3`: cash floor 7%, arm watchlist, no new satellite entries.
  - `2`: cash floor 10%, stage SPY puts, freeze satellite adds.
  - `1`: cash floor 15%, execute puts, core-only, tighten all stops.
  - Publishes `cash_floor_override_pct` that **raises** (never lowers) kernel cash floor.
- **Sentinel Watchdog** (`risk/sentinel_watchdog.py`) — Layer 7 kill-switch. Final check each build:
  - Staleness (liquidity > 36h, forecasts > 48h, GEM > 48h).
  - Model disagreement (≥ 3 tickers with ensemble p50 spread > 60pp).
  - Veto storm (≥ 5 active vetoes).
  - Kernel breach or Drawdown RED/ORANGE.
  - Composite score → `GREEN | YELLOW | ORANGE | RED | FREEZE`. FREEZE downgrades every BUY/ADD to WATCH and stamps `sentinel_freeze` into blocks.

**Wiring** (`tools/build_active_actions.py`): after the Phase 1 sizer loop we run the correlation audit, stop engine (per-ticker), tail hedger, then the watchdog as a final pass. Payload now carries `correlation_audit`, `tail_hedger`, `sentinel_watchdog`, plus a `groups` block with `core / satellite / rules` for the dashboard.

**Dashboard**:
- `CORE DIGEST` header bar replaces the static MINERVA_GEM grade summary. It pulls from `active_actions.json` every 2 min and shows WATCHDOG level, DD state, DEFCON, PC1, `so_what_mandate`, and the current top-5 BUY/ADD and top-5 TRIM/EXIT/VETO candidates. Staleness of GEM surfaces as a red note with the exact command to run.
- `CORE vs SATELLITE` panel (open by default) renders each ticker with live gate badges (`OPS ≤120`, `thesis ✓`, `EV ≥35`, `ES5`, conviction, verb).
- Matrix tooltip: when GEM projections are missing, falls back to `/forecasts.json` ensemble (EV / p05 / p50 / p95 + weights used) so the tooltip never reads `GEM projections loading…`.

**Rule**: If `sentinel_watchdog.level = FREEZE`, no ADD/BUY survives regardless of source (directives, radar, override) — only EXITs and explicit TRIMs pass through. This is the one switch that overrides GOD — and only until the root cause (stale data, kernel breach, DD red) is cleared.

## OLYMPUS-SENTINEL — DISCOVERY + REFLECTION + BEHAVIORAL + DEPLOY (PHASE 4)

Phase 1–3 hardened risk. Phase 4 turns the system outward (hunt for alpha) and inward (learn from every closed trade, stop the human from self-destructing). Four modules, four dashboard panels, zero new dependencies.

- **Auto lesson cards** (`tools/close_trade.py`) — every closed trade emits `data/lessons/<ticker>_<YYYY-MM-DD>.json` carrying entry/exit, realized 1y, thesis outcome, `signals_at_entry` (OPS, liquidity state, EV, ES5, p_win, conviction, ensemble quantiles), `what_fired_first / right / wrong / silent`, and a `felt` human reflection field. `tools/lesson_backfill.py` seeds KTOS / AVAV / GEVO / TMO canonical failures. `tools/lesson_roundup.py` produces `data/lesson_digest.json` (win-loss, signal scoreboard, actionable patterns, calibration status). Once ≥ 20 cards exist, `reflection/post_mortem.py` refits ensemble weights via pinball-loss / CRPS.
- **Earth-Shifter discovery** —
  - `tools/secular_trends.py`: 8 civilisational themes (AI_COMPUTE, NUCLEAR, SPACE_ECON, GENE_EDITING, DEFENSE_AUTON, BIOTECH_INFRA, CYBER, CRITICAL_MIN). Each theme tracks a proxy ETF's 90d/365d alpha vs a benchmark. States: `STRONG_BID | LEADING | INFLECTING | NEUTRAL | EXITING`.
  - `tools/insider_flow.py`: SEC EDGAR Form 4 ATOM per CIK. Cluster score `log1p(n_filings_30d) × Σ decay`. Tight Form-4 title filter (rejects 424B* prospectuses). Seed CIK map covers portfolio + small-cap discovery (BKSY, IRDM, LEU, LTBR, NNE, ACHR, JOBY, RGTI, IONQ, QBTS, AVAV, ONDS, RZLV).
  - `tools/ipo_spinoff_radar.py`: curated `gem_inputs/ipo_calendar.json` → scored (sector 0–4, scale 0–2, moat 0–2, governance 0–2) → tier A/B/C/D/PASS → `imminent_30d` / `imminent_90d` lists.
  - `tools/patent_signal.py`: USPTO PatentsView velocity by CPC class and applicant name. Graceful `no_data` fallback when endpoint is key-gated.
- **Behavioral circuit breakers** (`behavioral/circuit_breakers.py`) —
  1. `check_cooldown(ticker, order_eur, day_move_pct)`: arms a **5-min cooldown** when order ≥ €500 **and** underlying moved ≥ 5% that day. Stored in `data/cooldowns.json`, auto-expired.
  2. `require_thesis_restatement(ticker, action)`: blocks CORE trims/EXITs until a ≥ 20-char thesis sentence is recorded in `data/decisions_pending.json`.
  3. `log_override(...)`: records every human contradiction of the system verb to `data/overrides.json`, classified `overconfidence_buy / conservative_miss / premature_harvest / hope_hold_trap / other`. Pattern learning reads this.
- **Marginal-Sharpe deploy optimiser** (`tools/deploy_optimiser.py`) — consumes `forecasts.json` + `active_actions.json` + `core_satellite.json` + live `state.dry_powder.TR_EUR`. Marginal Sharpe = `EV / max(2, |ES5|)`. Adjusted score multiplies by `p_win × conviction_mult` (CORE 1.25 / SAT 1.00 / UNCL 0.85). Eligibility: **blocks checked BEFORE verb** so that `liquidity_freeze`, `sentinel_freeze`, `tail_defcon1/2`, `kernel_freeze`, `correlation_veto`, `ops_extreme`, `pending_catalyst` surface as the real gate reason; only **BUY / ADD** verbs get sized (HOLD / WATCH / TRIM / EXIT are rejected). Additional filters: OPS < 180, EV ≥ 5%, `p_win` ≥ 0.45. Picks top-3 with 60/25/15 allocation of `(powder + monthly contribution)`. When nothing is eligible, the mandate is honest: *"HOLD €3,100 dry powder — LIQUIDITY GATE — zone DANGER / vector CONTRACTING. Hold powder, wait for vector reversal."* When eligible: *"DEPLOY €3,100 → CWEN €1,860 · 000660.KS €775 · COHR €465 (correlation-adjusted, OPS-screened)"*.
  - **Powder source of truth**: `state.json.dry_powder.TR_EUR` (+ `Kiwoom_USD`). Keep this fresh — `tools/update_state_powder.py --tr-eur N [--kw-usd N]` one-shots the update. Stale powder → wrong deployable. On 2026-04-24 this was already wrong (2200 committed in state.json while actual was 1600), producing a phantom €3,700 recommendation; after fix → €3,100 honest.

**Daily wiring** (`olympus_daily.py`): after `_build_active_actions` → `_insider_flow → _secular_trends → _patent_signal → _ipo_radar → _lesson_roundup → _publish_lessons_index → _behavioral_publish → _deploy_optimiser → _scenario_engine → _strike_radar → _strike_cards → _strike_plan`.

## OLYMPUS-SENTINEL — STRIKE ENGINE (PHASE 5)

The user's standing instruction (Apr 28 2026): *"Vector is the most important thing. The moment money flow direction flips from CONTRACTING to EXPANDING is THE strike window. Catch it. Make all scattered data collapse into one decisive view. €10,000 powder is staged. Tell me what to buy and when."*

Phase 5 is the single decisive layer above prediction, valuation, risk and discovery. It does not replace any earlier gate; it consumes their outputs and emits **one number per ticker, one tranche plan for the powder, and one mandate sentence**.

### Layers

- **Strike Radar** (`tools/strike_radar.py`) — multi-horizon FRED velocity stack. Pulls 90 daily observations of WRESBAL / WTREGEN / RRPONTSYD; forward-fills weekly to daily; computes `v_3d, v_7d, v_14d, v_28d` and `accel = v_3d − v_14d`. Component decomposition over the last 7 days yields `reserves_share`, `tga_share`, `rrp_share` and a `dominant_driver`. Pivot quality: **A** = reserves-led real injection, **B** = RRP-drain mechanical, **C** = TGA spending transient. State machine (priority order): `STRIKE_WINDOW_OPEN` (net<1900, v_3d≥0, v_7d≥0) > `STRIKE_PIVOT_EARLY` (net<1900, v_3d≥0, v_7d<0) > `FROZEN_CONTRACTING` (net<1900, v_3d<0) > selective/deploy variants. Output: `data/strike_radar.json` with `strike_score 0-100`, `mandate`, full velocity stack and decomposition.
- **Strike Cards** (`tools/strike_cards.py`) — per-ticker decisive composite. Single 0-100 score weighted: macro 25 · forecast 20 · valuation 15 · quality 15 · catalyst 10 · discovery 10 − risk_penalty (0..15). Hard zero on any killer block (sentinel, kernel, correlation, ops_extreme, pending_catalyst, tail_defcon1/2, liquidity_freeze) and on `verb ∈ {EXIT,TRIM}` / `ev ≤ 0` / `p_win < 0.4` / `ops ≥ 180`. CORE × 1.05 / UNCLASSIFIED × 0.92. Output: `data/strike_cards.json` with shortlist (top-8) and full card list including `score_breakdown`, `buy_zone {low/mid/high}`, `nearest_catalyst`, `one_liner`.
- **Strike Plan** (`tools/strike_plan.py`) — €N three-tranche pyramid (40/35/25), gated by Strike Radar state.
  - **T1 STRIKE** — CORE-only, max 2 picks, 50% per-pick cap. Status `RELEASE` on `STRIKE_PIVOT_EARLY`+; `ARMED` on `FROZEN_CONTRACTING` (orders pre-staged; release on first day v_3d ≥ 0).
  - **T2 CONFIRM** — top 3 picks, max 1 satellite. Releases on v_7d ≥ 0 + reserves-led pivot quality A or B.
  - **T3 FOLLOW-UP** — opportunistic; reserved for the post-pop -8/-12% retracement OR a hard catalyst.
  - Single-pick cap: **50% of the tranche** (no all-in on one name).
  - When state ∈ {`SELECTIVE_FADING`, `DEPLOY_TOPPING`}: all tranches `HOLD`. Don't deploy into weakness.
  - Output: `data/strike_plan.json` with `mandate`, three tranches, picks (incl. €, buy zone, stop), `powder_used_eur` / `powder_remaining_eur`.
- **Scenario Engine** (`tools/scenario_engine.py`) — probability-weighted macro hypothesis encoder. Three seed scenarios in `config/scenarios.json` (GOD-editable): `fed_pivot_2026` (p=0.55), `geopolitical_deescalation` (p=0.40), `scenario_fail_recession` (p=0.20). Each carries `liquidity_uplift_b`, per-sector `sector_uplift_pct`, and `confirmation_signals` checklist. Output: `data/macro_scenario.json` with probability-weighted EV. The Strike Radar mandate stays UNCONDITIONAL on FRED velocity (we do not bias the gate by predicted politics) — scenarios are surfaced for context only.

### Dashboard

`⚡ STRIKE CONSOLE` is the new top panel (replaces the prior "open by default" Phase-4 deploy panel; deploy panel collapses to supporting evidence). Three rows: (1) Strike Radar pill with state colour, mandate, full velocity stack and 7d decomposition; (2) three-tranche grid with picks, € amounts, buy zones, stops, gate status (`RELEASE` green / `ARMED` amber / `COCKED` grey / `HOLD` muted); (3) top-8 strike cards with score breakdown line and forecast / OPS / GOD / next-catalyst columns.

### Operating doctrine

- **Vector beats range.** The radar fires on the day v_3d crosses zero, not on the day net liq crosses 1900. This is the user's central insight encoded.
- **Quality of pivot matters.** Reserves-led pivots are tradable; TGA-spending pivots are noise. Quality is shown next to dominant driver on the dashboard.
- **Tranches, not all-in.** Even at maximum-asymmetry STRIKE_WINDOW_OPEN we deploy at most T1 + T2 (75% of staged powder), keeping T3 for the post-pop dip. Never spend the powder twice.
- **Single-pick cap 50%.** Even the best strike card cannot consume more than half a tranche.
- **Honest stand-down.** When the gate is closed, the mandate says HOLD with a reason — not "no candidates". Powder is only deployed against the gate, never against narrative.

**Dashboard panels** (all sit between Eval Stack and Catalyst Radar):
- `🚀 DEPLOY PLAN` (open by default) — top-3 picks with € allocations, next-in-queue, rejected, concrete mandate echoed into CORE DIGEST.
- `🛰 EARTH-SHIFTER DISCOVERY` (open by default) — 4-tile grid: secular themes / insider cluster / IPO radar / patent velocity.
- `🪞 REFLECTION` (collapsed) — summary, 25 recent lesson cards, signal scoreboard (right / wrong / silent), CRPS calibration status.
- `🧠 BEHAVIORAL GATES` (collapsed) — active cooldowns, pending thesis restatements, override pattern histogram, last 6 overrides.

**CORE DIGEST extension**: when sentinel is not FREEZE and DEFCON > 2, `so_what_mandate` is replaced by the live deploy mandate (falls back to secular-theme mandate if no eligible picks). This makes the one "so what" line on the dashboard actually executable (€ amounts + tickers) rather than advisory prose.

**Rule**: The deploy optimiser never bypasses Phase 1–3 gates — it only ranks amongst survivors. The behavioral gates never block EXITs of DEAD theses — only expansionary verbs and discretionary core trims.

## OLYMPUS-SENTINEL — POINT A / POINT B + HEADS-UP (PHASE 6)

The user's standing instruction (May 4 2026): *"The major premise is price keeps going up. The ideal entry is A — the moment before price moves. If A is unclear, B is the practical fallback: -15% from previous peak. My experience says stocks meeting the major premise rebound -15 to -20%. Build the heads-up. And fix Telegram — saying 'watch for dip below €95' when price is €126 is noise."*

### Definitions (locked)

- **Point A** (macro entry, earliest reliable signal): three conditions must be true SIMULTANEOUSLY.
  - **A1 Liquidity expanding** — Strike Radar state ∈ {`STRIKE_PIVOT_EARLY`, `STRIKE_WINDOW_OPEN`, `SELECTIVE_TAILWIND`, `DEPLOY_RIDING`} OR (`v_3d ≥ 0` AND `v_7d ≥ 0`).
  - **A2 Funding stress easing** — VIX < 20 AND VIX < VIX 5d ago, OR HYG drawdown vs 60d high improving. Proxy for OFR FSI dropping below 0.5.
  - **A3 Stock below 20W MA** — close < 100-day SMA. The "price hasn't moved yet" guard. When price crosses above the 20W MA the A window CLOSES and we're in B-territory.
  - 3-of-3 = `FIRED`. 2-of-3 = `WATCH`. 1-of-3 or 0-of-3 = `INACTIVE`.

- **Point B** (price-driven entry, Soros gap formalised):
  - `high_20d` = highest CLOSE in trailing 20 trading days.
  - `breakout_base` = lowest CLOSE in trailing 60 trading days (consolidation low proxy).
  - `dist_pct = (close − high_20d) / high_20d × 100`.
  - States (priority — first match wins):
    - `THESIS_REVIEW` — dist ≤ −15% AND close ≤ base × 1.02. Base broken; written justification required. NOT a B entry.
    - `POINT_B_EXECUTE` — dist ≤ −15% AND base intact. Fire prepared orders.
    - `POINT_B_WARNING` — −15% < dist ≤ −10%. Pre-stage limits.
    - `RIDING` — −10% < dist ≤ 0. No action.
    - `ABOVE_HIGH` — dist > 0. A-window already closed; wait for next pullback.

### Heads-Up doctrine (Telegram noise fix)

- **Stop alerts** fire only when `current_price ≤ stop × 1.05` (within 5%). The PLTR €95 stop noise (price €126, 25% away) is now suppressed.
- **Limit alerts** fire only when `current_price ≤ limit × 1.03` (within 3%).
- Tier 2 (Point A `FIRED`) and Tier 3b (Point B `EXECUTE`) and Tier 3c (`THESIS_REVIEW`) always alert with daily dedup.
- Tier 3a (Point B `WARNING`) alerts once per ticker per day.
- Tier 1 (Point A `WATCH` 2-of-3) is digest-only — never an immediate alert.
- The `FIRST 30 MIN WATCH` block in `battle_rhythm.generate_us_open()` is now built deterministically by `tools.heads_up.run()` instead of GPT — GPT only writes the `OPEN STRATEGY` paragraph and is fed the proximity-gated trigger list as input. Stops in `_format_state_context()` are also annotated with proximity tags (`URGENT` / `APPROACHING` / `FAR — DO NOT include`) so other GPT prompts can't reintroduce noise.

### Modules

- `tools/point_a_scanner.py` — outputs `data/point_a_scan.json` with per-ticker A1/A2/A3 booleans, conditions met (0–3), state, reasons, and `shortlist_fired` / `shortlist_watch`.
- `tools/point_b_scanner.py` — outputs `data/point_b_scan.json` with per-ticker `last_close, high_20d, breakout_base, base_intact, dist_pct, soros_gap_pct, state, buy_zone_b {warning_at, execute_at}, stop_below_base`.
- `tools/heads_up.py` — consolidates both scanners + active stops/limits with proximity gating; outputs `data/heads_up.json` with `tiers {tier_2_point_a_fired, tier_3a_point_b_warning, tier_3b_point_b_execute, tier_3c_thesis_review, tier_4_stop_proximity, tier_5_limit_proximity, digest_point_a_watch}`, `one_command`, `first_30min_block`. Daily dedup state in `data/heads_up_dedup.json`.

### Dashboard

`🎯 HEADS-UP CONSOLE` is the new top-most panel (above Strike Console). Four blocks: (1) ONE-COMMAND single-line directive; (2) FIRST 30 MIN deterministic proximity block (replaces old GPT noise); (3) three-card grid: Point A (macro) · Point B (Soros gap) · Proximity (stops & limits). Loads `point_a_scan.json`, `point_b_scan.json`, `heads_up.json`.

### Operating rule

A and B are different signals on different data. A watches FRED + VIX/HYG + 20W MA. B watches price feeds. They are run independently every cycle. The user buys CORE candidates on A; SATELLITE candidates on B. Anything that doesn't fit either pattern but is being tempted by price action is a discretionary trade requiring written thesis restatement under behavioral gates.

## VECTOR LIQUIDITY ENGINE v2 + OPS (ENFORCED)

- **Level zones (net $B):** DANGER &lt;1,900 · SELECTIVE 1,900–2,200 · DEPLOY ≥2,200. Institutions optimize range; OLYMPUS optimizes **vector** (7d Δ net liq).
- **States 1–6** live in `vector_liquidity.py` and are written into `directives.json` → §11 dashboard. **State 2** (DANGER + EXPANDING) = selective strike window; **State 6** (DEPLOY + CONTRACTING) = secure tactical profits — not panic-selling core into weakness.
- **`active_actions.json`** freezes broad BUYs in states **1, 4, 6** only. It does **not** freeze State 2 strikes (still gated by thesis + GOD score + OPS).
- **OPS (OLYMPUS Premium Score):** `tools/premium_score.py` — stock vs **sector peer median** P/S and forward P/E. GEM “fair value” can still be **expensive vs peers** (KTOS lesson). **OPS ≥ 180** forces BUY → WATCH in `build_active_actions.py` regardless of letter grade.
- **Core vs satellite:** `gem_inputs/core_satellite.json`. Core = compounders — do not sell on profit alone (thesis death only). Satellite = tactical sleeve; harvest default **≥35% gross** before recycle (20% is structurally thin after DE Abgeltungsteuer + opportunity cost).

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

### TASK — GITHUB ACTIONS SETUP (Sunday)
Create .github/workflows/wednesday_recalibration.yml that:
1. Triggers every Wednesday at 05:00 UTC (07:00 Berlin)
2. Checks out the gods_plan repo
3. Runs python3 scripts/wednesday_recalibration.py
4. Commits and pushes any score changes
5. Sends Telegram confirmation to GOD

This removes laptop dependency from Wednesday recalibration entirely.
