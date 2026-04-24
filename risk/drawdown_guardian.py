"""
DRAWDOWN GUARDIAN — OLYMPUS-SENTINEL Layer 3, Ring 5.

Computes portfolio drawdown from best available inputs and returns
a state machine:

    DD ≤ 5%    GREEN   — full risk budget (×1.00)
    DD 5–10%   YELLOW  — no new non-core adds; tactical trims ok (×0.75)
    DD 10–15%  ORANGE  — trim satellite to zero; core untouched (×0.40)
    DD > 15%   RED     — freeze all buys; kernel I1 trips (×0.00)

Inputs (in order of preference):
  1. `history_pct` — pre-computed DD fraction (0..1) if caller has it.
  2. Positions list with `entry_price`, `current_price`: cost-basis DD
     used as the best proxy we have without a NAV series.

Notes:
  - This is a *safety* module — it errs on the side of being conservative
    when data is incomplete.
  - A future upgrade will plug in a proper NAV time series from state.json.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

GREEN_MAX = 0.05
YELLOW_MAX = 0.10
ORANGE_MAX = 0.15

BUDGET = {
    "GREEN": 1.00,
    "YELLOW": 0.75,
    "ORANGE": 0.40,
    "RED": 0.00,
}


def _pct(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return f"{x*100:.1f}%"


def cost_basis_dd(positions: Iterable[Dict[str, Any]]) -> Optional[float]:
    """
    Return a positive fraction (0..1) representing the weighted drawdown
    of current prices vs entry prices, or None if inputs insufficient.

    We use equal-weight across positions with a valid entry price — this
    is a proxy. Once state.json carries explicit position sizes we will
    switch to those weights.
    """
    losses = []
    gains = []
    n = 0
    for p in positions:
        entry = p.get("entry_price")
        cur = p.get("current_price")
        try:
            entry = float(entry) if entry is not None else None
            cur = float(cur) if cur is not None else None
        except (TypeError, ValueError):
            entry, cur = None, None
        if not entry or not cur or entry <= 0:
            continue
        r = cur / entry - 1.0
        n += 1
        if r < 0:
            losses.append(r)
        else:
            gains.append(r)
    if n == 0:
        return None
    # Weighted book return, equal-weight
    book_return = (sum(losses) + sum(gains)) / n
    # DD is expressed as a non-negative fraction. If the book is net up,
    # DD from cost-basis is 0. (A proper NAV series would give trailing-peak
    # DD which is stricter — see docstring for upgrade path.)
    return max(0.0, -book_return)


def state_for_dd(dd_fraction: Optional[float]) -> Dict[str, Any]:
    if dd_fraction is None:
        return {
            "state": "UNKNOWN",
            "risk_budget_multiplier": 0.50,  # halve risk when blind
            "dd_pct": None,
            "note": "Insufficient data to compute DD — running at 50% budget.",
        }
    dd = float(dd_fraction)
    if dd <= GREEN_MAX:
        s = "GREEN"
    elif dd <= YELLOW_MAX:
        s = "YELLOW"
    elif dd <= ORANGE_MAX:
        s = "ORANGE"
    else:
        s = "RED"
    return {
        "state": s,
        "risk_budget_multiplier": BUDGET[s],
        "dd_pct": dd,
        "note": {
            "GREEN": "Full risk budget; normal operations.",
            "YELLOW": "No new non-core adds; tactical trims permitted.",
            "ORANGE": "Trim satellite sleeve; core untouched; raise cash.",
            "RED": "FREEZE all buys; review every position for thesis. Kernel I1 likely tripped.",
        }[s],
    }


def evaluate(positions: Iterable[Dict[str, Any]], history_pct: Optional[float] = None) -> Dict[str, Any]:
    positions = list(positions)
    dd = history_pct if history_pct is not None else cost_basis_dd(positions)
    out = state_for_dd(dd)
    out["source"] = "history_pct" if history_pct is not None else "cost_basis_proxy"
    out["position_count"] = len(positions)
    out["headline"] = f"Drawdown Guardian: {out['state']} · DD {_pct(out.get('dd_pct'))} · risk budget ×{out['risk_budget_multiplier']:.2f}"
    return out


if __name__ == "__main__":
    demo = [
        {"ticker": "A", "entry_price": 100, "current_price": 92},
        {"ticker": "B", "entry_price": 50, "current_price": 47},
        {"ticker": "C", "entry_price": 20, "current_price": 22},
    ]
    print(evaluate(demo))
