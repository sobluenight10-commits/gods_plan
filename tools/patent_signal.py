"""
PATENT SIGNAL — USPTO filings velocity for discovery sleeve.

R&D inflection often shows up 12–18 months ahead of revenue inflection.
USPTO's PatentsView + Google Patents public endpoints let us detect
that inflection for free.

This module:
  1. Accepts a theme → CPC-class mapping (in gem_inputs/patent_cpc.json).
  2. For each of our 8 secular themes, counts patent filings in the
     relevant CPC classes over the last 90d vs trailing 12 months.
  3. Computes "velocity_ratio = (90d rate) / (12m rate) — so > 1.5x
     flags an accelerating theme.
  4. Optionally queries by applicant name (e.g., "Kratos Defense",
     "BEAM Therapeutics") to compute per-ticker patent velocity.

Data source: PatentsView API (https://api.patentsview.org/patents/query)
— free, no key required, rate-limited to a few req/second. Falls back
gracefully to empty if unreachable.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    import urllib.request
    import urllib.parse
    _HAS_URLLIB = True
except Exception:
    _HAS_URLLIB = False

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

CPC_MAP_FILE = os.path.join(BASE, "gem_inputs", "patent_cpc.json")
OUT = os.path.join(BASE, "data", "patent_signal.json")
WEBROOT_OUT = "/var/www/html/patent_signal.json"

# Seed CPC → theme mapping (overridable via gem_inputs/patent_cpc.json)
DEFAULT_THEME_CPC: Dict[str, List[str]] = {
    "AI_COMPUTE":   ["G06N", "G06F15/16", "G06F15/18", "G06F9/38"],    # neural compute, parallel arch
    "NUCLEAR":      ["G21C", "G21D", "G21G", "C01G43"],                # reactor + fuel chem
    "SPACE_ECON":   ["B64G", "H04B7/185", "H04W4/40"],                 # spacecraft, sat comms
    "GENE_EDITING": ["C12N15/10", "C12N15/11", "C12N15/90"],           # base & prime editing
    "DEFENSE_AUTON":["F41G", "F41H", "G05D1/10", "B64C39/02"],         # targeting, UAV autopilot
    "BIOTECH_INFRA":["C12M", "C12Q1/68", "B01L3/00"],                  # bioprocess, assays
    "CYBER":        ["H04L63", "G06F21/56", "G06F21/57"],              # network sec, malware
    "CRITICAL_MIN": ["C22B", "C01F17", "B01D11"],                      # metallurgy, rare earths
}

# Seed ticker → applicant-name for per-ticker velocity (extend freely)
DEFAULT_TICKER_APPLICANT: Dict[str, str] = {
    "PLTR":  "Palantir Technologies",
    "KTOS":  "Kratos Defense",
    "AVAV":  "AeroVironment",
    "RKLB":  "Rocket Lab",
    "ASTS":  "AST SpaceMobile",
    "PL":    "Planet Labs",
    "BKSY":  "BlackSky Technology",
    "BEAM":  "Beam Therapeutics",
    "NTLA":  "Intellia Therapeutics",
    "CRSP":  "CRISPR Therapeutics",
    "OKLO":  "Oklo",
    "NNE":   "Nano Nuclear",
    "LEU":   "Centrus Energy",
    "LTBR":  "Lightbridge",
    "NVDA":  "NVIDIA",
    "TSM":   "Taiwan Semiconductor",
    "ASML":  "ASML",
    "AMAT":  "Applied Materials",
    "COHR":  "Coherent",
    "VRT":   "Vertiv",
    "TMO":   "Thermo Fisher",
}

PATENTSVIEW_URL = "https://api.patentsview.org/patents/query"
USER_AGENT = "OLYMPUS-SENTINEL research"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _query_patentsview(where: Dict[str, Any], *, start: str, end: str, timeout: float = 10.0) -> Optional[int]:
    """Return count of patents granted in [start, end] matching where-clause."""
    if not _HAS_URLLIB:
        return None
    body = {
        "q": {
            "_and": [
                where,
                {"_gte": {"patent_date": start}},
                {"_lte": {"patent_date": end}},
            ]
        },
        "f": ["patent_number"],
        "o": {"per_page": 25},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(PATENTSVIEW_URL, data=data,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": USER_AGENT},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return int(out.get("total_patent_count") or 0)
    except Exception:
        return None


def _velocity(theme_id: str, cpc_list: List[str]) -> Dict[str, Any]:
    now = _now()
    window_90 = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    window_12m = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")

    # PatentsView accepts CPC subclass patterns like "cpc_subgroup_id"; we
    # approximate with a looser "cpc_group_id" OR join.
    where = {"_or": [{"_contains": {"cpc_group_id": cpc}} for cpc in cpc_list]}
    n90 = _query_patentsview(where, start=window_90, end=today)
    n12 = _query_patentsview(where, start=window_12m, end=today)
    if n90 is None or n12 is None:
        return {"theme_id": theme_id, "velocity_ratio": None,
                "status": "no_data", "n90": n90, "n12": n12}
    rate_90 = n90 / 90.0
    rate_12 = n12 / 365.0 if n12 else 0.0
    ratio = (rate_90 / rate_12) if rate_12 else None

    if ratio is None:
        status = "unknown"
    elif ratio >= 1.5:
        status = "ACCELERATING"
    elif ratio <= 0.75:
        status = "DECELERATING"
    else:
        status = "STABLE"

    return {
        "theme_id": theme_id,
        "cpc": cpc_list,
        "n_last_90d": n90,
        "n_last_12m": n12,
        "rate_per_day_90d": round(rate_90, 2),
        "rate_per_day_12m": round(rate_12, 2),
        "velocity_ratio": round(ratio, 2) if ratio is not None else None,
        "status": status,
    }


def _ticker_velocity(ticker: str, applicant: str) -> Dict[str, Any]:
    now = _now()
    w_90 = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    w_12m = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")

    where = {"_contains": {"assignee_organization": applicant}}
    n90 = _query_patentsview(where, start=w_90, end=today)
    n12 = _query_patentsview(where, start=w_12m, end=today)
    if n90 is None or n12 is None:
        return {"ticker": ticker, "applicant": applicant, "velocity_ratio": None,
                "status": "no_data"}
    rate_90 = n90 / 90.0
    rate_12 = n12 / 365.0 if n12 else 0.0
    ratio = (rate_90 / rate_12) if rate_12 else None
    status = "UNKNOWN"
    if ratio is not None:
        status = "ACCELERATING" if ratio >= 1.5 else ("DECELERATING" if ratio <= 0.75 else "STABLE")
    return {"ticker": ticker, "applicant": applicant,
            "n_last_90d": n90, "n_last_12m": n12,
            "velocity_ratio": round(ratio, 2) if ratio is not None else None,
            "status": status}


def run() -> Dict[str, Any]:
    theme_cpc = dict(DEFAULT_THEME_CPC)
    override = _load(CPC_MAP_FILE, None)
    if isinstance(override, dict):
        theme_cpc.update(override)

    themes: List[Dict[str, Any]] = []
    for theme_id, cpcs in theme_cpc.items():
        v = _velocity(theme_id, cpcs)
        themes.append(v)
        time.sleep(0.2)

    tickers: List[Dict[str, Any]] = []
    for tk, applicant in DEFAULT_TICKER_APPLICANT.items():
        v = _ticker_velocity(tk, applicant)
        tickers.append(v)
        time.sleep(0.2)

    accelerating = [t for t in themes if t.get("status") == "ACCELERATING"]
    accelerating.sort(key=lambda r: (r.get("velocity_ratio") or 0), reverse=True)
    accelerating_tickers = [t for t in tickers if t.get("status") == "ACCELERATING"]
    accelerating_tickers.sort(key=lambda r: (r.get("velocity_ratio") or 0), reverse=True)

    payload = {
        "schema_version": 1,
        "generated_utc": _iso(_now()),
        "source": "PatentsView (USPTO)",
        "themes": themes,
        "tickers": tickers,
        "earth_shifter_watch": {
            "accelerating_themes": [t["theme_id"] for t in accelerating[:3]],
            "accelerating_tickers": [t["ticker"] for t in accelerating_tickers[:5]],
        },
        "mandate": _mandate(accelerating, accelerating_tickers),
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


def _mandate(themes: List[Dict[str, Any]], tickers: List[Dict[str, Any]]) -> str:
    if not themes and not tickers:
        return "No accelerating patent classes this window."
    parts = []
    if themes:
        parts.append("Theme accel: " + ", ".join(t["theme_id"] for t in themes[:3]))
    if tickers:
        parts.append("Ticker accel: " + ", ".join(f"{t['ticker']}({t['velocity_ratio']}x)" for t in tickers[:5]))
    return " · ".join(parts)


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "accel_themes": out.get("earth_shifter_watch", {}).get("accelerating_themes"),
        "accel_tickers": out.get("earth_shifter_watch", {}).get("accelerating_tickers"),
        "mandate": out.get("mandate"),
    }, indent=2))
