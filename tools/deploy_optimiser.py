"""
DEPLOY OPTIMISER — "where does €1,500 go this month?"

Inputs:
  - data/forecasts.json           → ensemble EV, p05, p50, p95 per ticker
  - data/active_actions.json      → vetoes, blocks, verbs, OPS, group
  - data/premium_scores.json      → OPS peer-relative valuation
  - data/model_weights.json       → prior confidence (from reflection)
  - gem_inputs/core_satellite.json→ core-first routing
  - state.json                    → dry_powder + incoming monthly EUR

Output:
  - data/deploy_plan.json  (mirrored to /var/www/html/)

Math:
  For every eligible ticker (verb in BUY/ADD/HOLD, no VETO, no FREEZE,
  no pending_catalyst, OPS < 180):

      marginal_sharpe = EV_pct / max(2, |ES5_pct|)
      adj             = marginal_sharpe × (p_win or 0.5) × conviction_mult

  Conviction multiplier:
      CORE  → 1.25 (they compound forever)
      SATELLITE → 1.00
      UNCLASSIFIED → 0.85 (we don't know what they are yet)

  Rank descending. Take top-5. Allocate by marginal Sharpe share of
  the top-3 (60/25/15 cap to prevent all-in):
      top1 = 60% of deployable
      top2 = 25%
      top3 = 15%
      top4, top5 listed as "next-in-queue"

  Deployable EUR = (state.json.dry_powder.TR_EUR) + (configured monthly
  contribution, default €1,500).

  All numbers then pass through kernel + correlation + liquidity gates
  defensively (active_actions.json already enforced these; we just mirror
  the blocks so the plan is self-explanatory).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

ACTIVE = os.path.join(BASE, "data", "active_actions.json")
FORECASTS = os.path.join(BASE, "data", "forecasts.json")
PREMIUM = os.path.join(BASE, "data", "premium_scores.json")
CORE_SAT = os.path.join(BASE, "gem_inputs", "core_satellite.json")
STATE = os.path.join(BASE, "state.json")
OUT = os.path.join(BASE, "data", "deploy_plan.json")
WEBROOT_OUT = "/var/www/html/deploy_plan.json"

DEFAULT_MONTHLY_EUR = 1500.0
CONV_MULT = {"CORE": 1.25, "SATELLITE": 1.00, "UNCLASSIFIED": 0.85}
MAX_OPS_FOR_DEPLOY = 180
MIN_EV_PCT = 5.0              # no point deploying where forecast EV < 5%
MIN_P_WIN = 0.45              # coin-flip guard


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _eligibility(action: Dict[str, Any]) -> Optional[str]:
    """Return a rejection reason, or None if eligible."""
    verb = (action.get("verb") or "").upper()
    if verb in ("EXIT", "TRIM"):
        return f"verb={verb}"
    blocks = action.get("blocks") or []
    vetoes = action.get("vetoes") or []
    killers = {"sentinel_freeze", "sentinel_veto", "correlation_veto",
               "ops_extreme", "pending_catalyst", "tail_defcon1",
               "tail_defcon2", "kernel_freeze", "liquidity_danger_freeze"}
    hit = [b for b in list(blocks) + list(vetoes) if b in killers]
    if hit:
        return f"blocked:{','.join(hit)}"
    ops = action.get("ops")
    if ops is not None and float(ops) >= MAX_OPS_FOR_DEPLOY:
        return f"ops={ops}"
    ev = action.get("ev_pct")
    if ev is not None and float(ev) < MIN_EV_PCT:
        return f"ev<{MIN_EV_PCT}%"
    pw = action.get("p_win")
    if pw is not None and float(pw) < MIN_P_WIN:
        return f"p_win<{MIN_P_WIN}"
    return None


def _marginal_sharpe(action: Dict[str, Any]) -> float:
    ev = float(action.get("ev_pct") or 0.0)
    es5 = abs(float(action.get("es5_pct") or -20.0))
    if es5 < 2.0:
        es5 = 2.0
    return ev / es5


def run(monthly_contribution_eur: Optional[float] = None) -> Dict[str, Any]:
    active = _load(ACTIVE, {})
    actions = active.get("actions") or {}
    fc = (_load(FORECASTS, {}).get("tickers") or {})
    prem = (_load(PREMIUM, {}).get("tickers") or {})
    cs = _load(CORE_SAT, {"core_tickers": [], "satellite_tickers": []})
    core_set = set(cs.get("core_tickers") or [])
    sat_set = set(cs.get("satellite_tickers") or [])
    state = _load(STATE, {})

    dp = (state.get("dry_powder") or {})
    powder_eur = float(dp.get("TR_EUR") or 0.0)
    monthly_eur = float(monthly_contribution_eur if monthly_contribution_eur is not None
                         else DEFAULT_MONTHLY_EUR)
    deployable = powder_eur + monthly_eur

    # Killed by sentinel? Tell the user and stop.
    watch = active.get("sentinel_watchdog") or {}
    if watch.get("freeze"):
        plan = {
            "schema_version": 1,
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "FROZEN",
            "reason": f"sentinel watchdog level={watch.get('level')} — all deploy blocked",
            "triggers": watch.get("triggers") or [],
            "deployable_eur": deployable,
            "top_picks": [],
            "next_in_queue": [],
            "rejected": [],
        }
        _write(plan)
        return plan

    scored: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for tk, action in actions.items():
        group = action.get("group") or (
            "CORE" if tk in core_set else ("SATELLITE" if tk in sat_set else "UNCLASSIFIED")
        )
        reason_out = _eligibility(action)
        if reason_out:
            rejected.append({"ticker": tk, "reason": reason_out, "verb": action.get("verb"),
                             "ev_pct": action.get("ev_pct"), "ops": action.get("ops")})
            continue

        ms = _marginal_sharpe(action)
        pw = float(action.get("p_win") or 0.5)
        mult = CONV_MULT.get(group, 1.0)
        adj = ms * pw * mult

        ens = (fc.get(tk) or {}).get("ensemble") or {}
        scored.append({
            "ticker": tk,
            "group": group,
            "verb": action.get("verb"),
            "ev_pct": action.get("ev_pct"),
            "es5_pct": action.get("es5_pct"),
            "p_win": action.get("p_win"),
            "conviction": action.get("conviction"),
            "ops": action.get("ops"),
            "marginal_sharpe": round(ms, 3),
            "adj_score": round(adj, 3),
            "forecast_source": action.get("forecast_source"),
            "p50_1y": ens.get("p50"),
            "p95_1y": ens.get("p95"),
            "note": action.get("reason"),
        })

    scored.sort(key=lambda r: r["adj_score"], reverse=True)
    top = scored[:3]
    next_q = scored[3:8]

    weights = [0.60, 0.25, 0.15]
    picks: List[Dict[str, Any]] = []
    for i, row in enumerate(top):
        w = weights[i] if i < len(weights) else 0.0
        alloc = round(deployable * w, 2)
        picks.append({
            **row,
            "allocation_eur": alloc,
            "allocation_pct_of_deployable": round(w * 100, 1),
        })

    status = "READY" if picks else "NO_CANDIDATES"
    plan = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "powder_eur": powder_eur,
        "monthly_contribution_eur": monthly_eur,
        "deployable_eur": round(deployable, 2),
        "top_picks": picks,
        "next_in_queue": next_q,
        "rejected": rejected[:25],
        "filters": {
            "max_ops_for_deploy": MAX_OPS_FOR_DEPLOY,
            "min_ev_pct": MIN_EV_PCT,
            "min_p_win": MIN_P_WIN,
            "conviction_multipliers": CONV_MULT,
        },
        "mandate": _mandate_line(picks, deployable),
    }
    _write(plan)
    return plan


def _mandate_line(picks: List[Dict[str, Any]], deployable: float) -> str:
    if not picks:
        return "No eligible deploy candidates — raise dry powder or wait for gates to clear."
    parts = []
    for p in picks:
        parts.append(f"{p['ticker']} €{p['allocation_eur']:.0f}")
    return f"DEPLOY €{deployable:.0f} → {' · '.join(parts)} (correlation-adjusted, OPS-screened)"


def _write(plan: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    try:
        import shutil
        shutil.copy2(OUT, WEBROOT_OUT)
    except Exception:
        pass


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, indent=2))
