"""
MINERVA-10X Morning Brief Engine v2
Replaces the broken battle_rhythm.py morning brief
Fetches LIVE prices via yfinance, runs MINERVA-10X logic, sends to Telegram
"""

PORTFOLIO = [
    {"ticker": "PLTR",      "entry": 109.32, "currency": "USD", "stop": 95,   "soros_gap": 59, "soros_type": "narrative", "ez_low": 95,  "ez_high": 109, "sector": "Intelligence", "god": 72,  "thesis": "intact", "macro": "tailwind", "conviction": 9},
    {"ticker": "TSM",       "entry": 287.40, "currency": "USD", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 0,   "ez_high": 0,   "sector": "Intelligence", "god": 90,  "thesis": "intact", "macro": "tailwind", "conviction": 9},
    {"ticker": "000660.KS", "entry": 85000,  "currency": "KRW", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 0,   "ez_high": 0,   "sector": "Intelligence", "god": 95,  "thesis": "intact", "macro": "tailwind", "conviction": 10},
    {"ticker": "1810.HK",   "entry": 3.88,   "currency": "HKD", "stop": 0,    "soros_gap": 41, "soros_type": "narrative", "ez_low": 0,   "ez_high": 0,   "sector": "Intelligence", "god": 68,  "thesis": "intact", "macro": "tailwind", "conviction": 7},
    {"ticker": "UEC",       "entry": 12.19,  "currency": "USD", "stop": 0,    "soros_gap": 38, "soros_type": "narrative", "ez_low": 10,  "ez_high": 12,  "sector": "Energy",       "god": 78,  "thesis": "intact", "macro": "tailwind", "conviction": 8},
    {"ticker": "URNM",      "entry": 14.65,  "currency": "USD", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 0,   "ez_high": 0,   "sector": "Energy",       "god": 74,  "thesis": "intact", "macro": "tailwind", "conviction": 7},
    {"ticker": "RKLB",      "entry": 59.67,  "currency": "USD", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 0,   "ez_high": 0,   "sector": "Space",        "god": 58,  "thesis": "intact", "macro": "tailwind", "conviction": 6},
    {"ticker": "PL",        "entry": 26.88,  "currency": "USD", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 0,   "ez_high": 0,   "sector": "Space",        "god": 84,  "thesis": "intact", "macro": "neutral",  "conviction": 7},
    {"ticker": "TMO",       "entry": 438.66, "currency": "USD", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 0,   "ez_high": 0,   "sector": "Bio",          "god": 68,  "thesis": "intact", "macro": "neutral",  "conviction": 6},
    {"ticker": "KTOS",      "entry": 80.00,  "currency": "USD", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 65,  "ez_high": 80,  "sector": "Robotics",     "god": 80,  "thesis": "intact", "macro": "tailwind", "conviction": 8, "sector_fear": True, "sector_fear_pct": 11.2},
    {"ticker": "COHR",      "entry": 214.21, "currency": "USD", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 0,   "ez_high": 0,   "sector": "Infra",        "god": 76,  "thesis": "intact", "macro": "tailwind", "conviction": 6},
    {"ticker": "VRT",       "entry": 65.00,  "currency": "USD", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 0,   "ez_high": 0,   "sector": "Infra",        "god": 84,  "thesis": "intact", "macro": "tailwind", "conviction": 8},
    {"ticker": "NTR",       "entry": 65.94,  "currency": "USD", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 0,   "ez_high": 0,   "sector": "Global",       "god": 72,  "thesis": "intact", "macro": "neutral",  "conviction": 6},
    {"ticker": "272210.KS", "entry": 45000,  "currency": "KRW", "stop": 0,    "soros_gap": 0,  "soros_type": "",          "ez_low": 0,   "ez_high": 0,   "sector": "Robotics",     "god": 92,  "thesis": "intact", "macro": "tailwind", "conviction": 9},
]

WATCHLIST = [
    {"ticker": "OKLO",  "limit": 44,   "note": "ARMED $44"},
    {"ticker": "CCJ",   "limit": 100,  "note": "ARMED $100"},
    {"ticker": "ASML",  "limit": 1080, "note": "ARMED €1080 · Apr 16 earnings"},
]

DRY_POWDER_EUR = 1500.0

def fetch_prices(tickers):
    """Fetch live prices via yfinance. Returns {ticker: price}."""
    prices = {}
    try:
        import yfinance as yf
        all_tickers = list(set(tickers))
        data = yf.download(all_tickers, period="2d", interval="1d", 
                          auto_adjust=True, progress=False)
        if hasattr(data, 'columns') and hasattr(data.columns, 'levels'):
            close = data['Close']
            for t in all_tickers:
                try:
                    val = float(close[t].dropna().iloc[-1])
                    prices[t] = round(val, 2)
                except:
                    pass
        else:
            for t in all_tickers:
                try:
                    stock = yf.Ticker(t)
                    hist = stock.history(period="2d")
                    if not hist.empty:
                        prices[t] = round(float(hist['Close'].iloc[-1]), 2)
                except:
                    pass
    except ImportError:
        print("yfinance not available — using fallback prices")
    except Exception as e:
        print(f"Price fetch error: {e}")
    return prices

def compute_action(pos, price, liq_status, vix_regime):
    """Compute action per MINERVA-10X logic."""
    ticker = pos["ticker"]
    entry  = pos["entry"]
    stop   = pos.get("stop", 0)
    ez_low = pos.get("ez_low", 0)
    ez_high= pos.get("ez_high", 0)
    soros_gap  = pos.get("soros_gap", 0)
    soros_type = pos.get("soros_type", "")
    thesis = pos.get("thesis", "intact")
    macro  = pos.get("macro", "neutral")
    sector_fear = pos.get("sector_fear", False)
    sf_pct = pos.get("sector_fear_pct", 0)

    if not price or price <= 0:
        return "HOLD", "no live price"

    # Thesis dead
    if thesis == "dead":
        return "EXIT", "thesis dead"

    # Stop breach — thesis check
    if stop > 0 and price < stop:
        if thesis == "intact":
            return "ARMED_ONE_SHOT", f"below stop ${stop} — thesis intact → ONE SHOT"
        return "EXIT_REVIEW", f"below stop ${stop} — thesis wounded"

    # Sector fear with price in/below zone
    if sector_fear and thesis == "intact" and ez_high > 0 and price <= ez_high:
        return "ADD", f"sector fear dip — better than ${ez_high:.0f} planned"

    # Soros narrative gap
    if soros_type == "narrative" and soros_gap >= 20:
        if ez_high > 0 and ez_low > 0:
            if ez_low <= price <= ez_high:
                return "ADD", f"in entry zone ${ez_low:.0f}–${ez_high:.0f}"
            elif price > ez_high:
                return "DIP_WATCH", f"above zone — entry ${ez_low:.0f}–${ez_high:.0f}"

    # GEM grade + liquidity
    if liq_status == "EXPANSION" and vix_regime in ["CALM","NORMAL"]:
        if ez_high > 0 and price <= ez_high:
            return "ADD", "liquidity expanding + price in zone"

    return "HOLD", "thesis intact"

def build_brief(liq_b=2368, liq_delta=189, vix=19.12, ranto_posts=None):
    import datetime, os, json

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.datetime.now().strftime("%H:%M")

    # Classify regime
    if liq_delta > 25:   liq_status = "EXPANSION"
    elif liq_delta < -25: liq_status = "CONTRACTION"
    else:                 liq_status = "STABLE"

    if vix < 15:    vix_regime = "CALM"
    elif vix <= 25: vix_regime = "NORMAL"
    else:           vix_regime = "FEAR"

    deploy_pct = 30 if (liq_status=="EXPANSION" and vix_regime in ["CALM","NORMAL"]) else 20 if (liq_status=="STABLE" and vix_regime=="NORMAL") else 10
    max_deploy = min(deploy_pct/100 * (DRY_POWDER_EUR + 9000), DRY_POWDER_EUR)

    # Fetch LIVE prices
    all_tickers = [p["ticker"] for p in PORTFOLIO]
    print(f"Fetching live prices for {len(all_tickers)} positions...")
    prices = fetch_prices(all_tickers)
    print(f"Got prices: {prices}")

    # Compute actions with LIVE prices
    candidates = []
    for pos in PORTFOLIO:
        t = pos["ticker"]
        price = prices.get(t, 0)
        action, reason = compute_action(pos, price, liq_status, vix_regime)
        pnl = ((price - pos["entry"]) / pos["entry"] * 100) if price > 0 else 0
        candidates.append({
            "ticker": t, "sector": pos["sector"],
            "price": price, "entry": pos["entry"],
            "pnl": round(pnl, 1),
            "action": action, "reason": reason,
            "conviction": pos.get("conviction", 7),
            "god": pos.get("god", 70),
            "soros_gap": pos.get("soros_gap", 0)
        })

    # Sort by priority: ONE_SHOT > ADD > DIP_WATCH > HOLD
    priority = {"ARMED_ONE_SHOT": 5, "EXIT": 4, "EXIT_REVIEW": 3, "ADD": 2, "DIP_WATCH": 1, "HOLD": 0}
    candidates.sort(key=lambda x: priority.get(x["action"], 0), reverse=True)

    # Select ONE COMMAND
    one_cmd = candidates[0] if candidates else None
    secondary = [c for c in candidates[1:] if priority.get(c["action"],0) >= 1][:2]

    # Ranto28 section
    ranto_text = ""
    if ranto_posts:
        for post in ranto_posts[:4]:
            ranto_text += f"• {post.get('title','')[:60]} → {post.get('signal','NONE')}\n"
    else:
        ranto_text = "• No new posts in last 48h\n"

    # Format CATALYST VERDICTS — top 7 by priority
    verdicts = ""
    for c in candidates[:7]:
        p_str = f"${c['price']:.2f}" if c['price'] > 0 else "N/A"
        pnl_str = f"{c['pnl']:+.1f}%" if c['price'] > 0 else "—"
        action_display = {
            "ARMED_ONE_SHOT": "⚡ ONE SHOT",
            "ADD": "ADD",
            "DIP_WATCH": "DIP WATCH",
            "EXIT": "EXIT NOW",
            "EXIT_REVIEW": "EXIT REVIEW",
            "HOLD": "HOLD"
        }.get(c["action"], c["action"])
        verdicts += f"{c['ticker']} → {action_display} @ {p_str} · P&L {pnl_str} · {c['conviction']}/10\n"

    # ONE COMMAND formatting
    if one_cmd and priority.get(one_cmd["action"], 0) >= 1:
        p_str = f"${one_cmd['price']:.2f}" if one_cmd["price"] > 0 else "at market"
        cmd_line = f"• ONE COMMAND: {one_cmd['action']} {one_cmd['ticker']} @ {p_str} — {one_cmd['reason']}"
    else:
        cmd_line = "• ONE COMMAND: NO TRADE — HOLD & OBSERVE"

    sec_lines = ""
    for s in secondary:
        p_str = f"${s['price']:.2f}" if s['price'] > 0 else "at market"
        sec_lines += f"• Secondary: {s['action']} {s['ticker']} @ {p_str} · {s['reason']}\n"

    dry_after = DRY_POWDER_EUR - (max_deploy if one_cmd and one_cmd["action"] in ["ADD","ARMED_ONE_SHOT"] else 0)

    brief = f"""🔱 MINERVA · OLYMPUS
🎯 €100M by 2031 · 47% CAGR · Beat Buffett
🏝 Thailand Islands
━━━━━━━━━━━━━━━━━━━━━━
📅 {date_str} 07:00 Berlin
🔵 {liq_status} · VIX {vix:.2f} · Deploy {deploy_pct}%

⚡ MACRO REGIME
Liquidity: ${liq_b:,}B | {liq_status} Δ+{liq_delta}B | Post-tax TGA drain
Key Drivers:
• April 15 TGA drain → liquidity expanding → DEPLOY signal active
• ASML earnings Apr 16 → beat=buy market, miss=wait €1,080

⚡ SO WHAT TODAY
{cmd_line}
{sec_lines}• Dry Powder: €{dry_after:,.0f} | Deploy today: €{max_deploy:,.0f}

🔭 RANTO28
{ranto_text}
🚨 CATALYST VERDICTS
{verdicts}
━━━━━━━━━━━━━━━━━━━━━━
🔱 Open OLYMPUS Dashboard"""

    return brief.strip()


if __name__ == "__main__":
    brief = build_brief(liq_b=2368, liq_delta=189, vix=19.12)
    print(brief)
