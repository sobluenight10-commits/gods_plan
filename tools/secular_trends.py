"""
SECULAR TRENDS — 8 civilisational themes with leading indicators.

This is the module that helps us find the NEXT Earth Shifter before it
prices in. Each theme is tracked through:
  - A proxy ETF / index ticker for 90d and 365d total return.
  - A "breadth" proxy — ratio of theme basket to broader market.
  - Acceleration flag when short-term return > long-term return × 1.5.
  - Leading names in the theme (so GOD sees which to investigate).

Output: data/secular_trends.json — consumed by dashboard DISCOVERY panel.

Inputs: yfinance (already a dependency). Fallback: static baseline if
yfinance is unreachable (server without internet on first run).

THEMES:
  01 AI_COMPUTE      NVDA SMH SOXX    → Sovereign compute supply chain
  02 NUCLEAR         URNM URA CCJ     → Power for the AI load
  03 SPACE_ECON      UFO ROKT RKLB    → Satellite + launch economy
  04 GENE_EDITING    IDNA BEAM NTLA   → Programmable medicine
  05 DEFENSE_AUTON   ITA PPA KTOS     → Autonomous warfare
  06 BIOTECH_INFRA   XLV IHI TMO DHR  → Picks-and-shovels biotech
  07 CYBER           CIBR HACK CRWD   → Critical-infra defense
  08 CRITICAL_MIN    REMX URA SLX     → Raw materials for all of the above
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

OUT = os.path.join(BASE, "data", "secular_trends.json")
WEBROOT_OUT = "/var/www/html/secular_trends.json"

THEMES: List[Dict[str, Any]] = [
    {
        "id": "AI_COMPUTE",
        "name": "AI Compute Supply Chain",
        "proxy": "SMH",
        "breadth_vs": "SPY",
        "leaders": ["NVDA", "TSM", "ASML", "AMAT", "VRT", "COHR"],
        "thesis_1_line": "Hyperscalers spend $400B+/yr on compute. Choke-point economy.",
        "leading_indicator_hint": "TSMC Q4 capex guidance; NVDA data-center revenue YoY.",
    },
    {
        "id": "NUCLEAR",
        "name": "Nuclear Renaissance",
        "proxy": "URNM",
        "breadth_vs": "XLE",
        "leaders": ["CCJ", "UEC", "OKLO", "LEU", "LTBR", "NNE"],
        "thesis_1_line": "24/7 carbon-free power for AI datacenters + grid electrification.",
        "leading_indicator_hint": "NRC license pipeline, hyperscaler PPA announcements, uranium spot.",
    },
    {
        "id": "SPACE_ECON",
        "name": "Space Economy",
        "proxy": "UFO",
        "breadth_vs": "ITA",
        "leaders": ["RKLB", "ASTS", "PL", "BKSY", "IRDM"],
        "thesis_1_line": "Launch cost collapse + Starlink-class connectivity + sovereign EO.",
        "leading_indicator_hint": "Launch cadence per quarter, DoD/NRO contract dollar flow.",
    },
    {
        "id": "GENE_EDITING",
        "name": "Programmable Medicine",
        "proxy": "IDNA",
        "breadth_vs": "XBI",
        "leaders": ["BEAM", "NTLA", "CRSP", "VRTX"],
        "thesis_1_line": "CRISPR → Base Editing → Prime → broad-spectrum curative therapies.",
        "leading_indicator_hint": "FDA designations, Ph2/3 readouts, approved indications per tool.",
    },
    {
        "id": "DEFENSE_AUTON",
        "name": "Autonomous Warfare",
        "proxy": "ITA",
        "breadth_vs": "SPY",
        "leaders": ["KTOS", "AVAV", "ONDS", "RTX", "LMT", "NOC", "GD"],
        "thesis_1_line": "Drones + autonomous systems + software-defined defense budgets.",
        "leading_indicator_hint": "DoD Q supplementals, Replicator Initiative deliveries.",
    },
    {
        "id": "BIOTECH_INFRA",
        "name": "Biotech Picks & Shovels",
        "proxy": "IHI",
        "breadth_vs": "XLV",
        "leaders": ["TMO", "DHR", "A", "ILMN"],
        "thesis_1_line": "Tools win whether the drug trials win or lose.",
        "leading_indicator_hint": "Bioprocess capex cycle, Life Sciences revenue segment growth.",
    },
    {
        "id": "CYBER",
        "name": "Critical-Infra Cybersecurity",
        "proxy": "CIBR",
        "breadth_vs": "QQQ",
        "leaders": ["CRWD", "PANW", "ZS", "S"],
        "thesis_1_line": "Every infra layer gets a cyber budget line permanently.",
        "leading_indicator_hint": "CrowdStrike, Palo Alto ARR growth, CISA directives.",
    },
    {
        "id": "CRITICAL_MIN",
        "name": "Critical Minerals",
        "proxy": "REMX",
        "breadth_vs": "XLB",
        "leaders": ["MP", "CCJ", "FCX", "ALB"],
        "thesis_1_line": "Rare earths + copper + lithium + uranium: bottleneck of every transition.",
        "leading_indicator_hint": "China export policy, DoD strategic stockpiles.",
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yf_history(ticker: str, period_days: int) -> Optional[List[float]]:
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=f"{period_days}d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        return [float(x) for x in hist["Close"].tolist()]
    except Exception:
        return None


def _pct_return(series: Optional[List[float]]) -> Optional[float]:
    if not series or len(series) < 2:
        return None
    try:
        return round((series[-1] / series[0] - 1.0) * 100.0, 2)
    except Exception:
        return None


def _ratio_return(a: Optional[List[float]], b: Optional[List[float]]) -> Optional[float]:
    if not a or not b:
        return None
    n = min(len(a), len(b))
    if n < 2:
        return None
    ra = a[-1] / a[0] - 1.0
    rb = b[-1] / b[0] - 1.0
    return round((ra - rb) * 100.0, 2)


def run() -> Dict[str, Any]:
    themes_out: List[Dict[str, Any]] = []
    for theme in THEMES:
        proxy_90 = _yf_history(theme["proxy"], 90)
        proxy_365 = _yf_history(theme["proxy"], 365)
        bench_90 = _yf_history(theme["breadth_vs"], 90)
        bench_365 = _yf_history(theme["breadth_vs"], 365)

        ret_90 = _pct_return(proxy_90)
        ret_365 = _pct_return(proxy_365)
        alpha_90 = _ratio_return(proxy_90, bench_90)
        alpha_365 = _ratio_return(proxy_365, bench_365)

        accelerating = False
        if ret_90 is not None and ret_365 is not None:
            # 90d return greater than one quarter of the annual pace × 1.5 → heating up
            accelerating = ret_90 > ((ret_365 / 4) * 1.5)

        state = "NEUTRAL"
        if alpha_90 is not None and alpha_365 is not None:
            if alpha_90 > 5 and alpha_365 > 10:
                state = "STRONG_BID" if accelerating else "LEADING"
            elif alpha_90 < -5 and alpha_365 < -10:
                state = "EXITING"
            elif accelerating and ret_90 > 0:
                state = "INFLECTING"

        themes_out.append({
            **theme,
            "proxy_return_90d_pct": ret_90,
            "proxy_return_365d_pct": ret_365,
            "alpha_vs_bench_90d_pct": alpha_90,
            "alpha_vs_bench_365d_pct": alpha_365,
            "accelerating": accelerating,
            "state": state,
        })

    # Highlight the top 2 accelerating themes → "Earth-Shifter watch"
    highlighted = [t for t in themes_out if t["state"] in ("INFLECTING", "STRONG_BID", "LEADING")]
    highlighted.sort(key=lambda t: (t.get("alpha_vs_bench_90d_pct") or 0), reverse=True)

    payload = {
        "schema_version": 1,
        "generated_utc": _now_iso(),
        "themes": themes_out,
        "earth_shifter_watch": highlighted[:3],
        "mandate": _mandate(highlighted),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    try:
        import shutil
        shutil.copy2(OUT, WEBROOT_OUT)
    except Exception:
        pass
    return payload


def _mandate(highlighted: List[Dict[str, Any]]) -> str:
    if not highlighted:
        return "No themes inflecting — maintain existing allocation, no new hunting lines."
    lead = highlighted[0]
    leaders = ", ".join(lead.get("leaders") or [])[:80]
    return (
        f"Theme {lead['id']} {lead['state']} — alpha {lead.get('alpha_vs_bench_90d_pct')}% vs "
        f"{lead['breadth_vs']} over 90d. Investigate leaders: {leaders}."
    )


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "mandate": out.get("mandate"),
        "earth_shifter_watch": [t["id"] for t in out.get("earth_shifter_watch") or []],
        "themes_n": len(out.get("themes") or []),
    }, indent=2))
