"""
claude_sync.py — OLYMPUS <-> Claude Cross-Reference Bridge
Runs every 3 hours via cron. Compiles OLYMPUS state snapshot,
sends to Anthropic API, gets structured analysis back, stores results.

Requires: ANTHROPIC_API_KEY in .env
Cron:     0 6,9,12,15,18,21 * * 1-5 cd /root/gods_plan && python3 claude_sync.py
"""

import json
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

import pytz
import requests

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
log = logging.getLogger("claude_sync")

BASE = Path(__file__).parent
DATA = BASE / "data"
RESULTS_DIR = DATA / "claude_insights"
GEM_DIR = BASE / "gem_results"
SKILL_DIR = DATA / "skill_results"
BERLIN = pytz.timezone("Europe/Berlin")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE / ".env")
    except ImportError:
        pass


def _get_api_key():
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        log.error("ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)
    return key


def _load_latest_json(directory, prefix):
    d = Path(directory)
    if not d.exists():
        return None
    files = sorted(d.glob(f"{prefix}*.json"), reverse=True)
    if not files:
        return None
    with open(files[0]) as f:
        return json.load(f)


def _load_prices():
    p = Path("/var/www/html/data/prices.json")
    if not p.exists():
        p = BASE / "prices.json"
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


def compile_state_snapshot():
    """Build a compact OLYMPUS state summary for Claude."""
    now = datetime.now(BERLIN)
    snapshot = {
        "timestamp": now.strftime("%Y-%m-%d %H:%M CET"),
        "system": "OLYMPUS MINERVA v7",
    }

    # 1. GEM results
    gem = _load_latest_json(GEM_DIR, "gem_")
    if gem:
        results = gem.get("results", [])
        snapshot["gem"] = {
            "run_date": gem.get("run_date"),
            "total": len(results),
            "grade_summary": gem.get("grade_summary", {}),
            "grade_changes": gem.get("grade_changes", []),
            "positions": []
        }
        for r in results:
            g = r.get("grading", {})
            sw = r.get("so_what", {})
            snapshot["gem"]["positions"].append({
                "ticker": r.get("ticker"),
                "grade": g.get("grade"),
                "precision": g.get("precision_grade", g.get("grade")),
                "gem_score": g.get("gem_score"),
                "upside_1y": g.get("upside_1y_pct"),
                "upside_5y": g.get("upside_5y_pct"),
                "worst_1y": g.get("worst_drop_1y_pct"),
                "action": sw.get("signal", ""),
                "cadence": sw.get("cadence", ""),
            })

    # 2. Live prices + significant moves
    prices_data = _load_prices()
    prices = prices_data.get("prices", {})
    if prices:
        movers = []
        for tk, d in prices.items():
            chg = d.get("change_pct", 0)
            if abs(chg) >= 2:
                movers.append({"ticker": tk, "price": d["price"],
                               "change_pct": chg, "currency": d.get("currency", "USD")})
        movers.sort(key=lambda x: x["change_pct"])
        snapshot["prices"] = {
            "updated": prices_data.get("updated"),
            "significant_moves": movers,
            "top_losers": movers[:5],
            "top_gainers": list(reversed(movers[-5:])),
        }

    # 3. Risk screener
    risk = _load_latest_json(SKILL_DIR, "risk_")
    if risk:
        risk_results = risk.get("results", {})
        critical = []
        for tk, r in risk_results.items():
            if r.get("risk_level") in ("CRITICAL", "HIGH"):
                critical.append({
                    "ticker": tk,
                    "level": r["risk_level"],
                    "avg_risk": r.get("avg_risk"),
                    "critical_dims": r.get("critical_risks", []),
                })
        snapshot["risk_alerts"] = critical

    # 4. Fundamentals
    fund = _load_latest_json(SKILL_DIR, "fundamentals_")
    if fund:
        fund_summary = {}
        for tk, r in fund.get("results", {}).items():
            trends = r.get("trends", {})
            declining = [k for k, v in trends.items() if v == "declining"]
            if declining:
                fund_summary[tk] = {"declining_metrics": declining}
        if fund_summary:
            snapshot["fundamental_concerns"] = fund_summary

    # 5. News sentiment
    sent = _load_latest_json(SKILL_DIR, "sentiment_")
    if sent:
        snapshot["sentiment"] = {
            "sector_sentiment": sent.get("sector_sentiment", {}),
        }

    # 6. Dashboard state
    dash_file = DATA / "dashboard_state.json"
    if dash_file.exists():
        with open(dash_file) as f:
            dash = json.load(f)
        if "macro" in dash:
            snapshot["macro"] = dash["macro"]

    return snapshot


def build_prompt(snapshot):
    """Construct the message for Claude."""
    state_json = json.dumps(snapshot, indent=2, ensure_ascii=False)

    system = """You are the OLYMPUS MINERVA intelligence co-analyst. You receive a system state 
snapshot every 3 hours and provide structured cross-reference analysis.

Your job:
1. VALIDATE: Check if GEM grades/projections make sense given current prices and risks
2. FLAG: Identify any contradictions (e.g., high risk score but high grade, or declining fundamentals with bullish sentiment)
3. PRIORITIZE: What needs immediate attention vs. what can wait
4. ADVISE: Concrete actions for the next 3-hour window

You know the OLYMPUS system intimately:
- GEM v4: Heston MC (1M/6M) + fundamental (1Y/3Y/5Y), 40W/40N/20B weighting, 9-tier S→F grading
- Risk screener: 9 dimensions, 0-9 per dimension
- Precision tiers: I/II/III within each grade using 35% 1Y + 65% 5Y EV composite
- Monitoring cadence: S/A = monthly, B = quarterly, C/D = weekly, F = daily
- Portfolio is EUR-based (Trade Republic), all P&L tracked in EUR

Output JSON with these exact keys:
{
  "market_read": "1-2 sentence macro assessment",
  "contradictions": [{"ticker": "X", "issue": "...", "severity": "high/medium/low"}],
  "immediate_actions": [{"ticker": "X", "action": "...", "reason": "..."}],
  "thesis_reviews": [{"ticker": "X", "status": "intact/wounded/dead", "note": "..."}],
  "grade_challenges": [{"ticker": "X", "current_grade": "X", "suggested": "X", "reason": "..."}],
  "watchlist_signals": [{"ticker": "X", "signal": "buy/wait/remove", "reason": "..."}],
  "next_focus": "What to monitor in the next 3 hours"
}"""

    user_msg = f"""OLYMPUS STATE SNAPSHOT — {snapshot.get('timestamp', 'now')}

{state_json}

Analyze this snapshot. Return ONLY valid JSON, no markdown."""

    return system, user_msg


def call_claude(system, user_msg, api_key):
    """Call Anthropic API and return parsed response."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }

    log.info("Calling Claude API (%s)...", MODEL)
    resp = requests.post(ANTHROPIC_URL, headers=headers, json=body, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block["text"]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Claude returned non-JSON, saving raw text")
        return {"raw_response": text}


def save_insight(insight, snapshot_ts):
    """Save Claude's analysis to data/claude_insights/."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(BERLIN)
    fname = f"insight_{now.strftime('%Y%m%d_%H%M')}.json"
    out = {
        "generated": now.strftime("%Y-%m-%d %H:%M CET"),
        "snapshot_time": snapshot_ts,
        "model": MODEL,
        "analysis": insight,
    }
    path = RESULTS_DIR / fname
    with open(path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log.info("Saved insight: %s", path)

    latest = RESULTS_DIR / "insight_latest.json"
    with open(latest, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    web_dir = Path("/var/www/html/data/claude_insights")
    if web_dir.parent.exists():
        web_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(latest, web_dir / "insight_latest.json")

    return path


def send_telegram_summary(insight):
    """Send key findings to Telegram."""
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE / ".env")
    except ImportError:
        pass

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return

    lines = ["\U0001F9E0 CLAUDE CROSS-REF"]
    mr = insight.get("market_read", "")
    if mr:
        lines.append(f"\n{mr}")

    actions = insight.get("immediate_actions", [])
    if actions:
        lines.append("\nACTIONS:")
        for a in actions[:5]:
            lines.append(f"  {a.get('ticker','')} — {a.get('action','')}")

    contras = insight.get("contradictions", [])
    if contras:
        lines.append("\nFLAGS:")
        for c in contras[:5]:
            sev = c.get("severity", "")
            lines.append(f"  [{sev.upper()}] {c.get('ticker','')} — {c.get('issue','')}")

    nf = insight.get("next_focus", "")
    if nf:
        lines.append(f"\nFOCUS: {nf}")

    msg = "\n".join(lines)

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat, "text": msg, "parse_mode": "HTML"},
                      timeout=10)
        log.info("Telegram summary sent")
    except Exception as e:
        log.warning("Telegram send failed: %s", e)


def main():
    _load_env()
    api_key = _get_api_key()

    log.info("Compiling OLYMPUS state snapshot...")
    snapshot = compile_state_snapshot()
    log.info("Snapshot: %d keys, GEM=%s positions",
             len(snapshot), len(snapshot.get("gem", {}).get("positions", [])))

    system, user_msg = build_prompt(snapshot)
    insight = call_claude(system, user_msg, api_key)

    ts = snapshot.get("timestamp", "")
    path = save_insight(insight, ts)
    log.info("Insight saved: %s", path)

    if not insight.get("raw_response"):
        send_telegram_summary(insight)

    contras = insight.get("contradictions", [])
    actions = insight.get("immediate_actions", [])
    log.info("Done. %d contradictions, %d actions flagged.",
             len(contras), len(actions))

    print(json.dumps(insight, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
