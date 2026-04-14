"""output_factory.py — OUTPUT LAYER"""
import os

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

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import json, datetime, requests

BASE = os.path.dirname(os.path.abspath(__file__))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    return r.ok


def fmt_pct(v, decimals=1):
    if v is None:
        return "\u2014"
    s = "+" if v > 0 else ""
    return f"{s}{v:.{decimals}f}%"


def fmt_price(v, currency="USD"):
    if not v or v == 0:
        return "\u2014"
    if currency == "KRW":
        if v >= 1000000:
            return f"\u20a9{v/1000000:.1f}M"
        if v >= 1000:
            return f"\u20a9{v/1000:.0f}K"
        return f"\u20a9{v:.0f}"
    if currency == "HKD":
        return f"HK${v:.2f}"
    if currency == "EUR":
        return f"\u20ac{v:,.0f}"
    if v >= 1000:
        return f"${v:,.0f}"
    return f"${v:.2f}"


def build_brief(state):
    macro = state["macro"]
    liq = state["liquidity"]
    one = state["one_command"]
    ranto = state["ranto_posts"]
    results = state["universe_results"]

    portfolio = [(s, t) for s, t in state["scored_tickers"]
                 if results[t]["status"] == "portfolio"][:7]
    verdicts = ""
    for score, t in portfolio:
        r = results[t]
        p = fmt_price(r["price"], r.get("currency", "USD"))
        pnl = fmt_pct(r["pnl_pct"])
        u1y = fmt_pct(r["gem_u1y"])
        verdicts += f"{t} \u2192 {r['action']['display']} @ {p} \u00b7 P&L {pnl} \u00b7 1y EV {u1y} \u00b7 {r['conviction']}/10\n"

    # RANTO28 section — only 48h-filtered posts (filtering done in fetch_data)
    ranto_block = ""
    if ranto:
        for p in ranto[:4]:
            date_str = p.get("date", "")
            title = p.get("title", p.get("summary", ""))[:120]
            ranto_block += f"\u2022 [{date_str}] {title}\n"
            tks = p.get("affected_tickers", [])
            if tks:
                ranto_block += f"  Signal: {', '.join(str(x) for x in tks[:3])}\n"
            url = p.get("url", "")
            if url:
                ranto_block += f"  \U0001F517 {url}\n"
            sectors = p.get("sectors", [])
            if sectors:
                ranto_block += f"  Sectors: {', '.join(str(x) for x in sectors)}\n"
    if not ranto_block:
        ranto_block = "\u2022 No new signals last 48h\n"

    moves = ""
    for score, t in state["scored_tickers"][:5]:
        r = results[t]
        if r["action"]["action"] not in ["HOLD"]:
            moves += f"  {t} \u2192 {r['action']['display']} \U0001F7E2\n"

    brief = f"""\U0001F531 MINERVA \u00b7 OLYMPUS
\U0001F3AF \u20ac100M by 2031 \u00b7 47% CAGR \u00b7 Beat Buffett
\U0001F3DD Thailand Islands \u00b7 Gate 0: Does this move GOD toward \u20ac100M?
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\U0001F4C5 {state['date']} {state['time']} Berlin
\U0001F535 {macro['status']} \u00b7 VIX {state['vix']:.2f} \u00b7 Deploy {macro['deploy_pct']}%

\u26A1 MACRO REGIME
Liquidity: ${liq['liquidity_usd_bn']:,}B | {macro['status']} \u0394+{liq['liquidity_change_7d_bn']}B
{liq.get('action','')}

\u26A1 SO WHAT TODAY
- ONE COMMAND: {one}
- Dry Powder: \u20ac{state['dry_powder']:,.0f} | Deploy today: \u20ac{state['max_deploy']:,.0f}

\U0001F52D RANTO28 \u2014 KOREAN WARREN BUFFETT
{ranto_block}
\U0001F52D MACRO \u2192 PORTFOLIO
{moves}
\U0001F6A8 CATALYST VERDICTS
{verdicts}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\U0001F531 Open OLYMPUS Dashboard"""
    return brief.strip()


def build_dashboard_state(state):
    out = {
        "date": state["date"],
        "macro": state["macro"],
        "liquidity": state["liquidity"],
        "one_command": state["one_command"],
        "positions": {}
    }
    for t, r in state["universe_results"].items():
        out["positions"][t] = {
            "price":         r["price"],
            "entry":         r["entry"],
            "currency":      r.get("currency", "USD"),
            "pnl_pct":       r["pnl_pct"],
            "gem_grade":     r["gem_grade"],
            "gem_u1y":       r["gem_u1y"],
            "gem_u5y":       r["gem_u5y"],
            "god_score":     r.get("god_score", 0),
            "conviction":    r.get("conviction", 7),
            "ez_low":        r.get("ez_low", 0),
            "ez_high":       r.get("ez_high", 0),
            "soros_type":    r.get("soros_type", ""),
            "action":        r["action"]["display"],
            "action_code":   r["action"]["action"],
            "action_reason": r["action"].get("reason", ""),
            "score":         r["score"],
            "projections":   r["projections"],
            "soros_gap":     r["soros_gap"],
            "ranto_bias":    r["ranto_bias"],
            "scenarios":     r.get("scenarios", {}),
        }
    path = os.path.join(BASE, "data", "dashboard_state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return out


def generate_outputs(state):
    dashboard = build_dashboard_state(state)
    print(f"Dashboard state written: {len(dashboard['positions'])} positions")

    directives_path = os.path.join(BASE, "data", "directives.json")
    try:
        with open(directives_path) as f:
            d = json.load(f)
        d["one_command"] = state["one_command"]
        d["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M CET")
        with open(directives_path, "w") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass

    brief = build_brief(state)
    print(brief)
    sent = send_telegram(brief)
    print(f"Telegram: {'sent' if sent else 'FAILED'}")
