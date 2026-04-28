"""
SCENARIO ENGINE — probability-weighted macro thesis encoder.

The user's hypothesis (Apr 2026):
    1. New Fed Chair confirmed; Powell investigation halted.
    2. War (Russia-Ukraine) ends or de-escalates before US midterm vote.
    3. Trump + new Fed Chair cooperate to release liquidity → market boost.
    Net effect: high odds of equity expansion in the 5-month window.

The system must NOT pretend to know the future. Instead it stores the
hypothesis as named scenarios, each with:
    - probability  (0-1, GOD-editable)
    - liquidity_uplift_b   ($B added to net liquidity if scenario fires)
    - sector_uplift        per-sector EV adjustment if scenario fires
    - confirmation_signals (observable checkpoints — "did it happen?")

Output: data/macro_scenario.json

The strike_radar / strike_cards consume this to:
    - blend the unconditional EV with the scenario-conditional EV;
    - report a 1-line "scenario state" so GOD knows which assumption is live.

The hypotheses live in `config/scenarios.json` (GOD-editable).
We seed the file on first run with the user's stated thesis.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

CFG_DIR = os.path.join(BASE, "config")
CFG = os.path.join(CFG_DIR, "scenarios.json")
OUT = os.path.join(BASE, "data", "macro_scenario.json")
WEBROOT_OUT = "/var/www/html/macro_scenario.json"

DEFAULT_SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "fed_pivot_2026",
        "name": "Fed pivot → liquidity release",
        "probability": 0.55,
        "horizon_days": 150,
        "thesis": (
            "New Fed Chair confirmed; Powell investigation halted. "
            "Coordinated push with administration to add reserves and "
            "drain RRP to support equities into midterm vote."
        ),
        "liquidity_uplift_b": 250,
        "sector_uplift_pct": {
            "Intelligence": 12,
            "Intelligence/AI": 12,
            "Energy": 8,
            "Energy/Uranium": 10,
            "Space": 7,
            "Space/Logistics": 7,
            "Bio": 6,
            "Bio-Engineering": 6,
            "Robotics": 9,
            "Robotics/Defense": 9,
            "Infrastructure": 8,
            "Global Issue": 5,
        },
        "confirmation_signals": [
            "Fed Chair confirmation announced (Senate vote)",
            "FOMC dot-plot revised dovish",
            "Reserves (WRESBAL) week-over-week ≥ +$30B",
            "RRP balance week-over-week ≤ -$20B",
            "DXY breaks below 102",
        ],
    },
    {
        "id": "geopolitical_deescalation",
        "name": "War ends / de-escalation before midterms",
        "probability": 0.40,
        "horizon_days": 150,
        "thesis": (
            "Russia-Ukraine ceasefire or major de-escalation lands "
            "before US Nov vote. Risk-on impulse, defense names rotate "
            "down, energy/copper find a floor."
        ),
        "liquidity_uplift_b": 50,
        "sector_uplift_pct": {
            "Intelligence": 5,
            "Intelligence/AI": 5,
            "Energy": 4,
            "Energy/Uranium": 3,
            "Space": 3,
            "Space/Logistics": 3,
            "Bio": 4,
            "Bio-Engineering": 4,
            "Robotics": -3,
            "Robotics/Defense": -8,
            "Infrastructure": 4,
            "Global Issue": 6,
        },
        "confirmation_signals": [
            "Ceasefire announced",
            "VIX < 16",
            "ITA / XAR ETF -5% on the news",
            "Brent crude -8% on relief",
        ],
    },
    {
        "id": "scenario_fail_recession",
        "name": "Recession / earnings recession deepens",
        "probability": 0.20,
        "horizon_days": 150,
        "thesis": (
            "Q2 2026 earnings disappoint, AI capex pause confirmed, "
            "credit spreads widen, no Fed rescue in time. Defensive "
            "rotation; cash and gold outperform."
        ),
        "liquidity_uplift_b": -150,
        "sector_uplift_pct": {
            "Intelligence": -15,
            "Intelligence/AI": -15,
            "Energy": -10,
            "Energy/Uranium": -8,
            "Space": -12,
            "Space/Logistics": -12,
            "Bio": -8,
            "Bio-Engineering": -8,
            "Robotics": -10,
            "Robotics/Defense": -5,
            "Infrastructure": -10,
            "Global Issue": -5,
        },
        "confirmation_signals": [
            "ISM Mfg < 47",
            "HYG drawdown > -5% from 60d high",
            "Yield curve re-inverts hard",
            "Q2 earnings beat-rate < 60%",
        ],
    },
]


def _load_or_seed_scenarios() -> List[Dict[str, Any]]:
    os.makedirs(CFG_DIR, exist_ok=True)
    if not os.path.exists(CFG):
        with open(CFG, "w", encoding="utf-8") as f:
            json.dump({"scenarios": DEFAULT_SCENARIOS}, f, indent=2, ensure_ascii=False)
        return DEFAULT_SCENARIOS
    try:
        with open(CFG, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("scenarios") or DEFAULT_SCENARIOS
    except Exception:
        return DEFAULT_SCENARIOS


def _expected_value(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Probability-weighted aggregates."""
    total_p = sum(float(s.get("probability") or 0) for s in scenarios)
    if total_p <= 0:
        return {"liquidity_ev_b": 0.0, "sector_ev_pct": {}}
    liq_ev = sum(float(s.get("probability") or 0) *
                  float(s.get("liquidity_uplift_b") or 0)
                  for s in scenarios)
    sector_ev: Dict[str, float] = {}
    for s in scenarios:
        p = float(s.get("probability") or 0)
        for sec, up in (s.get("sector_uplift_pct") or {}).items():
            sector_ev[sec] = sector_ev.get(sec, 0.0) + p * float(up)
    return {
        "liquidity_ev_b": round(liq_ev, 1),
        "sector_ev_pct": {k: round(v, 1) for k, v in sector_ev.items()},
        "total_probability_used": round(total_p, 2),
    }


def run() -> Dict[str, Any]:
    scenarios = _load_or_seed_scenarios()
    ev = _expected_value(scenarios)
    out = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scenarios": scenarios,
        "expected_value": ev,
        "headline": (
            f"Scenario-weighted liquidity uplift ${ev['liquidity_ev_b']:+.0f}B · "
            f"Top scenarios: " + ", ".join(
                f"{s['name']} ({int(float(s.get('probability') or 0)*100)}%)"
                for s in scenarios[:2]
            )
        ),
        "config_path": "config/scenarios.json (GOD-editable)",
    }
    _write(out)
    return out


def _write(payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    try:
        if os.path.isdir(os.path.dirname(WEBROOT_OUT)):
            shutil.copy2(OUT, WEBROOT_OUT)
    except Exception as exc:
        print(f"[scenario_engine] webroot mirror failed: {exc}")


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, indent=2))
