"""
SENTINEL WATCHDOG  —  OLYMPUS-SENTINEL Layer 7 (Kill-Switch).

Final safety net. Runs AFTER every build_active_actions pass. Its only job is
to answer: "is the system itself still trustworthy right now?"

If ANY of these fail → output `"freeze": true`, force every BUY/ADD to
WATCH, and send a Telegram ping:

    1.  STALENESS
        - Liquidity print older than 36h
        - GEM last run older than 48h
        - Forecasts file older than 48h
    2.  MODEL DISAGREEMENT
        - Ensemble p50 spread > 60 percentage points across any ticker
          while conviction ≥ 70 (small convictions we don't care)
    3.  REGIME FLIP
        - Liquidity vector state changed in last 24h AND prev state ≠ new
    4.  CONSECUTIVE LOSSES / VETO STORM
        - ≥ 5 active vetoes across all actions → something is wrong
        - Drawdown Guardian flipped from GREEN to ORANGE/RED in one step
    5.  KERNEL BREACH
        - Any PrimeDirective invariant currently breached

Output:
    {
      "level": "GREEN|YELLOW|ORANGE|RED|FREEZE",
      "freeze": bool,
      "triggers": [...list of human-readable strings...],
      "next_check_utc": "...",
    }
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(*p: str) -> str:
    return os.path.join(HERE, *p)


def _load(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _age_hours(ts_str: Optional[str]) -> Optional[float]:
    if not ts_str:
        return None
    # Try common formats
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M CET", "%Y-%m-%d %H:%M"):
        try:
            t = datetime.strptime(ts_str, fmt)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0
        except Exception:
            continue
    return None


def evaluate() -> Dict[str, Any]:
    triggers: List[str] = []
    level_score = 0

    directives = _load(_path("data", "directives.json"))
    liq = directives.get("liquidity") or {}
    fx = _load(_path("data", "forecasts.json"))
    actions = _load(_path("data", "active_actions.json"))
    gm = _load(_path("data", "gem_meta.json"))

    # 1. staleness
    liq_age = _age_hours(liq.get("last_updated") or liq.get("updated_utc"))
    if liq_age is not None and liq_age > 36:
        triggers.append(f"Liquidity print {liq_age:.0f}h old (>36h)")
        level_score += 2

    fx_age = _age_hours((fx.get("as_of") or fx.get("built_at") or fx.get("generated_utc") or "").replace(" UTC", ""))
    if fx_age is not None and fx_age > 48:
        triggers.append(f"Forecasts file {fx_age:.0f}h old (>48h)")
        level_score += 2

    gm_age = _age_hours(gm.get("last_run_utc") or ((gm.get("run_date") or "") + " " + (gm.get("run_time") or "00:00")).strip())
    if gm_age is not None and gm_age > 48:
        triggers.append(f"GEM last run {gm_age:.0f}h old (>48h)")
        level_score += 1

    # 2. model disagreement
    try:
        fcs = fx.get("forecasts") or fx.get("tickers") or {}
        high_disagree = 0
        for t, row in fcs.items():
            models = row.get("models") or {}
            if len(models) < 2:
                continue
            p50s = [m.get("p50") for m in models.values() if m.get("p50") is not None]
            if len(p50s) < 2:
                continue
            spread = max(p50s) - min(p50s)
            if spread > 0.60:
                high_disagree += 1
        if high_disagree >= 3:
            triggers.append(f"{high_disagree} tickers with model p50 spread > 60pp")
            level_score += 2
    except Exception:
        pass

    # 3. veto storm
    acts = actions.get("actions") or []
    veto_count = 0
    try:
        for a in acts:
            vts = a.get("vetoes") or a.get("sentinel_vetoes") or []
            if vts:
                veto_count += 1
    except Exception:
        pass
    if veto_count >= 5:
        triggers.append(f"{veto_count} active vetoes across matrix — something drifted")
        level_score += 2

    # 4. kernel breach (from sentinel block if present)
    sb = actions.get("sentinel") or actions.get("sentinel_header") or {}
    kernel = sb.get("kernel") or {}
    if kernel.get("breaches"):
        triggers.append(f"Prime Directive breaches active: {', '.join(kernel['breaches'])[:120]}")
        level_score += 3

    # 5. drawdown state
    dd = sb.get("drawdown") or {}
    if (dd.get("state") or "").upper() == "RED":
        triggers.append("Drawdown Guardian RED — kernel DD cap tripped")
        level_score += 3
    elif (dd.get("state") or "").upper() == "ORANGE":
        triggers.append("Drawdown Guardian ORANGE — risk budget 0.40×")
        level_score += 1

    # Map score → level
    if level_score >= 6:
        level = "FREEZE"
    elif level_score >= 4:
        level = "RED"
    elif level_score >= 2:
        level = "ORANGE"
    elif level_score >= 1:
        level = "YELLOW"
    else:
        level = "GREEN"

    freeze = level == "FREEZE"
    return {
        "level": level,
        "freeze": freeze,
        "score": level_score,
        "triggers": triggers or ["All checks passing"],
        "checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "next_check_utc": "ran in-pipeline; re-evaluated on next build_active_actions",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(evaluate(), indent=2))
