"""
titan_K v2 — Olympus Engine (v2: News-Aware Intelligence)
Fetches LIVE news for every ticker, feeds it to GPT-4o alongside price data,
generates forward estimates with score revisions, highlights critical alerts.
"""
import json
import os
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional

import yfinance as yf
from openai import OpenAI

from config import (
    OPENAI_API_KEY, PORTFOLIO, WATCHLIST, WEIGHTS,
    TITAN_SYSTEM_URL, TIMEZONE,
)

logger = logging.getLogger("titan_k.olympus")

client = OpenAI(api_key=OPENAI_API_KEY)

HISTORY_FILE = os.path.join("data", "olympus_history.json")
OLYMPUS_OUTPUT = os.path.join("data", "OLYMPUS_LIVE.html")
OLYMPUS_TEMPLATE = "TITAN_SYSTEM_v4.html"


# ══════════════════════════════════════════════════════════════════════════════
# NEWS FETCHER — the missing intelligence layer
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_ticker_news(tickers: List[str]) -> Dict[str, List[str]]:
    """Fetch latest headlines for each ticker via yfinance."""
    all_news = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            news_items = t.news or []
            headlines = []
            for item in news_items[:5]:
                content = item.get("content", {})
                title = content.get("title", item.get("title", ""))
                if title:
                    headlines.append(title)
            if headlines:
                all_news[ticker] = headlines
        except Exception as e:
            logger.debug(f"News fetch failed for {ticker}: {e}")
    logger.info(f"Fetched news for {len(all_news)}/{len(tickers)} tickers")
    return all_news


def _build_portfolio_context() -> str:
    """Build current portfolio scores + thesis for GPT context."""
    lines = []
    for broker, positions in PORTFOLIO.items():
        for pos in positions:
            score = pos.get("score", "?")
            lines.append(
                f"  {pos['ticker']} ({pos['name']}): "
                f"Current Score={score}/10, Action={pos.get('action','?')}, "
                f"Thesis={pos.get('thesis','?')}"
            )
    for w in WATCHLIST:
        lines.append(
            f"  {w['ticker']} ({w['name']}): "
            f"Current Score={w.get('score','?')}/10, "
            f"Entry={w.get('entry','?')}, Target=${w.get('target_usd','?')}"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def run_olympus_update() -> dict:
    """Full pipeline: fetch data + news -> GPT forecast + scores -> deltas -> save -> HTML -> Telegram."""
    import pytz
    berlin = pytz.timezone(TIMEZONE)
    now = datetime.now(berlin)
    today_key = now.strftime("%Y-%m-%d")
    logger.info(f"Olympus update started: {now.strftime('%H:%M %Z')}")

    from market_data import fetch_market_snapshot, calculate_titan_k_index, get_vix_regime, fetch_stock_prices, fetch_fx_rate

    snapshot = fetch_market_snapshot()
    composite = calculate_titan_k_index(snapshot, WEIGHTS)

    vix_val = snapshot.get("VIX", {}).get("value", 0)
    vix_num = float(vix_val) if isinstance(vix_val, (int, float)) else 0
    regime_name, deploy_pct, regime_label = get_vix_regime(vix_num)

    all_tickers = set()
    for broker_positions in PORTFOLIO.values():
        for pos in broker_positions:
            all_tickers.add(pos["ticker"])
    for w in WATCHLIST:
        all_tickers.add(w["ticker"])
    stock_prices = fetch_stock_prices(list(all_tickers))

    try:
        fx_rate = fetch_fx_rate()
    except Exception:
        fx_rate = 1.155

    logger.info("Fetching real-time news for all tickers...")
    news = _fetch_ticker_news(list(all_tickers))

    yesterday = _load_yesterday()

    forecasts = _generate_forecasts(snapshot, stock_prices, news, yesterday)

    deltas = _compute_deltas(forecasts, yesterday)

    alerts = forecasts.get("alerts", [])

    result = {
        "date": today_key,
        "timestamp": now.strftime("%Y-%m-%d %H:%M %Z"),
        "composite": composite,
        "regime": regime_name,
        "deploy_pct": deploy_pct,
        "regime_label": regime_label,
        "fx_rate": fx_rate,
        "vix": vix_num,
        "environment": forecasts.get("environment", f"VIX {vix_num:.0f} — {regime_name}"),
        "snapshot": {k: v for k, v in snapshot.items() if isinstance(v.get("value"), (int, float))},
        "stock_prices": stock_prices,
        "news": news,
        "forecasts": forecasts,
        "deltas": deltas,
        "alerts": alerts,
    }

    _save_snapshot(today_key, forecasts, snapshot, stock_prices)

    try:
        html = generate_olympus_html(result)
        os.makedirs("data", exist_ok=True)
        with open(OLYMPUS_OUTPUT, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"Olympus HTML written: {OLYMPUS_OUTPUT}")
    except Exception as e:
        logger.error(f"HTML generation failed: {e}", exc_info=True)

    logger.info(f"Olympus update complete — {len(alerts)} alerts")

    write_directives_json(result)
    return result


def write_directives_json(data: dict) -> None:
    """Write data/directives.json for downstream consumers (dashboard, scripts, /olympus)."""
    regime = data.get("regime", "?")
    regime_map = {
        "CALM": "CALM",
        "NORMAL": "NORMAL",
        "FEAR": "FEAR ZONE",
        "CRISIS": "CRISIS",
    }
    regime_str = regime_map.get(regime, str(regime))

    fc = data.get("forecasts") or {}
    issues = [str(x).strip() for x in (fc.get("global_issues") or []) if str(x).strip()]
    directive_parts: List[str] = issues[:3]
    for a in data.get("alerts") or []:
        if len(directive_parts) >= 3:
            break
        act = (a.get("action") or a.get("event") or "").strip()
        line = f"{a.get('ticker', '?')}: {act}".strip()
        if len(line) > 2:
            directive_parts.append(line)
    env_fallback = (data.get("environment") or "Review OLYMPUS dashboard for today's actions.")[:220]
    pad = ["Review live matrix + alerts in OLYMPUS.", "Confirm limits/stops vs state.json.", env_fallback]
    i = 0
    while len(directive_parts) < 3:
        directive_parts.append(pad[min(i, len(pad) - 1)])
        i += 1
    directive_text = " | ".join(directive_parts[:3])

    alert_strs: List[str] = []
    for a in data.get("alerts") or []:
        alert_strs.append(
            f"{a.get('ticker', '?')}: {a.get('event', '')} — {a.get('action', '')} [{a.get('severity', 'INFO')}]"
        )
    if not alert_strs:
        alert_strs = ["No critical alerts."]

    payload = {
        "date": data.get("date", datetime.now().strftime("%Y-%m-%d")),
        "vix": round(float(data.get("vix", 0)), 2),
        "regime": regime_str,
        "deploy_pct": int(data.get("deploy_pct", 0)),
        "directive": directive_text,
        "alerts": alert_strs,
    }
    path = os.path.join("data", "directives.json")
    os.makedirs("data", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("Wrote %s", path)


# ══════════════════════════════════════════════════════════════════════════════
# GPT-4o FORECAST ENGINE (v2: NEWS-AWARE + SCORE REVISION)
# ══════════════════════════════════════════════════════════════════════════════

FORECAST_SYSTEM = """You are the Olympus Intelligence Engine — the brain of the TITAN Investment System.
You have access to LIVE market data AND today's breaking news for every stock.

You operate as the TITAN ARCHITECT: an elite AI investment strategist that filters every
stock through the 10 Global Titan Criteria before issuing any BUY, HOLD, or score above 7.

══ THE 10 GLOBAL TITAN CRITERIA ══

1. QUANTITATIVE GATE (Mandatory — calculate or flag UNKNOWN if data missing)
   a) Graham Number = sqrt(22.5 x EPS x BVPS). Flag if current price > Graham Number.
   b) Magic Formula: ROIC > 25% AND Earnings Yield (EBIT/EV) is attractive vs peers.
   c) Lynch Filter: PEG Ratio < 1.0 AND Inventory Growth < Sales Growth.
   d) Buffett Shield: Debt-to-Equity < 0.5.

2. PORTFOLIO ARCHITECTURE (Ray Dalio Logic)
   Classify asset as SPEAR (High Growth/Alpha) or SHIELD (Value/Defensive).
   Note diversification impact on existing portfolio.

3. BOGLE COST GUARD
   For any ETF/Fund: flag if Expense Ratio > 0.15%.

4. SCORING RULES (non-negotiable)
   - NEVER guess a Graham Number. Missing EPS or BVPS = state "UNKNOWN — awaiting filing."
   - Always state the data source assumption (e.g. "Based on Q3 2025 10-Q").
   - Score 8+ REQUIRES passing at least 3 of 4 quantitative gates.
   - Score 10 REQUIRES all 4 gates passed AND clear paradigm-shift thesis intact.
   - Broken thesis = score 1-3 regardless of quant metrics.

Your broader job:
1. Detect critical events (dilution, broken thesis, earnings surprise, war escalation, etc.)
2. Revise stock scores based on news AND quantitative gate results
3. Produce precise forward price estimates
4. Flag alerts that demand immediate attention

BRUTALLY HONEST. If news is catastrophic, slash the score. No cheerleading.
ALWAYS respond with valid JSON only. No markdown fences."""

FORECAST_USER = """You are updating the OLYMPUS dashboard. Today is {today}.

══ LIVE MARKET DATA — 30 INDICATORS ══
{indicators_block}

══ LIVE STOCK PRICES ══
{stocks_block}

══ CURRENT PORTFOLIO SCORES & THESES ══
{portfolio_context}

══ TODAY'S BREAKING NEWS (from financial feeds) ══
{news_block}

{yesterday_block}

══ INSTRUCTIONS ══
1. Read ALL the news carefully. Detect any material event: dilution, offering, guidance cut,
   earnings miss/beat, analyst upgrade/downgrade, war escalation, regulatory action, etc.
2. For EACH stock: run the TITAN ARCHITECT quantitative gate:
   a) Graham Number = sqrt(22.5 x EPS x BVPS). Use latest 10-Q/10-K. State assumption.
      If data unavailable, write "UNKNOWN — awaiting filing" — never guess.
   b) Magic Formula: ROIC > 25%? Earnings Yield (EBIT/EV) attractive? Yes/No/UNKNOWN.
   c) Lynch Filter: PEG < 1.0? Inventory Growth < Sales Growth? Yes/No/UNKNOWN.
   d) Buffett Shield: Debt-to-Equity < 0.5? Yes/No/UNKNOWN.
   e) Classify as SPEAR or SHIELD.
   f) For ETFs only: Expense Ratio > 0.15%? Flag if yes.
3. Produce new_score (1-10) based on ALL information: news + quant gates.
   Score 8+ requires 3+ gates passed. Score 10 requires all 4 gates + intact thesis.
   Broken thesis = 1-3 regardless of metrics.
4. For EACH stock and indicator: produce 1w, 1m, 1y, 5y forward estimates.
5. Generate ALERTS for score change >= 2 points or any critical event.
6. Determine the current global environment description.

Return ONLY this JSON:
{{
  "environment": "Short phrase describing today's global market environment",
  "global_issues": ["issue 1 with specific detail", "issue 2", "issue 3", "issue 4", "issue 5"],
  "alerts": [
    {{
      "ticker": "CRSP",
      "severity": "CRITICAL",
      "old_score": 8,
      "new_score": 5,
      "event": "Announced $350M convertible notes offering — dilutive to shareholders",
      "action": "REMOVE limit order. Wait for stabilization below $40.",
      "forecast_impact": "1w est dropped from $58 to $45, 1m from $68 to $50"
    }}
  ],
  "indicators": {{
    "INDICATOR_NAME": {{
      "est_1w": number,
      "est_1m": number,
      "est_1y": number,
      "est_5y": number,
      "why_changed": "1 sentence with specific reason"
    }}
  }},
  "stocks": {{
    "TICKER": {{
      "old_score": number,
      "new_score": number,
      "score_reason": "Why score changed or stayed same — reference specific news and gate results",
      "est_1w": number,
      "est_1m": number,
      "est_1y": number,
      "est_5y": number,
      "why_changed": "1 sentence referencing today's news if applicable",
      "architect": {{
        "graham_number": "e.g. $42.10 (Based on Q3 2025 10-Q: EPS $1.87, BVPS $8.92) — BELOW current price" or "UNKNOWN — awaiting filing",
        "magic_formula": "ROIC: 31% (PASS) / Earnings Yield: 4.2% (PASS)" or "UNKNOWN",
        "lynch_filter": "PEG: 0.82 (PASS) / Inventory vs Sales: N/A for software" or "FAIL: PEG 2.1",
        "buffett_shield": "D/E: 0.32 (PASS)" or "FAIL: D/E 1.8",
        "gates_passed": 3,
        "classification": "SPEAR",
        "etf_expense_ratio": null,
        "verdict": "PASS — 3/4 gates met. High-conviction SPEAR with intact paradigm thesis.",
        "data_assumption": "Based on most recent 10-Q (Q3 2025, filed Nov 2025)"
      }}
    }}
  }}
}}"""


def _generate_forecasts(snapshot: Dict, stock_prices: Dict, news: Dict, yesterday: Optional[Dict]) -> Dict:
    """Call GPT-4o with live data + news to produce news-aware forecasts and score revisions."""
    import pytz
    berlin = pytz.timezone(TIMEZONE)
    today_str = datetime.now(berlin).strftime("%A, %B %d, %Y")

    ind_lines = []
    for name, data in sorted(snapshot.items()):
        val = data.get("value", "N/A")
        chg = data.get("change_pct", 0)
        sig = data.get("signal", "")
        if isinstance(val, (int, float)):
            ind_lines.append(f"  {name}: {val} ({chg:+.2f}%) — {sig}")
        else:
            ind_lines.append(f"  {name}: {val} — {sig}")

    stock_lines = []
    for ticker, data in sorted(stock_prices.items()):
        price = data.get("price", "N/A")
        chg = data.get("change_pct", 0)
        stock_lines.append(f"  {ticker}: ${price} ({chg:+.2f}%)")

    news_lines = []
    if news:
        for ticker, headlines in sorted(news.items()):
            news_lines.append(f"  [{ticker}]")
            for h in headlines[:4]:
                news_lines.append(f"    - {h}")
    else:
        news_lines.append("  (No news fetched — estimate based on price action only)")

    portfolio_context = _build_portfolio_context()

    yesterday_block = ""
    if yesterday:
        yesterday_block = "══ YESTERDAY'S ESTIMATES (compare and explain ANY changes) ══\n"
        y_stocks = yesterday.get("stocks", {})
        if y_stocks:
            for ticker, est in sorted(y_stocks.items()):
                old_score = est.get("new_score", est.get("old_score", "?"))
                yesterday_block += (
                    f"  {ticker}: score={old_score} "
                    f"1w={est.get('est_1w','?')} 1m={est.get('est_1m','?')} "
                    f"1y={est.get('est_1y','?')} 5y={est.get('est_5y','?')}\n"
                )
        y_ind = yesterday.get("indicators", {})
        if y_ind:
            for name, est in sorted(y_ind.items()):
                yesterday_block += (
                    f"  {name}: 1w={est.get('est_1w','?')} 1m={est.get('est_1m','?')} "
                    f"1y={est.get('est_1y','?')} 5y={est.get('est_5y','?')}\n"
                )
    else:
        yesterday_block = "No yesterday data — this is the first run."

    prompt = FORECAST_USER.format(
        today=today_str,
        indicators_block="\n".join(ind_lines),
        stocks_block="\n".join(stock_lines),
        portfolio_context=portfolio_context,
        news_block="\n".join(news_lines),
        yesterday_block=yesterday_block,
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": FORECAST_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.25,
            max_tokens=5000,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r'^```json\s*|\s*```$', '', raw)
        result = json.loads(raw)
        n_alerts = len(result.get("alerts", []))
        logger.info(f"GPT forecast complete: {n_alerts} alerts generated")
        return result
    except Exception as e:
        logger.error(f"Forecast GPT call failed: {e}", exc_info=True)
        return {"environment": "ERROR", "global_issues": ["Forecast generation failed"],
                "alerts": [], "indicators": {}, "stocks": {}}


# ══════════════════════════════════════════════════════════════════════════════
# DELTA COMPUTATION
# ══════════════════════════════════════════════════════════════════════════════

def _compute_deltas(today_forecasts: Dict, yesterday: Optional[Dict]) -> Dict:
    """Compute numeric deltas between today's and yesterday's estimates."""
    deltas = {"indicators": {}, "stocks": {}}
    if not yesterday:
        return deltas

    for section in ("indicators", "stocks"):
        today_section = today_forecasts.get(section, {})
        yesterday_section = yesterday.get(section, {})
        for name, today_est in today_section.items():
            if name not in yesterday_section:
                continue
            yday_est = yesterday_section[name]
            d = {}
            for tf in ("est_1w", "est_1m", "est_1y", "est_5y"):
                t_val = today_est.get(tf)
                y_val = yday_est.get(tf)
                if isinstance(t_val, (int, float)) and isinstance(y_val, (int, float)) and y_val != 0:
                    d[tf] = round(t_val - y_val, 4)
                    d[f"{tf}_pct"] = round((t_val - y_val) / abs(y_val) * 100, 2)
            deltas[section][name] = d
    return deltas


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def _load_yesterday() -> Optional[Dict]:
    """Load the most recent forecast snapshot."""
    if not os.path.exists(HISTORY_FILE):
        return None
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        if not history:
            return None
        latest_key = sorted(history.keys())[-1]
        return history[latest_key].get("forecasts")
    except Exception as e:
        logger.warning(f"Could not load history: {e}")
        return None


def _save_snapshot(date_key: str, forecasts: Dict, snapshot: Dict, stock_prices: Dict):
    """Append today's forecast to the history file."""
    os.makedirs("data", exist_ok=True)
    history = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}

    keys = sorted(history.keys())
    while len(keys) > 29:
        del history[keys.pop(0)]

    snapshot_save = {}
    for k, v in snapshot.items():
        val = v.get("value")
        if isinstance(val, (int, float)):
            snapshot_save[k] = {"value": val, "change_pct": v.get("change_pct", 0)}

    history[date_key] = {
        "timestamp": datetime.now().isoformat(),
        "forecasts": forecasts,
        "snapshot": snapshot_save,
        "stock_prices": {t: {"price": d.get("price")} for t, d in stock_prices.items()},
    }

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    logger.info(f"Snapshot saved: {date_key}")


# ══════════════════════════════════════════════════════════════════════════════
# HTML GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_olympus_html(data: dict) -> str:
    """Read Olympus template, inject live data, reorder sections, fix JS."""
    import re as _re

    template_path = OLYMPUS_TEMPLATE
    if not os.path.exists(template_path):
        template_path = os.path.join(os.path.dirname(__file__), OLYMPUS_TEMPLATE)

    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    timestamp = data.get("timestamp", "")
    composite = data.get("composite", 0)
    vix = data.get("vix", 0)
    environment = data.get("environment", "")

    # ── Header patches ──────────────────────────────────────────────────
    html = html.replace(
        '<span class="val warn">29.48</span>',
        f'<span class="val warn">{vix:.2f}</span>',
    )
    html = html.replace(
        '<span class="val warn">56</span>',
        f'<span class="val warn">{composite}</span>',
    )
    if environment:
        html = html.replace(
            '<span id="txt-env-val" class="val warn">US-IRAN WAR D8</span>',
            f'<span id="txt-env-val" class="val warn">{environment}</span>',
        )
        html = html.replace(
            "envVal: 'US-IRAN WAR D8'",
            f"envVal: '{environment}'",
        )
    html = _re.sub(
        r'LAST UPDATED: \d{1,2} [A-Z]{3} \d{4}',
        f'LIVE UPDATE: {timestamp}',
        html,
    )

    # ── Inject live scorecard ───────────────────────────────────────────
    html = _inject_live_scorecard(html, data)

    # ── Inject live MATRIX_DATA + fix FX_RATE ───────────────────────────
    html = _inject_live_matrix_data(html, data)

    # ── Fix broken JS quotes in renderMatrixTables ──────────────────────
    # Template uses font-family:'Share Tech Mono' inside JS single-quoted
    # strings, which crashes the parser. Fix in JS context only.
    html = html.replace(
        """font-family:'Share Tech Mono',monospace""",
        """font-family:Share Tech Mono,monospace""",
    )

    # ── Replace broken corsproxy FX fetch with live-injected rate ───────
    fx_rate = data.get("fx_rate", 1.155)
    html = _re.sub(
        r"async function fetchFXRate\(\).*?renderMatrixTables\(\);\s*\}",
        f"""async function fetchFXRate() {{
  document.getElementById('fx-rate-display').textContent = '1 EUR = $' + FX_RATE.toFixed(4) + ' USD';
  document.getElementById('fx-time-display').textContent = 'Injected by TITAN engine — {timestamp}';
  renderMatrixTables();
}}""",
        html,
        flags=_re.DOTALL,
    )

    # ── Inject live sections into HTML so reorder can find them ─────────
    alerts_html = _build_alerts_html(data)
    global_issues_html = _build_global_issues_html(data)
    forecast_html = _build_forecast_html(data)
    live_block = alerts_html + "\n" + global_issues_html + "\n" + forecast_html

    price_marker = "<!-- ===== PRICE MATRIX ===== -->"
    if price_marker in html:
        html = html.replace(price_marker, live_block + "\n" + price_marker)

    # ── Reorder sections: Scorecard first, then Price Matrix, etc. ──────
    html = _reorder_sections(html, data)

    return html


def _reorder_sections(html: str, data: dict) -> str:
    """Extract sections by comment markers and reassemble in priority order.

    Target order (actionable first):
      1. ALERTS (live injected — immediate attention)
      2. STOCK SCORECARD (buy/sell decisions)
      3. PRICE MATRIX (current prices & upside)
      4. REGIME MATRIX (market risk level)
      5. GLOBAL ISSUES (live injected — context)
      6. FORECAST MATRIX (live injected — predictions)
      7. EARNINGS CALENDAR (upcoming events)
      8. CAPITAL MAP (portfolio allocation)
      9. 3-LAYER SYSTEM (methodology)
     10. SYSTEM ARCHITECTURE (meta)
     11. MINERVA PROTOCOL
     12. TUITION LOG
    """
    import re as _re

    markers = [
        ("SYSTEM ARCHITECTURE", "<!-- ===== SYSTEM ARCHITECTURE ===== -->"),
        ("REGIME MATRIX",       "<!-- ===== REGIME MATRIX ===== -->"),
        ("STOCK SCORECARD",     "<!-- ===== STOCK SCORECARD"),
        ("PRICE MATRIX",        "<!-- ===== PRICE MATRIX ===== -->"),
        ("3-LAYER SYSTEM",      "<!-- ===== 3-LAYER SYSTEM ===== -->"),
        ("EARNINGS CALENDAR",   "<!-- ===== EARNINGS CALENDAR ===== -->"),
        ("CAPITAL MAP",         "<!-- ===== CAPITAL MAP ===== -->"),
        ("MINERVA PROTOCOL",    "<!-- ===== MINERVA PROTOCOL ===== -->"),
        ("TUITION LOG",         "<!-- ===== TUITION LOG ===== -->"),
    ]

    live_markers = [
        ("ALERTS",          "<!-- ===== CRITICAL ALERTS (LIVE) ===== -->"),
        ("GLOBAL ISSUES",   "<!-- ===== GLOBAL ISSUES (LIVE) ===== -->"),
        ("FORECAST MATRIX", "<!-- ===== 30-INDEX FORECAST MATRIX (LIVE) ===== -->"),
    ]

    all_markers = markers + live_markers

    # Find positions
    positions = []
    for name, marker in all_markers:
        idx = html.find(marker)
        if idx >= 0:
            positions.append((idx, name, marker))

    if len(positions) < 5:
        logger.warning(f"Only found {len(positions)} sections — skipping reorder")
        return html

    positions.sort(key=lambda x: x[0])

    # Extract each section as the text from its marker to the next marker
    sections = {}
    for i, (idx, name, marker) in enumerate(positions):
        if i + 1 < len(positions):
            end = positions[i + 1][0]
        else:
            # Last section — find the closing </main> or end-of-sections
            end_markers = ["</main>", "<footer", "<!-- FOOTER"]
            end = len(html)
            for em in end_markers:
                em_idx = html.find(em, idx + 100)
                if em_idx >= 0 and em_idx < end:
                    end = em_idx
        sections[name] = html[idx:end]

    # Find everything BEFORE the first section (header, nav, CSS, etc.)
    first_pos = positions[0][0] if positions else 0
    preamble = html[:first_pos]

    # Find everything AFTER the last section (footer, closing tags)
    last_pos = positions[-1][0]
    last_section = sections.get(positions[-1][1], "")
    after_all = html[last_pos + len(last_section):]

    # Build alerts/issues/forecast if not already in sections
    if "ALERTS" not in sections:
        sections["ALERTS"] = _build_alerts_html(data) + "\n"
    if "GLOBAL ISSUES" not in sections:
        sections["GLOBAL ISSUES"] = _build_global_issues_html(data) + "\n"
    if "FORECAST MATRIX" not in sections:
        sections["FORECAST MATRIX"] = _build_forecast_html(data) + "\n"

    # Desired order — actionable info first, methodology/architecture last
    order = [
        "ALERTS",
        "STOCK SCORECARD",
        "PRICE MATRIX",
        "REGIME MATRIX",
        "GLOBAL ISSUES",
        "FORECAST MATRIX",
        "EARNINGS CALENDAR",
        "CAPITAL MAP",
        "3-LAYER SYSTEM",
        "SYSTEM ARCHITECTURE",
        "MINERVA PROTOCOL",
        "TUITION LOG",
    ]

    body = ""
    for name in order:
        if name in sections:
            body += sections[name]

    result = preamble + body + after_all
    logger.info(f"Sections reordered: {[n for n in order if n in sections]}")
    return result


def _build_alerts_html(data: dict) -> str:
    """Build CRITICAL ALERTS section — score downgrades, broken theses, dilution events."""
    alerts = data.get("alerts", [])
    if not alerts:
        return ""

    cards = ""
    for a in alerts:
        severity = a.get("severity", "WARNING")
        ticker = a.get("ticker", "?")
        event = a.get("event", "")
        action = a.get("action", "")
        impact = a.get("forecast_impact", "")
        old_score = a.get("old_score", "?")
        new_score = a.get("new_score", "?")

        sev_color = "var(--red)" if severity == "CRITICAL" else "var(--warn)"
        score_color = "var(--red)" if isinstance(new_score, (int, float)) and new_score <= 4 else "var(--warn)"

        cards += f"""    <div style="background:var(--bg2);border:1px solid {sev_color};border-left:5px solid {sev_color};border-radius:4px;padding:18px;margin-bottom:12px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px;">
        <div>
          <span style="font-family:'Orbitron',monospace;font-size:16px;color:{sev_color};font-weight:900;">{severity}</span>
          <span style="font-family:'Orbitron',monospace;font-size:16px;color:var(--gold);margin-left:12px;">{ticker}</span>
        </div>
        <div style="display:flex;gap:12px;align-items:center;">
          <div style="text-align:center;">
            <div style="font-family:'Share Tech Mono',monospace;font-size:9px;color:var(--text-dim);">OLD SCORE</div>
            <span class="score-badge mid" style="font-size:14px;">{old_score}/10</span>
          </div>
          <span style="font-size:20px;color:{sev_color};">→</span>
          <div style="text-align:center;">
            <div style="font-family:'Share Tech Mono',monospace;font-size:9px;color:var(--text-dim);">NEW SCORE</div>
            <span class="score-badge low" style="font-size:14px;background:rgba(255,59,59,0.15);color:{score_color};border:1px solid {score_color};">{new_score}/10</span>
          </div>
        </div>
      </div>
      <div style="font-size:14px;color:var(--text);line-height:1.7;margin-bottom:8px;"><strong style="color:{sev_color};">EVENT:</strong> {event}</div>
      <div style="font-size:13px;color:var(--green);line-height:1.6;margin-bottom:6px;"><strong>ACTION:</strong> {action}</div>
      <div style="font-size:12px;color:var(--warn);line-height:1.6;"><strong>FORECAST IMPACT:</strong> {impact}</div>
    </div>
"""

    return f"""
<!-- ===== CRITICAL ALERTS (LIVE) ===== -->
<section id="alerts">
  <div class="section-header">
    <span class="num" style="background:rgba(255,59,59,0.2);border-color:var(--red);color:var(--red);">ALERT</span>
    <h2 style="color:var(--red) !important;">CRITICAL ALERTS — IMMEDIATE ATTENTION REQUIRED</h2>
  </div>
{cards}
</section>
"""


def _build_global_issues_html(data: dict) -> str:
    """Build the Global Issues banner."""
    issues = data.get("forecasts", {}).get("global_issues", [])
    if not issues:
        return ""

    items = ""
    for issue in issues[:5]:
        items += f'    <div style="background:var(--bg3);border:1px solid var(--border);border-left:3px solid var(--warn);padding:10px 14px;border-radius:3px;font-size:13px;color:var(--text);line-height:1.6;word-break:keep-all;">{issue}</div>\n'

    return f"""
<!-- ===== GLOBAL ISSUES (LIVE) ===== -->
<section id="global-issues">
  <div class="section-header">
    <span class="num">LIVE</span>
    <h2>GLOBAL ISSUES — TOP 5 MARKET-MOVING FACTORS TODAY</h2>
  </div>
  <div style="display:grid;grid-template-columns:1fr;gap:8px;margin-bottom:24px;">
{items}  </div>
</section>
"""


def _build_forecast_html(data: dict) -> str:
    """Build the 30-Index Forecast Matrix + Stock matrix with score columns."""
    forecasts = data.get("forecasts", {})
    snapshot = data.get("snapshot", {})
    deltas = data.get("deltas", {})
    yesterday = _load_yesterday()

    indicator_rows = _build_indicator_rows(
        forecasts.get("indicators", {}),
        snapshot,
        deltas.get("indicators", {}),
        yesterday.get("indicators", {}) if yesterday else {},
    )

    stock_prices = data.get("stock_prices", {})
    stock_snapshot = {}
    for ticker, pdata in stock_prices.items():
        stock_snapshot[ticker] = {"value": pdata.get("price"), "change_pct": pdata.get("change_pct", 0)}

    stock_rows = _build_stock_rows(
        forecasts.get("stocks", {}),
        stock_snapshot,
        deltas.get("stocks", {}),
        yesterday.get("stocks", {}) if yesterday else {},
    )

    timestamp = data.get("timestamp", "")

    return f"""
<!-- ===== 30-INDEX FORECAST MATRIX (LIVE) ===== -->
<section id="forecast-matrix">
  <div class="section-header">
    <span class="num">LIVE</span>
    <h2>30-INDEX FORECAST MATRIX — GPT-4o ESTIMATES</h2>
  </div>

  <div class="note-box gold" style="margin-bottom:18px;">
    <strong>HOW TO READ:</strong> Current = live price. Est = GPT-4o forward estimates reflecting TODAY'S NEWS.
    Yday = yesterday's estimate. Delta = change in estimate.
    <span style="color:var(--green);">Green</span> = improved. <span style="color:var(--red);">Red</span> = worsened.
    <br><strong>Last updated:</strong> <span style="color:var(--gold);font-family:'Share Tech Mono',monospace;">{timestamp}</span>
  </div>

  <div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:var(--text-dim);letter-spacing:1px;margin-bottom:12px;">MACRO INDICATORS</div>
  <div style="overflow-x:auto;margin-bottom:28px;">
    <table>
      <thead>
        <tr>
          <th>INDEX</th><th>CURRENT</th>
          <th>1W EST</th><th>1M EST</th><th>1Y EST</th><th>5Y EST</th>
          <th>YDAY 1W</th><th>YDAY 1M</th><th>YDAY 1Y</th><th>YDAY 5Y</th>
          <th>DELTA</th><th>WHY CHANGED</th>
        </tr>
      </thead>
      <tbody>
{indicator_rows}
      </tbody>
    </table>
  </div>

  <div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:var(--text-dim);letter-spacing:1px;margin-bottom:12px;">PORTFOLIO &amp; WATCHLIST — WITH LIVE SCORE REVISION + TITAN ARCHITECT GATE</div>
  <div style="overflow-x:auto;">
    <table>
      <thead>
        <tr>
          <th>STOCK</th><th>SCORE</th><th>CURRENT</th>
          <th>1W EST</th><th>1M EST</th><th>1Y EST</th><th>5Y EST</th>
          <th>YDAY 1W</th><th>YDAY 1M</th><th>YDAY 1Y</th><th>YDAY 5Y</th>
          <th>DELTA</th><th>ARCHITECT GATE</th><th>WHY CHANGED</th>
        </tr>
      </thead>
      <tbody>
{stock_rows}
      </tbody>
    </table>
  </div>
</section>
"""


def _build_indicator_rows(forecasts: dict, snapshot: dict, deltas: dict, yesterday: dict) -> str:
    rows = ""
    for name in sorted(forecasts.keys()):
        est = forecasts[name]
        snap = snapshot.get(name, {})
        current = snap.get("value", "—")
        chg = snap.get("change_pct", 0)

        e1w, e1m, e1y, e5y = est.get("est_1w", "—"), est.get("est_1m", "—"), est.get("est_1y", "—"), est.get("est_5y", "—")
        why = est.get("why_changed", "—")

        y = yesterday.get(name, {})
        y1w, y1m, y1y, y5y = y.get("est_1w", "—"), y.get("est_1m", "—"), y.get("est_1y", "—"), y.get("est_5y", "—")

        d = deltas.get(name, {})
        delta_1m_pct = d.get("est_1m_pct", 0)
        delta_color = "c-green" if delta_1m_pct > 0 else "c-red" if delta_1m_pct < 0 else "c-dim"
        delta_display = f"{delta_1m_pct:+.1f}%" if delta_1m_pct else "—"

        chg_color = "c-green" if chg >= 0 else "c-red"

        rows += f"""        <tr>
          <td class="ticker-cell">{name}</td>
          <td><span class="{chg_color}">{_fmt(current, False)}</span></td>
          <td>{_fmt(e1w, False)}</td><td>{_fmt(e1m, False)}</td>
          <td class="c-green">{_fmt(e1y, False)}</td><td class="c-gold">{_fmt(e5y, False)}</td>
          <td class="c-dim">{_fmt(y1w, False)}</td><td class="c-dim">{_fmt(y1m, False)}</td>
          <td class="c-dim">{_fmt(y1y, False)}</td><td class="c-dim">{_fmt(y5y, False)}</td>
          <td><span class="{delta_color}">{delta_display}</span></td>
          <td style="font-size:11px;max-width:220px;color:var(--text-dim);">{why}</td>
        </tr>
"""
    return rows


def _build_stock_rows(forecasts: dict, snapshot: dict, deltas: dict, yesterday: dict) -> str:
    rows = ""
    for name in sorted(forecasts.keys()):
        est = forecasts[name]
        snap = snapshot.get(name, {})
        current = snap.get("value", snap.get("price", "—"))
        chg = snap.get("change_pct", 0)

        old_score = est.get("old_score", "?")
        new_score = est.get("new_score", "?")
        score_reason = est.get("score_reason", "")

        e1w, e1m, e1y, e5y = est.get("est_1w", "—"), est.get("est_1m", "—"), est.get("est_1y", "—"), est.get("est_5y", "—")
        why = est.get("why_changed", "—")

        y = yesterday.get(name, {})
        y1w, y1m, y1y, y5y = y.get("est_1w", "—"), y.get("est_1m", "—"), y.get("est_1y", "—"), y.get("est_5y", "—")

        d = deltas.get(name, {})
        delta_1m_pct = d.get("est_1m_pct", 0)
        delta_color = "c-green" if delta_1m_pct > 0 else "c-red" if delta_1m_pct < 0 else "c-dim"
        delta_display = f"{delta_1m_pct:+.1f}%" if delta_1m_pct else "—"

        chg_color = "c-green" if chg >= 0 else "c-red"

        # Score badge
        score_changed = isinstance(old_score, (int, float)) and isinstance(new_score, (int, float)) and old_score != new_score
        if isinstance(new_score, (int, float)):
            if new_score >= 8:
                badge_class = "high"
            elif new_score >= 5:
                badge_class = "mid"
            else:
                badge_class = "low"
        else:
            badge_class = "mid"

        if score_changed:
            score_dir = "▼" if new_score < old_score else "▲"
            score_html = (
                f'<span style="font-size:10px;color:var(--text-dim);">{old_score}→</span>'
                f'<span class="score-badge {badge_class}" style="font-size:12px;">{score_dir}{new_score}/10</span>'
            )
            row_style = ' style="background:rgba(255,59,59,0.06);"' if new_score < old_score else ' style="background:rgba(0,255,136,0.04);"'
        else:
            score_html = f'<span class="score-badge {badge_class}" style="font-size:12px;">{new_score}/10</span>'
            row_style = ""

        rows += f"""        <tr{row_style}>
          <td class="ticker-cell">{name}</td>
          <td>{score_html}</td>
          <td><span class="{chg_color}">{_fmt(current, True)}</span></td>
          <td>{_fmt(e1w, True)}</td><td>{_fmt(e1m, True)}</td>
          <td class="c-green">{_fmt(e1y, True)}</td><td class="c-gold">{_fmt(e5y, True)}</td>
          <td class="c-dim">{_fmt(y1w, True)}</td><td class="c-dim">{_fmt(y1m, True)}</td>
          <td class="c-dim">{_fmt(y1y, True)}</td><td class="c-dim">{_fmt(y5y, True)}</td>
          <td><span class="{delta_color}">{delta_display}</span></td>
          <td style="font-size:10px;max-width:200px;color:var(--text-dim);line-height:1.5;">{_fmt_architect(est.get('architect'))}</td>
          <td style="font-size:11px;max-width:180px;color:var(--text-dim);">{why}</td>
        </tr>
"""
    return rows


def _fmt(val, is_stock: bool) -> str:
    if val == "—" or val is None or val == "N/A":
        return '<span style="color:var(--text-dim)">—</span>'
    try:
        v = float(val)
        if is_stock:
            return f"${v:,.2f}" if v < 100 else f"${v:,.0f}"
        else:
            return f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"
    except (ValueError, TypeError):
        return str(val)


def _fmt_architect(arch: dict | None) -> str:
    """Render the TITAN ARCHITECT gate as a compact HTML cell."""
    if not arch:
        return '<span style="color:var(--text-dim)">—</span>'

    gates_passed = arch.get("gates_passed", 0)
    verdict = arch.get("verdict", "")
    classification = arch.get("classification", "")
    graham = arch.get("graham_number", "UNKNOWN")
    magic = arch.get("magic_formula", "UNKNOWN")
    lynch = arch.get("lynch_filter", "UNKNOWN")
    buffett = arch.get("buffett_shield", "UNKNOWN")
    assumption = arch.get("data_assumption", "")
    etf_er = arch.get("etf_expense_ratio")

    # Gate pass color
    if gates_passed >= 4:
        gate_color = "var(--green)"
        gate_label = f"✅ {gates_passed}/4 GATES"
    elif gates_passed >= 3:
        gate_color = "var(--gold)"
        gate_label = f"🟡 {gates_passed}/4 GATES"
    elif gates_passed >= 2:
        gate_color = "var(--warn)"
        gate_label = f"⚠️ {gates_passed}/4 GATES"
    else:
        gate_color = "var(--red)"
        gate_label = f"❌ {gates_passed}/4 GATES"

    cls_badge = (
        '<span style="color:var(--red);font-weight:bold;">⚔ SPEAR</span>'
        if classification == "SPEAR"
        else '<span style="color:var(--blue, #4fc3f7);font-weight:bold;">🛡 SHIELD</span>'
        if classification == "SHIELD"
        else ""
    )

    etf_line = ""
    if etf_er is not None:
        er_color = "var(--red)" if float(etf_er) > 0.15 else "var(--green)"
        etf_line = f'<div>ER: <span style="color:{er_color};">{etf_er}%</span></div>'

    return (
        f'<div style="font-weight:bold;color:{gate_color};margin-bottom:3px;">{gate_label}</div>'
        f'<div style="margin-bottom:2px;">{cls_badge}</div>'
        f'<div style="color:var(--text-dim);margin-bottom:2px;">Graham: {graham[:40]}</div>'
        f'<div style="color:var(--text-dim);margin-bottom:2px;">Magic: {magic[:35]}</div>'
        f'<div style="color:var(--text-dim);margin-bottom:2px;">Lynch: {lynch[:35]}</div>'
        f'<div style="color:var(--text-dim);margin-bottom:2px;">Buffett: {buffett[:30]}</div>'
        f'{etf_line}'
        f'<div style="color:var(--text-dim);font-style:italic;font-size:9px;">{assumption[:50]}</div>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# LIVE SCORECARD + MATRIX INJECTION
# ══════════════════════════════════════════════════════════════════════════════

def _inject_live_scorecard(html: str, data: dict) -> str:
    """Replace the static scorecard <tbody> with live GPT-revised scores."""
    import re as _re

    forecasts = data.get("forecasts", {})
    stock_forecasts = forecasts.get("stocks", {})
    stock_prices = data.get("stock_prices", {})
    alerts_by_ticker = {a["ticker"]: a for a in data.get("alerts", [])}

    all_positions = []
    for broker, positions in PORTFOLIO.items():
        for pos in positions:
            all_positions.append(pos)
    for w in WATCHLIST:
        all_positions.append(w)

    rows = ""
    seen_tickers = set()
    for pos in sorted(all_positions, key=lambda p: -(stock_forecasts.get(p["ticker"], {}).get("new_score", p.get("score", 0)) or 0)):
        ticker = pos["ticker"]
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)

        sf = stock_forecasts.get(ticker, {})
        new_score = sf.get("new_score", pos.get("score", "?"))
        old_score = sf.get("old_score", pos.get("score", "?"))
        score_reason = sf.get("score_reason", "")
        why = sf.get("why_changed", "")
        action = pos.get("action", "")

        price_data = stock_prices.get(ticker, {})
        chg_pct = price_data.get("change_pct", 0)
        current = price_data.get("price", "?")

        alert = alerts_by_ticker.get(ticker)

        if isinstance(new_score, (int, float)):
            if new_score >= 8:
                badge = f'<span class="score-badge high">{new_score}/10</span>'
            elif new_score >= 5:
                badge = f'<span class="score-badge mid">{new_score}/10</span>'
            else:
                badge = f'<span class="score-badge low">{new_score}/10</span>'
        else:
            badge = f'<span class="score-badge mid">{new_score}/10</span>'

        score_changed = isinstance(old_score, (int, float)) and isinstance(new_score, (int, float)) and old_score != new_score
        if score_changed:
            direction = "▼" if new_score < old_score else "▲"
            badge = (
                f'<span style="font-size:10px;color:var(--text-dim);">{old_score}→</span>'
                + badge
            )

        row_bg = ""
        if alert and alert.get("severity") == "CRITICAL":
            row_bg = ' style="background:rgba(255,59,59,0.08);"'
        elif score_changed and new_score < old_score:
            row_bg = ' style="background:rgba(255,165,0,0.06);"'

        chg_color = "c-green" if chg_pct >= 0 else "c-red"
        chg_str = f"{chg_pct:+.1f}%" if isinstance(chg_pct, (int, float)) else "?"

        thesis_dot = '<span class="dot g"></span>' if not alert else '<span class="dot r"></span>'
        reason_text = score_reason or why or pos.get("thesis", "")

        # Compact architect summary for scorecard
        arch = sf.get("architect", {})
        if arch:
            gates = arch.get("gates_passed", 0)
            gate_icon = "✅" if gates >= 4 else "🟡" if gates >= 3 else "⚠️" if gates >= 2 else "❌"
            cls = arch.get("classification", "")
            cls_tag = f" ⚔SPEAR" if cls == "SPEAR" else f" 🛡SHIELD" if cls == "SHIELD" else ""
            arch_summary = f"{gate_icon}{gates}/4{cls_tag}"
        else:
            arch_summary = "—"

        action_cls = "add" if "ADD" in action.upper() or "BUY" in action.upper() else "hold" if "HOLD" in action.upper() else "sell" if "EXIT" in action.upper() or "SELL" in action.upper() else "pending"

        rows += f"""        <tr{row_bg}>
          <td><span class="ticker-cell">{ticker}</span></td>
          <td><span class="{chg_color}">${current} ({chg_str})</span></td>
          <td>{thesis_dot} {reason_text[:45]}</td>
          <td>{badge}</td>
          <td><span class="action-badge {action_cls}">{action[:30]}</span></td>
          <td style="font-size:11px;color:var(--text-dim);">{arch_summary}</td>
          <td class="c-dim">{why[:60]}</td>
        </tr>
"""

    new_thead = """      <thead>
        <tr>
          <th>STOCK</th>
          <th>PRICE (TODAY)</th>
          <th>THESIS / NEWS</th>
          <th>SCORE</th>
          <th>ACTION</th>
          <th>ARCHITECT</th>
          <th>WHY CHANGED</th>
        </tr>
      </thead>"""

    pattern = r'(<section[^>]*>\s*<div class="section-header">\s*<span[^>]*>.*?03.*?<tbody>)(.*?)(</tbody>\s*</table>)'
    match = _re.search(pattern, html, _re.DOTALL)
    if match:
        before_thead = match.group(1)
        before_thead = _re.sub(r'<thead>.*?</thead>', new_thead, before_thead, flags=_re.DOTALL)
        html = html[:match.start()] + before_thead + "\n" + rows + "      " + match.group(3) + html[match.end():]
        logger.info(f"Scorecard injected: {len(seen_tickers)} stocks")
    else:
        logger.warning("Scorecard section not matched — static scores remain")

    return html


def _parse_entry_price(entry_str: str):
    """Extract a buy-entry price from strings like '$44 limit', '$205-240 post-earnings'."""
    if not entry_str:
        return None
    import re as _re
    m = _re.search(r'\$(\d+(?:\.\d+)?)', entry_str)
    return float(m.group(1)) if m else None


def _inject_live_matrix_data(html: str, data: dict) -> str:
    """Replace the static MATRIX_DATA JS array and FX_RATE with live data."""
    import re as _re

    forecasts = data.get("forecasts", {})
    stock_forecasts = forecasts.get("stocks", {})
    stock_prices = data.get("stock_prices", {})
    fx_rate = data.get("fx_rate", 1.155)

    watchlist_tickers = {w["ticker"] for w in WATCHLIST}

    all_positions = []
    for broker, positions in PORTFOLIO.items():
        for pos in positions:
            all_positions.append(pos)
    for w in WATCHLIST:
        all_positions.append(w)

    js_rows = []
    seen = set()
    for pos in all_positions:
        ticker = pos["ticker"]
        if ticker in seen:
            continue
        seen.add(ticker)

        name_js = pos.get("name", ticker).replace("'", "\\'")
        price_data = stock_prices.get(ticker, {})
        current = price_data.get("price")
        if current is None:
            continue

        sf = stock_forecasts.get(ticker, {})
        est_1w = sf.get("est_1w")
        est_1m = sf.get("est_1m")
        est_1y = sf.get("est_1y")
        est_5y = sf.get("est_5y")
        new_score = sf.get("new_score", pos.get("score", "?"))
        conv_str = f"{new_score}/10" if isinstance(new_score, (int, float)) else str(new_score)

        is_watchlist = ticker in watchlist_tickers
        buy_usd = pos.get("buy_price_usd")
        entry_note = pos.get("entry", pos.get("action", ""))
        if not buy_usd and is_watchlist:
            buy_usd = _parse_entry_price(pos.get("entry", ""))
        if buy_usd and isinstance(buy_usd, str):
            try:
                buy_usd = float(buy_usd.replace("$", "").strip())
            except ValueError:
                buy_usd = None

        buy_js = f"{buy_usd}" if isinstance(buy_usd, (int, float)) else "null"
        note_js = str(entry_note).replace("'", "\\'")[:30]
        amount = pos.get("amount", "")
        if isinstance(amount, str):
            amount_js = amount.replace("'", "\\'")
        else:
            amount_js = str(amount) if amount else "\u2014"

        m1 = est_1m if isinstance(est_1m, (int, float)) else "null"
        m6 = est_1y if isinstance(est_1y, (int, float)) else "null"  # map 1y to the 12M column
        m12 = est_1y if isinstance(est_1y, (int, float)) else "null"
        y5 = est_5y if isinstance(est_5y, (int, float)) else "null"

        js_rows.append(
            f"  {{ ticker:'{ticker}', name:'{name_js}', "
            f"current:{current}, buyUSD:{buy_js}, buyNote:'{note_js}', "
            f"amount:'{amount_js}', "
            f"m1:{m1}, m6:{m6}, m12:{m12}, y5:{y5}, "
            f"conviction:'{conv_str}' }}"
        )

    new_js = "const MATRIX_DATA = [\n" + ",\n".join(js_rows) + "\n];"
    html = _re.sub(
        r'const MATRIX_DATA = \[.*?\];',
        new_js,
        html,
        flags=_re.DOTALL,
    )

    html = _re.sub(
        r'let FX_RATE = [\d.]+;',
        f'let FX_RATE = {fx_rate:.4f};',
        html,
    )

    return html


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM SUMMARY (v2: ALERTS-FIRST)
# ══════════════════════════════════════════════════════════════════════════════

def get_olympus_telegram_summary(data: dict) -> str:
    """Format Olympus update for Telegram — alerts first, then forecasts."""
    timestamp = data.get("timestamp", "")
    composite = data.get("composite", 0)
    regime = data.get("regime", "?")
    deploy = data.get("deploy_pct", 0)
    vix = data.get("vix", 0)
    environment = data.get("environment", "")

    regime_emoji = {"CALM": "🟢", "NORMAL": "🔵", "FEAR": "🟡", "CRISIS": "🔴"}.get(regime, "⚪")

    header = (
        f"🏛 <b>OLYMPUS INTELLIGENCE UPDATE</b>\n"
        f"📅 {timestamp}\n"
        f"🌍 {environment}\n"
        f"{'━' * 28}\n\n"
        f"{regime_emoji} <b>{regime}</b> · VIX {vix:.1f}\n"
        f"📊 Composite {composite}/100 → Deploy {deploy}%\n\n"
    )

    # ALERTS FIRST
    alerts = data.get("alerts", [])
    body = ""
    if alerts:
        body += "🚨 <b>CRITICAL ALERTS</b>\n\n"
        for a in alerts:
            sev = a.get("severity", "WARNING")
            ticker = a.get("ticker", "?")
            old_s = a.get("old_score", "?")
            new_s = a.get("new_score", "?")
            event = a.get("event", "")
            action = a.get("action", "")
            impact = a.get("forecast_impact", "")

            body += (
                f"{'🔴' if sev == 'CRITICAL' else '🟡'} <b>{ticker}</b>: "
                f"{old_s}/10 → <b>{new_s}/10</b>\n"
                f"  📌 {event}\n"
                f"  ⚡ {action}\n"
                f"  📉 {impact}\n\n"
            )
    else:
        body += "✅ <b>No critical alerts today.</b>\n\n"

    # Global issues
    forecasts = data.get("forecasts", {})
    issues = forecasts.get("global_issues", [])
    if issues:
        body += "<b>🌍 GLOBAL ISSUES</b>\n"
        for issue in issues[:5]:
            body += f"  • {issue}\n"
        body += "\n"

    # Score changes
    stocks = forecasts.get("stocks", {})
    score_changes = []
    for ticker, est in stocks.items():
        old = est.get("old_score")
        new = est.get("new_score")
        if isinstance(old, (int, float)) and isinstance(new, (int, float)) and old != new:
            score_changes.append((new - old, ticker, old, new, est.get("score_reason", "")))

    if score_changes:
        score_changes.sort()
        body += "<b>📊 SCORE REVISIONS</b>\n"
        for diff, ticker, old, new, reason in score_changes:
            arrow = "▲" if diff > 0 else "▼"
            body += f"  {arrow} <b>{ticker}</b>: {old}→{new}/10 — {reason[:80]}\n"
        body += "\n"

    # TITAN ARCHITECT gate verdicts
    architect_lines = []
    for ticker, est in stocks.items():
        arch = est.get("architect")
        if not arch:
            continue
        gates = arch.get("gates_passed", 0)
        verdict = arch.get("verdict", "")
        cls = arch.get("classification", "")
        gate_icon = "✅" if gates >= 4 else "🟡" if gates >= 3 else "⚠️" if gates >= 2 else "❌"
        cls_icon = "⚔" if cls == "SPEAR" else "🛡" if cls == "SHIELD" else ""
        graham_short = arch.get("graham_number", "UNKNOWN")
        # Keep it short for Telegram
        if len(graham_short) > 45:
            graham_short = graham_short[:45] + "…"
        architect_lines.append(
            f"  {gate_icon} <b>{ticker}</b> {cls_icon} {gates}/4 gates | {graham_short}"
        )

    if architect_lines:
        body += "<b>🏛 TITAN ARCHITECT GATE</b>\n"
        for line in architect_lines:
            body += line + "\n"
        body += "\n"

    # Key forecast changes
    deltas = data.get("deltas", {})
    changes = []
    for section in ("indicators", "stocks"):
        for name, d in deltas.get(section, {}).items():
            pct = d.get("est_1m_pct", 0)
            if abs(pct) >= 2:
                direction = "▲" if pct > 0 else "▼"
                changes.append((abs(pct), f"  {direction} <b>{name}</b> 1M est {pct:+.1f}%"))

    if changes:
        changes.sort(reverse=True)
        body += "<b>📈 BIGGEST FORECAST MOVES</b>\n"
        for _, line in changes[:8]:
            body += line + "\n"
        body += "\n"

    footer = (
        f"{'━' * 28}\n"
        f"🏛 <a href=\"{TITAN_SYSTEM_URL}\">Open OLYMPUS Dashboard</a>\n"
        f"<i>The system sees what others cannot.</i>"
    )

    return header + body + footer
