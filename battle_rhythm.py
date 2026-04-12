"""
🔱 OLYMPUS — Battle Rhythm Briefing Engine v4
ONE message. Concrete verdicts. Logical order.

Order: Mission → Overnight → Korea → Key Moves → Forecast → Catalysts → Blog → Strategy
Every stock mention ends with: BUY/HOLD/SELL @ price · size · reason

Schedule (Berlin, Mon-Fri):
  07:00  master_daily
  15:30  us_open
  22:30  us_close
Saturday 08:00  olympus_weekly
"""
import logging
import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests
from openai import OpenAI
import config
from market_data import (
    fetch_stock_prices,
    fetch_market_snapshot,
    calculate_titan_k_index,
    get_vix_regime,
    fetch_fx_rate,
)


def fetch_fred_liquidity() -> dict:
    """Fetch TGA/RRP/Reserves from FRED. Auto-updates directives.json liquidity section."""
    fred_key = os.getenv("FRED_API_KEY", "0bc0ed228f83cb0853a6fa1f35b970d3")
    series = {"reserves": "WRESBAL", "tga": "WTREGEN", "rrp": "RRPONTSYD"}
    out: dict = {}
    for k, sid in series.items():
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": sid,
                    "api_key": fred_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 2,
                },
                timeout=10,
            )
            obs = r.json().get("observations") or []
            if len(obs) < 2:
                continue
            v0, v1 = obs[0].get("value"), obs[1].get("value")

            def _fv(x):
                if x is None or x == ".":
                    return None
                try:
                    return float(x)
                except (TypeError, ValueError):
                    return None

            fv0, fv1 = _fv(v0), _fv(v1)
            if fv0 is not None:
                out[k] = fv0
            if fv1 is not None:
                out[f"{k}_prev"] = fv1
        except Exception:
            out[k] = None

    if all(out.get(k) is not None for k in ("reserves", "tga", "rrp")):
        # FRED WRESBAL / WTREGEN / RRP: observations in millions USD → billions for §11 UI
        _m = 1000.0
        res_b = out["reserves"] / _m
        tga_b = out["tga"] / _m
        rrp_b = out["rrp"] / _m
        prev_res_b = (out.get("reserves_prev") or 0) / _m
        prev_tga_b = (out.get("tga_prev") or 0) / _m
        prev_rrp_b = (out.get("rrp_prev") or 0) / _m
        net = res_b - tga_b - rrp_b
        prev = prev_res_b - prev_tga_b - prev_rrp_b
        out["net_liq"] = round(net, 1)
        change = round(net - prev, 1)
        out["change"] = change
        out["direction"] = "EXPANDING ↑" if net > prev else "CONTRACTING ↓"
        out["net_liq_text"] = (
            f"Net Liq ${net:.0f}B · Res ${res_b:.0f}B − TGA ${tga_b:.0f}B − RRP ${rrp_b:.0f}B"
        )
        if net < 2000:
            zone = "🔴 DANGER — Crisis threshold ($2T floor)"
        elif net < 2500:
            zone = "🟠 WARNING — Approaching stress ($2-2.5T)"
        elif net < 3500:
            zone = "🟡 NORMAL — Ample reserves ($2.5-3.5T)"
        else:
            zone = "🟢 ABUNDANCE — Maximum liquidity ($3.5T+)"
        if net < 2200:
            hist_parallel = "2023 SVB banking crisis level"
        elif net < 2500:
            hist_parallel = "Mid-2023 post-debt-ceiling drain"
        elif net < 3000:
            hist_parallel = "2024 average — stable bull market"
        elif net < 4000:
            hist_parallel = "2025 peak — strong conditions"
        else:
            hist_parallel = "2020-2021 COVID liquidity peak"
        last_updated = datetime.now().strftime("%Y-%m-%d %H:%M") + " CET"
        change_text = f"Δ${change:+.0f}B"
        dp = os.path.join(os.path.dirname(__file__), "data", "directives.json")
        try:
            with open(dp, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        d["liquidity"] = {
            "net_liq_text": (
                f"Net Liq ${net:.0f}B · Res ${res_b:.0f}B − TGA ${tga_b:.0f}B − RRP ${rrp_b:.0f}B"
            ),
            "outlook_text": f"{out['direction']} · Δ${out['change']:+.0f}B vs prev week",
            "action_text": (
                "DEPLOY dry powder — liquidity expanding, risk-on confirmed"
                if net > prev
                else "HOLD dry powder — liquidity contracting, wait for expansion"
            ),
            "net_liq_value": round(net, 1),
            "change_text": change_text,
            "zone": zone,
            "hist_parallel": hist_parallel,
            "last_updated": last_updated,
        }
        try:
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            with open(dp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("fetch_fred_liquidity: could not write directives.json: %s", e)
    return out


def _directives_json_path() -> str:
    return os.path.join(os.path.dirname(__file__), "data", "directives.json")


PORTFOLIO_SCORES = [
    ("000660.KS", 95, "Intelligence"),
    ("TSM", 90, "Intelligence"),
    ("PLTR", 72, "Intelligence"),
    ("1810.HK", 68, "Intelligence"),
    ("UEC", 78, "Energy"),
    ("URNM", 74, "Energy"),
    ("CWEN", 55, "Energy"),
    ("UUUU", 72, "Energy"),
    ("PL", 84, "Space"),
    ("RKLB", 58, "Space"),
    ("TMO", 68, "Bio"),
    ("272210.KS", 92, "Robotics"),
    ("KTOS", 80, "Robotics"),
    ("ARKQ", 62, "Robotics"),
    ("BOTZ", 60, "Robotics"),
    ("VRT", 84, "Infrastructure"),
    ("COHR", 76, "Infrastructure"),
    ("NTR", 72, "Global Issue"),
    ("FCX", 45, "Global Issue"),
]


def build_god_score_context(ticker: str, score: float, sector: str) -> dict:
    """
    GOD Score is meaningless alone.
    Must show: score vs sector average, vs top peer, vs own history.
    Returns context dict for dashboard and Telegram.
    """
    SECTOR_PEERS = {
        "Intelligence": {"avg": 81, "top": ("NVDA", 96), "bottom": ("1810.HK", 68)},
        "Energy": {"avg": 74, "top": ("CCJ", 82), "bottom": ("CWEN", 55)},
        "Space": {"avg": 70, "top": ("PL", 84), "bottom": ("RKLB", 58)},
        "Bio": {"avg": 60, "top": ("BEAM", 70), "bottom": ("CRSP", 48)},
        "Robotics": {"avg": 75, "top": ("272210.KS", 92), "bottom": ("BOTZ", 60)},
        "Infrastructure": {"avg": 81, "top": ("ASML", 87), "bottom": ("CWEN", 55)},
        "Global Issue": {"avg": 58, "top": ("NTR", 72), "bottom": ("FCX", 45)},
    }
    peers = SECTOR_PEERS.get(
        sector, {"avg": 70, "top": ("—", 0), "bottom": ("—", 0)}
    )
    sector_avg = peers["avg"]
    top_name, top_score = peers["top"]
    diff_from_avg = score - sector_avg
    diff_from_top = score - top_score

    if score >= 90:
        verdict = "ELITE — top conviction, full size position justified"
    elif score >= 80:
        verdict = "HIGH — strong conviction, core position"
    elif score >= 70:
        verdict = "SOLID — hold, monitor for upgrade catalysts"
    elif score >= 55:
        verdict = "WEAK — thesis needs verification before adding"
    else:
        verdict = "EXIT CANDIDATE — thesis likely broken"

    return {
        "score": score,
        "sector_avg": sector_avg,
        "diff_from_avg": f"{diff_from_avg:+.0f} vs sector avg ({sector_avg})",
        "diff_from_top": f"{diff_from_top:+.0f} vs sector best {top_name} ({top_score})",
        "verdict": verdict,
        "sector": sector,
    }


def classify_soros_gap(
    ticker: str,
    gap_pct: float,
    cause: str,
    thesis_intact: bool,
    drop_from_high: float,
) -> dict:
    """
    Soros Gap is meaningless without cause classification.
    Cause types: NARRATIVE (buy signal) vs FUNDAMENTAL (exit signal)
    """
    HISTORICAL_PARALLELS = {
        "PLTR": {
            "cause": "Michael Burry deleted bearish post — pure narrative",
            "reality": "US Army $10B contract intact · NATO expansion ongoing",
            "parallel": "NVDA -30% in 2022 on AI capex fear → +600% recovery",
            "cause_type": "NARRATIVE",
        },
        "1810.HK": {
            "cause": "US-China tariff escalation fear — macro narrative",
            "reality": "EV + AI smartphone sales growing · China domestic demand intact",
            "parallel": "BABA 2021-2022 regulatory fear → recovered 60% in 6 months",
            "cause_type": "NARRATIVE",
        },
        "UEC": {
            "cause": "Uranium spot price tape weakness — sector rotation",
            "reality": "Nuclear structural demand 2025-2035 unchanged · US Energy Dominance policy",
            "parallel": "CCJ 2020 COVID drop -50% → +400% in 24 months",
            "cause_type": "NARRATIVE",
        },
        "FCX": {
            "cause": "Iran ceasefire optimism + copper production accident",
            "reality": "EV demand doubles copper need by 2040 · AI data centers = copper intensive",
            "parallel": "FCX 2020 COVID -50% → +200% in 18 months on same thesis",
            "cause_type": "NARRATIVE",
        },
        "OKLO": {
            "cause": "SMR technology skepticism + regulatory timeline uncertainty",
            "reality": "Meta 1.2GW contract SIGNED · Sam Altman chairman · NRC license 2026",
            "parallel": "TSLA 2019 production doubt → 10x in 24 months",
            "cause_type": "NARRATIVE",
        },
        "NVDA": {
            "cause": "AI capex slowdown fear + tariff uncertainty",
            "reality": "GPU monopoly intact · $500B Stargate committed · no viable competitor",
            "parallel": "NVDA 2022 -65% on crypto/AI fear → +800% by 2024",
            "cause_type": "NARRATIVE",
        },
        "KTOS": {
            "cause": "Defense sector rotation + AVAV contract cancellation fear bleed",
            "reality": "Kratos drones in active deployment · DoD contract Q2 intact · different thesis",
            "parallel": "LMT 2013 sequestration fear -20% → +300% over 5 years",
            "cause_type": "NARRATIVE",
        },
    }

    info = HISTORICAL_PARALLELS.get(
        ticker,
        {
            "cause": cause or "Unknown — research required",
            "reality": "Verify thesis before acting",
            "parallel": "No parallel identified",
            "cause_type": "UNKNOWN",
        },
    )

    cause_type = info["cause_type"]

    if cause_type == "NARRATIVE" and thesis_intact:
        action = "MAXIMUM CONVICTION ENTRY — narrative gap, thesis intact"
        urgency = "HIGH"
    elif cause_type == "FUNDAMENTAL":
        action = "THESIS REVIEW REQUIRED — may be company death not narrative"
        urgency = "CRITICAL"
    else:
        action = "MONITOR — classify cause before acting"
        urgency = "MEDIUM"

    return {
        "ticker": ticker,
        "gap_pct": gap_pct,
        "cause": info["cause"],
        "reality": info["reality"],
        "historical_parallel": info["parallel"],
        "cause_type": cause_type,
        "thesis_intact": thesis_intact,
        "action": action,
        "urgency": urgency,
    }


PORTFOLIO_SOROS_SIGNALS = [
    ("PLTR", 59.0, "", True, 0),
    ("1810.HK", 41.0, "", True, 0),
    ("UEC", 38.0, "", True, 0),
    ("FCX", 32.0, "", True, 0),
    ("OKLO", 60.0, "", True, 0),
    ("NVDA", 45.0, "", True, 0),
    ("KTOS", 13.74, "", True, 0),
]


def classify_price_drop(
    ticker: str,
    drop_pct: float,
    sector_drop_pct: float,
    sec_8k_filed: bool,
    thesis_events: list,
) -> dict:
    """
    Every price drop must be decomposed:
    Company-specific drop = total drop - sector drop
    If company-specific < 3% → SECTOR FEAR not COMPANY DEATH
    """
    company_specific = drop_pct - sector_drop_pct

    if abs(company_specific) < 3.0:
        classification = "SECTOR FEAR"
        action = "HOLD or ADD — company not the issue"
        color = "🟡"
    elif company_specific < -5.0 and sec_8k_filed:
        classification = "COMPANY EVENT — SEC filing detected"
        action = "THESIS REVIEW REQUIRED — check 8-K immediately"
        color = "🔴"
    elif company_specific < -5.0 and thesis_events:
        classification = "COMPANY EVENT — thesis event detected"
        action = f"REVIEW: {'; '.join(thesis_events[:2])}"
        color = "🔴"
    elif company_specific < -3.0:
        classification = "PARTIAL COMPANY ISSUE"
        action = "MONITOR — no SEC filing but company-specific selling"
        color = "🟠"
    else:
        classification = "SECTOR FEAR"
        action = "HOLD — sector rotation not company problem"
        color = "🟡"

    return {
        "ticker": ticker,
        "total_drop": f"{drop_pct:+.2f}%",
        "sector_drop": f"{sector_drop_pct:+.2f}%",
        "company_specific": f"{company_specific:+.2f}%",
        "classification": f"{color} {classification}",
        "sec_8k_filed": sec_8k_filed,
        "action": action,
    }


TICKER_SECTOR_BENCH: Dict[str, List[str]] = {
    "000660.KS": ["QQQ"],
    "TSM": ["QQQ"],
    "PLTR": ["QQQ"],
    "1810.HK": ["QQQ"],
    "NVDA": ["QQQ"],
    "UEC": ["XLE", "URA"],
    "URNM": ["XLE", "URA"],
    "CWEN": ["XLE"],
    "UUUU": ["XLE", "URA"],
    "CCJ": ["XLE", "URA"],
    "OKLO": ["XLE", "URA"],
    "PL": ["ARKX"],
    "RKLB": ["ARKX"],
    "ASTS": ["ARKX"],
    "TMO": ["XBI"],
    "272210.KS": ["BOTZ"],
    "KTOS": ["BOTZ"],
    "ARKQ": ["BOTZ"],
    "BOTZ": ["BOTZ"],
    "VRT": ["IGV"],
    "COHR": ["IGV"],
    "NTR": ["DJP"],
    "FCX": ["DJP"],
    "IAU": ["DJP"],
    "MC.PA": ["QQQ"],
}


def sector_drop_for_ticker(ticker: str, sector_bench: Dict) -> float:
    """Average same-day % change of sector ETF proxies (from directives sector_bench)."""
    syms = TICKER_SECTOR_BENCH.get(ticker, ["QQQ"])
    vals = []
    for s in syms:
        v = sector_bench.get(s)
        if isinstance(v, (int, float)):
            vals.append(float(v))
    return sum(vals) / len(vals) if vals else 0.0


def merge_master_intel_to_directives() -> None:
    """Write god_scores, soros_classified, sector_bench into directives.json (preserve other keys)."""
    from market_data import fetch_stock_prices

    dp = _directives_json_path()
    try:
        with open(dp, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}

    bench_syms = ["QQQ", "XLE", "URA", "ARKX", "XBI", "BOTZ", "IGV", "DJP"]
    br = fetch_stock_prices(bench_syms)
    sector_bench = {
        k: round(float(br.get(k, {}).get("change_pct", 0)), 2) for k in bench_syms
    }

    god_scores = {
        tk: build_god_score_context(tk, float(sc), sec)
        for tk, sc, sec in PORTFOLIO_SCORES
    }
    soros_classified = {
        tk: classify_soros_gap(tk, float(gap), "", intact, float(dh))
        for tk, gap, _, intact, dh in PORTFOLIO_SOROS_SIGNALS
    }

    d["god_scores"] = god_scores
    d["soros_classified"] = soros_classified
    d["sector_bench"] = sector_bench
    try:
        os.makedirs(os.path.dirname(dp), exist_ok=True)
        with open(dp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("merge_master_intel_to_directives: %s", e)


def _format_soros_classified_for_prompt(soros: Dict) -> str:
    lines = []
    for tk, row in soros.items():
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {tk}: gap {row.get('gap_pct')}% · {row.get('cause_type')} · "
            f"{row.get('action', '')[:80]}"
        )
    return "\n".join(lines) if lines else "None"


DECISION_MATRIX_SYSTEM_PROMPT = """You are Minerva, GOD's investment intelligence engine.
GOD's mission: €100M by 2031. 47% CAGR required. Island in Thailand.
Every word you write must earn its place. No filler. No generic phrases.
Format output EXACTLY as shown. No deviations."""


def fetch_portfolio_news() -> List[dict]:
    """Fetch last ~20H news for GOD's holdings via NewsAPI."""
    news_key = os.getenv("NEWS_API_KEY", "b579e246dfca4a4095c1f4a64f0d5572")
    keywords = [
        "Palantir",
        "TSMC",
        "uranium",
        "Rocket Lab",
        "Oklo",
        "ASML",
        "Coherent",
        "Xiaomi",
        "Hanwha",
    ]
    query = " OR ".join(f'"{k}"' for k in keywords[:5])
    try:
        now = datetime.now(timezone.utc)
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "apiKey": news_key,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 5,
                "from": (now - timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%S"),
            },
            timeout=10,
        )
        data = r.json()
        return [
            {"title": a["title"], "source": a["source"]["name"]}
            for a in data.get("articles", [])[:3]
            if a.get("title") and "[Removed]" not in a.get("title", "")
        ]
    except Exception as e:
        logger.debug("fetch_portfolio_news: %s", e)
        return []


STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

def _load_state() -> dict:
    """Load persistent OLYMPUS state. Returns empty dict if missing."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"State file not loaded: {e}")
        return {}

def _format_state_context(state: dict) -> str:
    """Format state.json into a compact context block for GPT."""
    if not state:
        return ""

    lines = ["\n[OLYMPUS STATE — binding context]"]

    # Liquidity
    liq = state.get("liquidity_state", {})
    if liq:
        lines.append(f"§11 Net Liquidity: ${liq.get('net_liq_B','?')}B · Signal: {liq.get('signal','?')} · Min GOD Score: {liq.get('min_god_score','?')}")
        lines.append(f"FSI: {liq.get('fsi','?')} · Funding sub: {liq.get('funding_sub','?')} · Safe Assets sub: {liq.get('safe_assets_sub','?')}")

    # Dry powder
    dp = state.get("dry_powder", {})
    if dp:
        lines.append(f"Dry powder: TR €{dp.get('TR_EUR',0)} · Kiwoom ${dp.get('Kiwoom_USD',0)}")

    # Active limits
    limits = state.get("active_limits", [])
    if limits:
        lines.append("Active limits (DO NOT recommend these — already in progress):")
        for l in limits:
            lines.append(f"  {l['ticker']} @ {l.get('limit_EUR','?')} EUR — {l.get('status','?')} — {l.get('reason','')}")

    # Active stops
    stops = state.get("active_stops", [])
    if stops:
        lines.append("Active stops:")
        for s in stops:
            lines.append(f"  {s['ticker']} stop ${s.get('stop_USD','?')} — {s.get('note','')}")

    # Exit flags
    exits = state.get("exit_flags", [])
    if exits:
        lines.append("Exit flags (these are BROKEN theses — never recommend as buys):")
        for e in exits:
            lines.append(f"  {e['ticker']} → {e.get('status','?')} — {e.get('reason','')}")

    # Upcoming calendar
    import datetime
    today = datetime.date.today().isoformat()
    cal = [c for c in state.get("calendar", []) if c.get("date","") >= today][:4]
    if cal:
        lines.append("Next calendar events:")
        for c in cal:
            lines.append(f"  {c['date']} · {c['event']} [{c.get('priority','?')}] → {c.get('action','')}")

    # GOD scores (top 5 held)
    scores = state.get("god_scores", [])
    if scores:
        lines.append("GOD Scores (current):")
        for s in scores[:8]:
            lines.append(f"  {s['ticker']} {s['score']}/100 → {s['signal']}")

    # Macro
    macro = state.get("macro_context", {})
    iran = macro.get("iran_war", {})
    if iran:
        lines.append(f"Macro: Iran war {iran.get('status','?')} · VIX {macro.get('vix','?')} · {macro.get('regime','?')}")

    lines.append("[END STATE]\n")
    return "\n".join(lines)

logger = logging.getLogger("titan_k.battle_rhythm")
client = OpenAI(api_key=config.OPENAI_API_KEY)

FAST_MODEL = "gpt-4o-mini"
DEEP_MODEL = "gpt-4o-mini"

NEWS_CACHE_PATH = os.path.join("data", "news_cache.json")

GOD_MISSION = (
    "🔱 <b>MINERVA · OLYMPUS</b>\n"
    "🎯 €100,000,000 by 2031 · 47% CAGR · Beat Buffett\n"
    "🏝 Thailand Islands · Gate 0: does this move GOD toward €100M?\n"
)

SYSTEM_PERSONA = '''You are Minerva, GOD's investment intelligence engine for OLYMPUS — targeting €100M by 2031.

GOD's TR holdings: TSM, PLTR (avg €109), UEC (limit €11 armed), URNM, COHR, Xiaomi (1810.HK), NTR, RKLB, PL, TMO, LVMH (locked)
GOD's Kiwoom: 000660.KS, 272210.KS, ARKQ, BOTZ, VRT, FCX (hold), IAU
Dry powder: €1,500 | Active limits: OKLO $44, CCJ $100, UEC €11 | Stop: PLTR €95

STRICT RULES:
1. NEVER use generic phrases like geopolitical tensions remain high or markets showed mixed signals
2. ALWAYS name specific tickers from GOD's holdings with specific prices and reasons
3. CRITICAL ALERTS: only fire if NEW information — never repeat same alert within 48 hours
4. If quiet overnight: say QUIET SESSION — all positions hold, no action needed
5. Soros check: if any holding dropped more than 8% on narrative not fundamentals — flag REFLEXIVITY SIGNAL with entry zone
6. End Decision Engine with: ⚔ ONE COMMAND: [single most important action today]'''


# ══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def _berlin_now():
    import pytz
    return datetime.now(pytz.timezone(config.TIMEZONE))

def _is_weekday():
    return _berlin_now().weekday() < 5

def _gpt(system: str, user: str, tokens: int = 600) -> str:
    try:
        resp = client.chat.completions.create(
            model=FAST_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.3,
            max_tokens=tokens,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT failed: {e}")
        return "⚠️ Analysis unavailable."

def _send_telegram(message: str):
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.error("Telegram credentials missing")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # Split if over 4096 chars
    chunks = []
    if len(message) <= 4096:
        chunks = [message]
    else:
        lines = message.split("\n")
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 4096:
                chunks.append(current)
                current = line
            else:
                current = (current + "\n" + line).strip()
        if current:
            chunks.append(current)
    for chunk in chunks:
        try:
            requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=15)
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCHERS
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_live_context() -> Dict:
    all_tickers = set()
    for positions in config.PORTFOLIO.values():
        for pos in positions:
            all_tickers.add(pos["ticker"])
    for w in config.WATCHLIST:
        all_tickers.add(w["ticker"])

    prices = fetch_stock_prices(list(all_tickers))
    fx_rate = fetch_fx_rate()
    snapshot = fetch_market_snapshot()
    composite = calculate_titan_k_index(snapshot, config.WEIGHTS)
    vix_val = snapshot.get("VIX", {}).get("value", 25)
    regime, deploy_pct, label = get_vix_regime(vix_val) if isinstance(vix_val, (int, float)) else ("UNKNOWN", 0, "?")

    portfolio_lines = []
    for broker, positions in config.PORTFOLIO.items():
        for pos in positions:
            p = prices.get(pos["ticker"], {})
            portfolio_lines.append(
                f"{pos['ticker']} ${p.get('price','?')} ({p.get('change_pct',0):+.1f}%) "
                f"Score:{pos.get('score','?')}/10 Signal:{pos.get('signal','?')} "
                f"Action:{pos.get('action','HOLD')} Stop:{pos.get('stop','—')}"
            )

    watchlist_lines = []
    for w in config.WATCHLIST:
        p = prices.get(w["ticker"], {})
        watchlist_lines.append(
            f"{w['ticker']} ${p.get('price','?')} Score:{w.get('score','?')}/10 "
            f"Signal:{w.get('signal','?')} Entry:{w.get('entry','—')}"
        )

    key_indicators = ["VIX","SPX","NDX","SOX","Gold","Oil","DXY","US10Y","BTC","Copper","Uranium"]
    key_moves = []
    for ind in key_indicators:
        d = snapshot.get(ind, {})
        if isinstance(d.get("value"), (int, float)):
            chg = d.get("change_pct", 0)
            arrow = "▲" if chg >= 0 else "▼"
            bold = abs(chg) >= 2
            line = f"  {'<b>' if bold else ''}{arrow} {ind} {d['value']} ({chg:+.1f}%){'</b>' if bold else ''}"
            key_moves.append(line)

    today = _berlin_now().strftime("%Y-%m-%d")
    earnings_today = [e for e in config.EARNINGS_CALENDAR if e.get("date") == today]

    return {
        "prices": prices, "fx_rate": fx_rate, "vix": vix_val,
        "regime": regime, "deploy_pct": deploy_pct, "composite": composite,
        "portfolio_text": "\n".join(portfolio_lines),
        "watchlist_text": "\n".join(watchlist_lines),
        "key_moves": "\n".join(key_moves),
        "earnings_today": earnings_today,
        "snapshot": snapshot,
    }

def _fetch_portfolio_news() -> Dict[str, list]:
    import yfinance as yf
    all_tickers = set()
    for positions in config.PORTFOLIO.values():
        for pos in positions:
            all_tickers.add(pos["ticker"])
    news_by_ticker = {}
    for ticker in all_tickers:
        if ticker in ("xAI", "FigureAI"):
            continue
        try:
            t = yf.Ticker(ticker)
            items = t.news or []
            headlines = []
            for item in items[:4]:
                content = item.get("content", {})
                title = content.get("title", item.get("title", ""))
                if title:
                    headlines.append(title)
            if headlines:
                news_by_ticker[ticker] = headlines
        except Exception as e:
            logger.debug(f"News fetch {ticker}: {e}")
    return news_by_ticker

def _fetch_blog() -> str:
    """Fetch ranto28 blog — try RSS first, then direct scrape."""
    import xml.etree.ElementTree as ET
    import re

    rss_url = config.NAVER_RSS_URL
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }

    posts = []

    # Try RSS
    try:
        resp = requests.get(rss_url, headers=headers, timeout=15)
        if resp.status_code == 200 and "<rss" in resp.text:
            root = ET.fromstring(resp.content)
            channel = root.find("channel")
            items = channel.findall("item") if channel else []
            for item in items[:3]:
                title = item.findtext("title", "").strip()
                desc = item.findtext("description", "").strip()
                pub = item.findtext("pubDate", "").strip()
                link = item.findtext("link", "").strip()
                # Strip HTML tags from description
                desc_clean = re.sub(r"<[^>]+>", " ", desc).strip()[:300]
                if title:
                    url = link or config.NAVER_BLOG_URL
                    posts.append(
                        f"📌 <b>{title}</b>\n"
                        f"{desc_clean}\n"
                        f"URL: {url}\n"
                        f"({pub[:16]})"
                    )
            logger.info(f"Blog RSS: {len(posts)} posts")
    except Exception as e:
        logger.warning(f"Blog RSS failed: {e}")

    # Fallback: scrape blog page
    if not posts:
        try:
            resp = requests.get(config.NAVER_BLOG_URL, headers=headers, timeout=15)
            if resp.status_code == 200:
                titles = re.findall(r'<span[^>]*logMainTitle[^>]*>([^<]+)</span>', resp.text)
                if not titles:
                    titles = re.findall(r'"title"\s*:\s*"([^"]{10,})"', resp.text)
                for t in titles[:3]:
                    posts.append(f"📌 <b>{t.strip()}</b>\nURL: {config.NAVER_BLOG_URL}")
                logger.info(f"Blog scrape: {len(posts)} titles")
        except Exception as e:
            logger.warning(f"Blog scrape failed: {e}")

    if not posts:
        return "📭 ranto28: No posts retrieved. Check manually."

    return "\n\n".join(posts)

# ══════════════════════════════════════════════════════════════════════════════
# NEWS PULSE (background — fires silently, sends only if actionable)
# ══════════════════════════════════════════════════════════════════════════════

_last_seen_headlines: Dict[str, set] = {}

def run_news_pulse():
    import pytz
    berlin = pytz.timezone(config.TIMEZONE)
    now = datetime.now(berlin)
    if now.weekday() >= 5:
        return
    hour = now.hour + now.minute / 60.0
    start_h = float(getattr(config, "NEWS_PULSE_START_HOUR", 7.0))
    end_h = float(getattr(config, "NEWS_PULSE_END_HOUR", 23.5))
    if hour < start_h or hour > end_h:
        return

    try:
        fresh_news = _fetch_portfolio_news()
    except Exception as e:
        logger.error(f"News pulse fetch failed: {e}")
        return

    new_items = []
    for ticker, headlines in fresh_news.items():
        if ticker not in _last_seen_headlines:
            _last_seen_headlines[ticker] = set()
        new_h = [h for h in headlines if h not in _last_seen_headlines[ticker]]
        if new_h:
            _last_seen_headlines[ticker].update(new_h)
            for h in new_h[:2]:
                new_items.append(f"{ticker}: {h[:120]}")

    # ── SEC Form 4 Insider Monitor (free, high-signal, Scale-Aware) ──────────
    try:
        from insider_monitor import scan_insider_filings, format_insider_telegram
        insider_signals = scan_insider_filings()
        if insider_signals:
            insider_msg = format_insider_telegram(insider_signals)
            if insider_msg:
                _send_telegram(insider_msg)
                logger.info(f"Insider signals sent: {len(insider_signals)} buys")
    except Exception as e:
        logger.debug(f"Insider monitor skipped: {e}")

    if not new_items:
        return

    verdict = _gpt(
        SYSTEM_PERSONA + """
New headlines require immediate verdict. Five-Phase compressed:
P1: Does macro context change anything? (one word: YES/NO)
P2-3: Skip unless Black Swan visible in headlines
P4: TICKER → ACTION @ $price · reason (max 8 words) · conviction X/10
P5: exit if [condition] — only if recommending BUY
If nothing clears Gate 0: reply exactly SKIP""",
        f"New headlines:\n" + "\n".join(new_items[:15]) +
        f"\n\nPortfolio:\n{chr(10).join(new_items[:5])}"
    )

    if not verdict or verdict.strip() == "SKIP":
        return

    msg = (
        f"⚡ <b>PULSE {now.strftime('%H:%M')}</b>\n"
        f"{'━'*22}\n"
        f"{verdict}"
    )
    _send_telegram(msg)
    logger.info(f"News pulse sent: {len(new_items)} headlines")


# ══════════════════════════════════════════════════════════════════════════════
# MASTER DAILY — 07:00 — ONE MESSAGE, LOGICAL ORDER
# ══════════════════════════════════════════════════════════════════════════════

def generate_master_daily() -> str:
    liq = fetch_fred_liquidity()
    if liq.get("net_liq") is not None:
        liq_context = (
            f"LIQUIDITY: {liq.get('net_liq_text', 'FRED unavailable')} · {liq.get('direction', '')}"
        )
    else:
        liq_context = "LIQUIDITY: FRED unavailable"

    news = fetch_portfolio_news()
    news_context = (
        "\n".join(f"- {n['title']} ({n['source']})" for n in news)
        if news
        else "No recent news"
    )

    ctx = _fetch_live_context()
    merge_master_intel_to_directives()
    try:
        with open(_directives_json_path(), encoding="utf-8") as f:
            _dj = json.load(f)
        _lz = (_dj.get("liquidity") or {}).get("zone")
        _hp = (_dj.get("liquidity") or {}).get("hist_parallel")
        if _lz:
            liq_context = f"{liq_context} | {_lz} | hist: {_hp or '—'}"
    except Exception:
        pass

    state = _load_state()
    state_context = _format_state_context(state)
    now = _berlin_now()
    weekday = now.strftime("%A")
    is_monday = weekday == "Monday"

    # ── Blog ──────────────────────────────────────────────────────────────────
    blog_raw = _fetch_blog()
    blog_gpt = _gpt(
        SYSTEM_PERSONA
        + f"\n{liq_context}\nNEWS (24h):\n{news_context}\n"
        + """
IMPORTANT: Always respond in ENGLISH.
You are Minerva, investment analyst for GOD's OLYMPUS system targeting €100M by 2031.
Analyze this Korean financial blog post and return exactly this format:

• What it says: [2-3 sentences — full context]
• Macro theme: [energy / geopolitics / liquidity / tech / defense / commodities]
• Portfolio impact: [connect to GOD's holdings even if no ticker named — TSM, PLTR, UEC, URNM, KTOS, RKLB, PL, TMO, COHR, 000660.KS, 272210.KS, 1810.HK, VRT, NTR, ASML, IAU]
• ⚡ FOCUS NOW: [one specific action or watch point for GOD — e.g. "Watch UEC — uranium supply chain affected by Hormuz reopening" or "No action — macro noise only"]
• Signal: [BUY / WATCH / AVOID / HOLD — one sentence reason]
• 🔗 [shortened title](url)

Rules:
- There may be multiple posts in the input. Treat each post independently.
- Output one block per post, separated by a blank line.
- URL is provided in the input as \"URL: ...\"; use it for the 🔗 line.
- The ⚡ FOCUS NOW line is the most important: it must always be concrete, never empty, and must connect to a current holding, a watchlist stock, or a sector GOD monitors.""",
        f"{state_context}Blog posts:\n{blog_raw}\n\nPortfolio:\n{ctx['portfolio_text'][:600]}"
    )

    # ── Stock news with verdicts ───────────────────────────────────────────────
    portfolio_news = {}
    catalyst_verdicts = ""
    try:
        portfolio_news = _fetch_portfolio_news()
        if portfolio_news:
            news_block = ""
            for ticker, headlines in portfolio_news.items():
                p = ctx["prices"].get(ticker, {})
                chg = p.get("change_pct", 0)
                price = p.get("price", "?")
                news_block += f"\n{ticker} {chg:+.1f}% @ ${price}:\n"
                for h in headlines[:2]:
                    news_block += f"  - {h[:100]}\n"

            # Build binding state constraints for this call
            exit_tickers = [e["ticker"] for e in state.get("exit_flags", [])]
            hold_tickers = [s["ticker"] for s in state.get("god_scores", [])
                           if s.get("signal") in ("HOLD","CORE","NEVER_SELL","HOLD_NO_ADD")]
            # Hard filter: any SELL below conviction 8 on a HOLD ticker is suppressed in post-processing
            catalyst_verdicts = _gpt(
                SYSTEM_PERSONA
                + f"\n{liq_context}\nNEWS (24h):\n{news_context}\n"
                + f"""
\nHARD STATE CONSTRAINTS — violations are not permitted:
1. These tickers are on EXIT flags — never recommend BUY: {", ".join(exit_tickers)}
2. These tickers have standing HOLD status in state.json — you may NOT output SELL
   unless conviction is 9 or 10 AND you provide a specific thesis-break reason:
   {", ".join(hold_tickers)}
3. Conviction below 7 = output HOLD, not SELL. No exceptions.
4. If you cannot find a specific thesis-break event (earnings miss, contract loss,
   management change) — output HOLD regardless of price action.
5. Net Liquidity §11-PREDICT: ${state.get("liquidity_state", {}).get("net_liq_B", "?")}B
   Dry powder available: TR €{state.get("dry_powder", {}).get("TR_EUR", 0)}
   These are different numbers. Net Liq is the Fed liquidity reading. Dry powder is GOD's cash.
{state_context}
For each stock give ONE line verdict.
Format: TICKER → BUY/HOLD/SELL @ $price · reason (max 10 words) · conviction X/10
Only include stocks with moves >1.5% OR material news. Skip unchanged stocks.
End with: ⚡ TOP ACTION: [single highest-conviction action today]""",
                f"Live data:\n{news_block}\n\nPortfolio:\n{ctx['portfolio_text'][:800]}"
            )
    except Exception as e:
        logger.error(f"News scan failed: {e}")

    # ── Macro correlations ─────────────────────────────────────────────────────
    MACRO_PAIRS = {
        "SOX":     [("000660.KS","+"), ("COHR","+")],
        "Uranium": [("UEC","+"), ("URNM","+")],
        "Oil":     [("UEC","+"), ("URNM","+")],
        "DXY":     [("PLTR","-"), ("UEC","-")],
        "BTC":     [("RKLB","+"), ("PLTR","+")],
    }
    macro_lines = []
    for ind, pairs in MACRO_PAIRS.items():
        d = ctx["snapshot"].get(ind, {})
        chg = d.get("change_pct", 0)
        if not isinstance(chg, (int, float)) or abs(chg) < 1.5:
            continue
        for ticker, corr in pairs:
            impact = "Tailwind 🟢" if (chg > 0) == (corr == "+") else "Headwind 🔴"
            macro_lines.append(f"  {ind} {chg:+.1f}% → <b>{ticker}</b> {impact}")

    # ── Main GPT — decision matrix morning brief ─────────────────────────────
    monday_add = (
        "\n📅 WEEK AHEAD: include 2 dated events + GOD action in PORTFOLIO SIGNALS if Monday.\n"
        if is_monday
        else ""
    )
    soros_ctx_str = _format_soros_classified_for_prompt(
        {
            tk: classify_soros_gap(tk, g, "", intact, dh)
            for tk, g, _, intact, dh in PORTFOLIO_SOROS_SIGNALS
        }
    )
    today_str = f"{now.strftime('%Y-%m-%d %H:%M')} Berlin"
    portfolio_prices_context = ctx["portfolio_text"]
    vix_level = ctx["vix"]
    vix_regime = ctx["regime"]

    user_matrix = f"""{monday_add}
LIQUIDITY: {liq_context}
VIX: {vix_level} ({vix_regime})
DATE: {today_str} Berlin

PORTFOLIO POSITIONS:
{portfolio_prices_context}

SOROS SIGNALS:
{soros_ctx_str}

NEWS (24H):
{news_context}

BLOG SIGNALS:
{blog_gpt}

Write the morning brief in EXACTLY this format:

⚡ LIQUIDITY: [one line — number, zone, historical parallel]
📊 VIX: [number · regime · what it means for deployment]

PORTFOLIO SIGNALS:
[For each position with a signal write:]
[✅/⚠️/🔱/❌] TICKER: [price change] — [one sentence: sector vs company, action]

NEWS THAT MATTERS:
[Only include news that changes an action. Max 3 items.]
- TICKER: [headline] → [action change if any]

ONE COMMAND:
[Single most important action GOD must take TODAY. Be specific. Include price and size.]

Do not write anything outside this format.

Context (binding, do not contradict):
{state_context}
MACRO moves:
{ctx['key_moves']}
EUR/USD: {ctx['fx_rate']} | Composite: {ctx['composite']}/100
WATCHLIST TOP:
{ctx['watchlist_text'][:600]}
EARNINGS TODAY: {', '.join(e['ticker'] for e in ctx['earnings_today']) or 'None'}
WEEKDAY: {weekday}
"""

    analysis = _gpt(DECISION_MATRIX_SYSTEM_PROMPT, user_matrix, tokens=900)

    # ── Assemble ONE message ───────────────────────────────────────────────────
    regime_emoji = {"CALM":"🟢","NORMAL":"🔵","FEAR":"🟡","CRISIS":"🔴"}.get(ctx["regime"],"⚪")
    sep = "━" * 26

    msg = (
        f"{GOD_MISSION}"
        f"{sep}\n"
        f"📅 {now.strftime('%Y-%m-%d %H:%M')} Berlin\n"
        f"{regime_emoji} {ctx['regime']} · VIX {ctx['vix']} · Deploy {ctx['deploy_pct']}%\n"
        f"{sep}\n\n"
    )

    # Macro correlations (only if meaningful moves)
    if macro_lines:
        msg += "<b>🔭 MACRO → PORTFOLIO</b>\n" + "\n".join(macro_lines) + "\n\n"

    # Catalyst verdicts with conclusions
    if catalyst_verdicts:
        msg += f"<b>🚨 CATALYST VERDICTS</b>\n{catalyst_verdicts}\n\n"

    # Blog
    msg += f"<b>📰 RANTO28</b>\n{blog_gpt}\n\n"

    # Main analysis (overnight + Korea + strategy + one command)
    msg += analysis

    # Key moves (compact)
    msg += f"\n\n<b>📊 KEY MOVES</b>\n{ctx['key_moves']}"

    # Footer
    dashboard_url = getattr(config, "TITAN_SYSTEM_URL",
        "https://sobluenight10-commits.github.io/gods_plan/OLYMPUS_UNIFIED.html")
    msg += f"\n\n{sep}\n🔱 <a href=\"{dashboard_url}\">Open OLYMPUS Dashboard</a>"

    return msg


# ══════════════════════════════════════════════════════════════════════════════
# US OPEN — 15:30
# ══════════════════════════════════════════════════════════════════════════════

def generate_us_open() -> str:
    ctx = _fetch_live_context()
    now = _berlin_now()

    portfolio_news = {}
    catalyst_verdicts = ""
    try:
        portfolio_news = _fetch_portfolio_news()
        if portfolio_news:
            news_block = "\n".join(
                f"{t} {ctx['prices'].get(t,{}).get('change_pct',0):+.1f}%: {hs[0][:80]}"
                for t, hs in portfolio_news.items() if hs
            )
            catalyst_verdicts = _gpt(
                SYSTEM_PERSONA + "\nPre-market. US opens in 30 min. ONE line per stock. "
                "Format: TICKER → BUY/HOLD/SELL @ $price · reason. Skip unchanged stocks. "
                "End with: ⚡ OPEN ACTION: [single most important thing at open]",
                f"Pre-market news:\n{news_block}\n\nPortfolio:\n{ctx['portfolio_text'][:800]}"
            )
    except Exception as e:
        logger.error(f"Open news scan failed: {e}")

    analysis = _gpt(
        SYSTEM_PERSONA + """
Structure:
🎯 LIMITS CHECK
• [every active limit order — armed/triggered/cancel?]

⚡ FIRST 30 MIN WATCH
• [2-3 stocks to watch at open + price levels + what triggers action]

📋 OPEN STRATEGY
• [what to do at open — specific tickers, prices, sizes]
• [do NOT buy in first 15min unless stop triggered]""",
        f"Portfolio:\n{ctx['portfolio_text']}\nMacro:\n{ctx['key_moves']}\nEUR/USD: {ctx['fx_rate']}"
    )

    sep = "━" * 26
    regime_emoji = {"CALM":"🟢","NORMAL":"🔵","FEAR":"🟡","CRISIS":"🔴"}.get(ctx["regime"],"⚪")
    msg = (
        f"🔱 <b>US OPEN · {now.strftime('%H:%M')}</b>\n"
        f"{regime_emoji} {ctx['regime']} · VIX {ctx['vix']}\n"
        f"{sep}\n\n"
    )
    if catalyst_verdicts:
        msg += f"<b>⚡ PRE-MARKET VERDICTS</b>\n{catalyst_verdicts}\n\n"
    msg += analysis
    msg += f"\n\n<b>📊 MOVES</b>\n{ctx['key_moves']}"
    dashboard_url = getattr(config, "TITAN_SYSTEM_URL",
        "https://sobluenight10-commits.github.io/gods_plan/OLYMPUS_UNIFIED.html")
    msg += f"\n\n{sep}\n🔱 <a href=\"{dashboard_url}\">Open OLYMPUS</a>"
    return msg


# ══════════════════════════════════════════════════════════════════════════════
# US CLOSE — 22:30
# ══════════════════════════════════════════════════════════════════════════════

def generate_us_close() -> str:
    ctx = _fetch_live_context()
    now = _berlin_now()

    analysis = _gpt(
        SYSTEM_PERSONA + """
Structure:
🏁 CLOSE SUMMARY
• [SPX/NDX/SOX final + what it means for tomorrow]
• [VIX close → regime change?]

💼 PORTFOLIO TODAY
• [winners and losers — TICKER chg% · still HOLD or action needed?]
• [any stops triggered? any limits filled?]

🌅 TOMORROW PREP
• [1-2 specific setups to prepare tonight]
• [earnings or macro events — which ones matter for GOD's positions]

🎯 ONE COMMAND (what to do before markets open tomorrow)""",
        f"Portfolio:\n{ctx['portfolio_text']}\nMacro:\n{ctx['key_moves']}\nEUR/USD: {ctx['fx_rate']}\n"
        f"Earnings today: {', '.join(e['ticker'] for e in ctx['earnings_today']) or 'None'}"
    )

    sep = "━" * 26
    regime_emoji = {"CALM":"🟢","NORMAL":"🔵","FEAR":"🟡","CRISIS":"🔴"}.get(ctx["regime"],"⚪")
    msg = (
        f"🔱 <b>US CLOSE · {now.strftime('%H:%M')}</b>\n"
        f"{regime_emoji} {ctx['regime']} · VIX {ctx['vix']}\n"
        f"{sep}\n\n"
        f"{analysis}\n\n"
        f"<b>📊 FINAL</b>\n{ctx['key_moves']}"
    )
    dashboard_url = getattr(config, "TITAN_SYSTEM_URL",
        "https://sobluenight10-commits.github.io/gods_plan/OLYMPUS_UNIFIED.html")
    msg += f"\n\n{sep}\n🔱 <a href=\"{dashboard_url}\">Open OLYMPUS</a>"
    return msg


# ══════════════════════════════════════════════════════════════════════════════
# SOROS REFLEXIVITY ALERT
# Fires when a THESIS_ALERT_TICKER drops >10% in a session.
# Classifies the drop as NARRATIVE or FUNDAMENTAL via GPT, then:
#   NARRATIVE + thesis intact + divergence >7% → entry signal
#   FUNDAMENTAL → thesis review warning
# ══════════════════════════════════════════════════════════════════════════════

_REFLEXIVITY_CACHE: dict = {}  # ticker → date string, prevents duplicate fires per day

def analyze_reflexivity(ticker: str, chg: float, price: float) -> None:
    """
    Called by price_alert when a ticker drops >10% intraday.
    chg is negative (e.g. -12.5). price is current price in USD.
    """
    from datetime import date
    today = date.today().isoformat()

    # One analysis per ticker per day
    if _REFLEXIVITY_CACHE.get(ticker) == today:
        logger.debug(f"Reflexivity: {ticker} already analysed today, skipping")
        return
    _REFLEXIVITY_CACHE[ticker] = today

    logger.info(f"Reflexivity analysis triggered: {ticker} {chg:+.1f}%")

    # ── Fetch headlines via yfinance ──────────────────────────────────────────
    headlines = []
    try:
        import yfinance as yf
        items = yf.Ticker(ticker).news or []
        for item in items[:5]:
            content = item.get("content", {})
            title = content.get("title", item.get("title", ""))
            if title:
                headlines.append(title)
    except Exception as e:
        logger.warning(f"Reflexivity news fetch {ticker}: {e}")

    headlines_text = "\n".join(f"- {h}" for h in headlines) if headlines else "No headlines available."

    # ── GPT classification ────────────────────────────────────────────────────
    prompt = (
        f"A stock in our portfolio ({ticker}) dropped {abs(chg):.1f}% today. "
        f"Here are the news headlines:\n{headlines_text}\n\n"
        "Classify this drop as: NARRATIVE (caused by opinion, tweet, analyst view, macro fear) "
        "or FUNDAMENTAL (caused by contract loss, earnings miss, fraud, regulatory block).\n"
        "Then state in one sentence why the company thesis is or is not intact.\n"
        'Output JSON only: {"classification": "NARRATIVE" or "FUNDAMENTAL", '
        '"thesis_intact": true or false, "reason": "one sentence"}'
    )

    raw = _gpt("You are a precise investment analyst. Output only valid JSON.", prompt, tokens=200)

    # ── Parse JSON ────────────────────────────────────────────────────────────
    try:
        # Strip markdown fences if present
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(clean)
    except Exception as e:
        logger.error(f"Reflexivity JSON parse failed for {ticker}: {e} | raw: {raw[:200]}")
        _send_telegram(f"⚠️ REFLEXIVITY — {ticker} | GPT parse failed | Drop: {chg:+.1f}% | Check manually.")
        return

    classification  = result.get("classification", "").upper()
    thesis_intact   = result.get("thesis_intact", False)
    reason          = result.get("reason", "No reason provided.")

    sep = "━" * 17

    if classification == "NARRATIVE" and thesis_intact:
        divergence = round(abs(chg) - 3.0, 1)   # subtract rational noise floor
        if divergence > 7.0:
            entry_high = round(price * 0.97, 2)
            entry_low  = round(price * 0.92, 2)
            limit      = round(price * 0.93, 2)
            msg = (
                f"🔱 <b>REFLEXIVITY SIGNAL — {ticker}</b>\n"
                f"{sep}\n"
                f"TRIGGER: Narrative drop — not fundamental\n"
                f"DROP: {chg:+.1f}% | THESIS: ✅ INTACT\n"
                f"DIVERGENCE: {divergence}% above rational\n"
                f"{sep}\n"
                f"💰 <b>SOROS ENTRY ZONE:</b> ${entry_low} — ${entry_high}\n"
                f"⚔ <b>SET LIMIT:</b> ${limit}\n"
                f"⏰ WINDOW: Act within 4 hours\n"
                f"REASON NARRATIVE IS WRONG: {reason}\n"
                f"{sep}\n"
                f"This is how GOD beats Buffett. 🏝️"
            )
            _send_telegram(msg)
            logger.info(f"Reflexivity ENTRY SIGNAL sent: {ticker} divergence={divergence}%")
        else:
            logger.info(f"Reflexivity: {ticker} narrative drop but divergence {divergence}% ≤7% — no signal")

    elif classification == "FUNDAMENTAL":
        msg = (
            f"⚠️ <b>FUNDAMENTAL ALERT — {ticker}</b>\n"
            f"Drop: {chg:+.1f}% | Classification: FUNDAMENTAL\n"
            f"Thesis review required | See Lesson 05\n"
            f"Reason: {reason}"
        )
        _send_telegram(msg)
        logger.info(f"Reflexivity FUNDAMENTAL alert sent: {ticker}")

    else:
        logger.info(f"Reflexivity: {ticker} narrative but thesis NOT intact — no entry signal")


# ══════════════════════════════════════════════════════════════════════════════
# DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def generate_briefing(briefing_id: str, force: bool = False) -> Optional[str]:
    logger.info(f"Generating: {briefing_id}")
    if not force and briefing_id != "olympus_weekly" and not _is_weekday():
        logger.info(f"Skipping {briefing_id} — weekend")
        return None
    if briefing_id in ("master_daily", "morning_macro"):
        return generate_master_daily()
    elif briefing_id in ("us_open", "us_premarket"):
        return generate_us_open()
    elif briefing_id in ("us_close",):
        return generate_us_close()
    elif briefing_id == "olympus_weekly":
        return None
    else:
        logger.error(f"Unknown briefing_id: {briefing_id}")
        return None


if __name__ == "__main__":
    run_news_pulse()
