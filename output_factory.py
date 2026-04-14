import os
# Load .env file if env vars not set
def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())
_load_env()
"""output_factory.py — OUTPUT LAYER"""
from dotenv import load_dotenv
load_dotenv()
import json, os, datetime, requests

BASE = os.path.dirname(os.path.abspath(__file__))

# NOTE: Telegram credentials must be provided via environment variables.
# This avoids committing secrets into the repository.
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id":CHAT_ID,"text":text,"parse_mode":"HTML"})
    return r.ok

def fmt_pct(v, decimals=1):
    if v is None: return "—"
    s = "+" if v>0 else ""
    return f"{s}{v:.{decimals}f}%"

def fmt_price(v, currency="USD"):
    if not v or v==0: return "—"
    if currency=="KRW":
        if v>=1000000: return f"₩{v/1000000:.1f}M"
        if v>=1000: return f"₩{v/1000:.0f}K"
        return f"₩{v:.0f}"
    if currency=="HKD": return f"HK${v:.2f}"
    if currency=="EUR": return f"€{v:,.0f}"
    if v>=1000: return f"${v:,.0f}"
    return f"${v:.2f}"

def build_brief(state):
    macro = state["macro"]
    liq   = state["liquidity"]
    one   = state["one_command"]
    ranto = state["ranto_posts"]
    results = state["universe_results"]

    # CATALYST VERDICTS — top 7 by score (portfolio only)
    portfolio = [(s,t) for s,t in state["scored_tickers"]
                 if results[t]["status"]=="portfolio"][:7]
    verdicts = ""
    for score, t in portfolio:
        r = results[t]
        p = fmt_price(r["price"], r.get("currency","USD"))
        pnl = fmt_pct(r["pnl_pct"])
        u1y = fmt_pct(r["gem_u1y"])
        verdicts += f"{t} \u2192 {r['action']['display']} @ {p} \u00b7 P&L {pnl} \u00b7 1y EV {u1y} \u00b7 {r['conviction']}/10\n"

    # RANTO section — rich blog analysis
    ranto_block = ""
    if ranto:
        for p in ranto[:4]:
            ranto_block += f"\u2022 {p.get('summary','')[:120]}\n"
            if p.get('theme'): ranto_block += f"  Theme: {p['theme']}\n"
            tks = ','.join(p.get('tickers',[]))
            if tks: ranto_block += f"  Impact: {tks} \u2192 {p.get('action','WATCH')}\n"
    if not ranto_block:
        try:
            bt_path = os.path.join(BASE, "data", "blog_tickers.json")
            if os.path.exists(bt_path):
                import time as _time
                age_h = (_time.time() - os.path.getmtime(bt_path)) / 3600
                with open(bt_path) as f:
                    bt = json.load(f)
                history = bt.get("history", [])
                by_sector = bt.get("by_sector", {})
                if history and age_h < 96:
                    for entry in history[-4:]:
                        post_title = entry.get("post", "")
                        added = entry.get("added", [])
                        date = entry.get("date", "")
                        url = entry.get("url", "")
                        if post_title and added:
                            ranto_block += f"\u2022 [{date}] {post_title[:100]}\n"
                            ranto_block += f"  Signal: {', '.join(added[:3])}\n"
                            if url: ranto_block += f"  \U0001F517 {url}\n"
                    if by_sector:
                        sectors = list(by_sector.keys())
                        ranto_block += f"  Sectors: {', '.join(sectors)}\n"
        except Exception:
            pass
    if not ranto_block:
        ranto_block = "\u2022 Blog data unavailable \u2014 check blog_monitor service\n"
    # MACRO → PORTFOLIO (top 3 moves)
    moves = ""
    for score, t in state["scored_tickers"][:5]:
        r = results[t]
        if r["action"]["action"] not in ["HOLD"]:
            moves += f"  {t} → {r['action']['display']} 🟢\n"

    brief = f"""🔱 MINERVA · OLYMPUS
🎯 €100M by 2031 · 47% CAGR · Beat Buffett
🏝 Thailand Islands · Gate 0: Does this move GOD toward €100M?
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {state['date']} {state['time']} Berlin
🔵 {macro['status']} · VIX {state['vix']:.2f} · Deploy {macro['deploy_pct']}%

⚡ MACRO REGIME
Liquidity: ${liq['liquidity_usd_bn']:,}B | {macro['status']} Δ+{liq['liquidity_change_7d_bn']}B
{liq.get('action','')}

⚡ SO WHAT TODAY
- ONE COMMAND: {one}
- Dry Powder: €{state['dry_powder']:,.0f} | Deploy today: €{state['max_deploy']:,.0f}

🔭 RANTO28 — KOREAN WARREN BUFFETT
{ranto_block}
🔭 MACRO → PORTFOLIO
{moves}
🚨 CATALYST VERDICTS
{verdicts}
━━━━━━━━━━━━━━━━━━━━━━━━
🔱 Open OLYMPUS Dashboard"""
    return brief.strip()

def build_dashboard_state(state):
    """Write dashboard_state.json — read by gem_injector"""
    out = {
        "date": state["date"],
        "macro": state["macro"],
        "liquidity": state["liquidity"],
        "one_command": state["one_command"],
        "positions": {}
    }
    for t, r in state["universe_results"].items():
        out["positions"][t] = {
            "price":       r["price"],
            "entry":       r["entry"],
            "currency":    r.get("currency","USD"),
            "pnl_pct":     r["pnl_pct"],
            "gem_grade":   r["gem_grade"],
            "gem_u1y":     r["gem_u1y"],
            "gem_u5y":     r["gem_u5y"],
            "god_score":   r.get("god_score",0),
            "conviction":  r.get("conviction",7),
            "ez_low":      r.get("ez_low",0),
            "ez_high":     r.get("ez_high",0),
            "soros_type":  r.get("soros_type",""),
            "action":      r["action"]["display"],
            "action_code": r["action"]["action"],
            "action_reason": r["action"].get("reason",""),
            "score":       r["score"],
            "projections": r["projections"],
            "soros_gap":   r["soros_gap"],
            "ranto_bias":  r["ranto_bias"],
            "scenarios":   r.get("scenarios",{}),
        }
    path = os.path.join(BASE, "data", "dashboard_state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return out

def generate_outputs(state):
    # Output 1: Dashboard JSON
    dashboard = build_dashboard_state(state)
    print(f"Dashboard state written: {len(dashboard['positions'])} positions")

    # Output 1b: Update directives.json with ONE COMMAND
    directives_path = os.path.join(BASE, "data", "directives.json")
    with open(directives_path) as f: d = json.load(f)
    d["one_command"] = state["one_command"]
    d["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M CET")
    with open(directives_path, "w") as f: json.dump(d, f, indent=2)

    # Output 2: Telegram brief — SO WHAT
    brief = build_brief(state)
    print(brief)
    sent = send_telegram(brief)
    print(f"Telegram: {'sent' if sent else 'FAILED'}")
