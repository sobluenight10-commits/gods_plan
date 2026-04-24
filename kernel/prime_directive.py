"""
PRIME DIRECTIVE KERNEL  —  OLYMPUS-SENTINEL Layer 0.

Four immutable invariants. Every agent that wants to act must pass
its proposal through `evaluate_portfolio()`. On any breach the
kernel sets `freeze_all=True` in the payload; the dashboard already
reads this flag.

    I1. PORTFOLIO_DD_HARD_CAP  = 15%   # trailing DD → full freeze
    I2. SINGLE_POSITION_CAP    = 20%   # NAV cap per ticker
    I3. SECTOR_CAP             = 35%   # NAV cap per sector
    I4. CASH_FLOOR             = 5%    # never fully invested

Why these four survive every regime (1929, 1973, 2000, 2008, 2020, 2022):
  - DD cap stops doom loops (loss → desperation size-up → bigger loss).
  - Position cap stops single-thesis ruin.
  - Sector cap stops correlated-bet ruin disguised as "diversification".
  - Cash floor keeps State-2 strike ammo permanently available.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

# Hard caps — do not edit without GOD approval + journal entry.
PORTFOLIO_DD_HARD_CAP = 0.15
SINGLE_POSITION_CAP = 0.20
SECTOR_CAP = 0.35
CASH_FLOOR = 0.05


def _pct(x: float) -> str:
    return f"{x*100:.1f}%"


def invariants() -> Dict[str, float]:
    return {
        "I1_portfolio_dd_hard_cap": PORTFOLIO_DD_HARD_CAP,
        "I2_single_position_cap": SINGLE_POSITION_CAP,
        "I3_sector_cap": SECTOR_CAP,
        "I4_cash_floor": CASH_FLOOR,
    }


def evaluate_portfolio(
    positions: Iterable[Dict[str, Any]],
    cash_pct: Optional[float],
    drawdown_pct: Optional[float],
    suppress_structural_breaches: bool = False,
) -> Dict[str, Any]:
    """
    Evaluate current book against the four invariants.

    positions: iterable of {ticker, sector, weight_pct (0..1)}; weights are
               expressed as a fraction of NAV (0..1). If weight_pct not
               provided, we treat positions as equal-weighted.
    cash_pct:  dry powder as fraction of NAV (0..1), or None if unknown.
    drawdown_pct: current portfolio DD from trailing peak as positive
               fraction (e.g. 0.08 = down 8%). None if unknown.

    Returns dict:
      {
        invariants: {...},
        breaches: ["I1", "I3:Intelligence/AI", ...],
        freeze_all: bool,
        reasons: [human-readable strings],
        sector_weights: {sector: weight},
      }
    """
    positions = list(positions)
    breaches: List[str] = []
    reasons: List[str] = []

    # Normalize weights
    weights = []
    if positions:
        explicit = [p for p in positions if p.get("weight_pct") is not None]
        if explicit and len(explicit) == len(positions):
            weights = [float(p["weight_pct"]) for p in positions]
        else:
            eq = 1.0 / max(1, len(positions))
            weights = [eq] * len(positions)

    # I1: drawdown cap
    if drawdown_pct is not None and drawdown_pct >= PORTFOLIO_DD_HARD_CAP:
        breaches.append("I1")
        reasons.append(
            f"I1 BREACH: portfolio DD {_pct(drawdown_pct)} ≥ cap {_pct(PORTFOLIO_DD_HARD_CAP)} — freeze all adds."
        )

    # I2: per-position cap
    if not suppress_structural_breaches:
        for p, w in zip(positions, weights):
            if w > SINGLE_POSITION_CAP + 1e-6:
                tk = p.get("ticker", "?")
                breaches.append(f"I2:{tk}")
                reasons.append(
                    f"I2 BREACH: {tk} weight {_pct(w)} > cap {_pct(SINGLE_POSITION_CAP)} — trim toward cap."
                )

    # I3: per-sector cap
    sec_weights: Dict[str, float] = {}
    for p, w in zip(positions, weights):
        s = p.get("sector") or "UNCLASSIFIED"
        sec_weights[s] = sec_weights.get(s, 0.0) + w
    if not suppress_structural_breaches:
        for s, w in sec_weights.items():
            if w > SECTOR_CAP + 1e-6:
                breaches.append(f"I3:{s}")
                reasons.append(
                    f"I3 BREACH: sector {s} {_pct(w)} > cap {_pct(SECTOR_CAP)} — no new adds in sector."
                )

    # I4: cash floor
    if cash_pct is not None and cash_pct < CASH_FLOOR:
        breaches.append("I4")
        reasons.append(
            f"I4 BREACH: cash {_pct(cash_pct)} < floor {_pct(CASH_FLOOR)} — raise dry powder before new risk."
        )

    freeze_all = any(b == "I1" or b == "I4" for b in breaches)

    return {
        "invariants": invariants(),
        "breaches": breaches,
        "freeze_all": freeze_all,
        "reasons": reasons,
        "sector_weights": sec_weights,
        "cash_pct": cash_pct,
        "drawdown_pct": drawdown_pct,
    }


def veto_new_position(
    ticker: str,
    sector: str,
    proposed_weight_pct: float,
    current_portfolio: Iterable[Dict[str, Any]],
    cash_pct: Optional[float],
    drawdown_pct: Optional[float],
) -> Dict[str, Any]:
    """
    Returns {approved: bool, max_allowed_weight_pct: float, reasons: [...]}.

    Used by the sizer to clamp proposals before they hit active_actions.
    """
    state = evaluate_portfolio(current_portfolio, cash_pct, drawdown_pct)
    reasons: List[str] = []

    if state["freeze_all"]:
        return {
            "approved": False,
            "max_allowed_weight_pct": 0.0,
            "reasons": ["kernel.freeze_all"] + list(state["reasons"]),
        }

    max_by_position = SINGLE_POSITION_CAP
    existing = 0.0
    for p in current_portfolio:
        if p.get("ticker") == ticker and p.get("weight_pct") is not None:
            existing = float(p["weight_pct"])

    sec_weight = float(state.get("sector_weights", {}).get(sector, 0.0))
    max_by_sector = max(0.0, SECTOR_CAP - sec_weight)

    cap = min(max_by_position - existing, max_by_sector)
    if cash_pct is not None:
        cap = min(cap, max(0.0, cash_pct - CASH_FLOOR))

    allowed = max(0.0, min(float(proposed_weight_pct), cap))
    if allowed + 1e-9 < proposed_weight_pct:
        reasons.append(
            f"kernel clamp: proposed {_pct(proposed_weight_pct)} → allowed {_pct(allowed)} "
            f"(position headroom {_pct(max(0.0, max_by_position - existing))}, "
            f"sector headroom {_pct(max_by_sector)}, "
            f"cash headroom {_pct(max(0.0, (cash_pct or 0.0) - CASH_FLOOR))})"
        )

    return {
        "approved": allowed > 0,
        "max_allowed_weight_pct": allowed,
        "reasons": reasons,
    }


if __name__ == "__main__":
    demo = [
        {"ticker": "PLTR", "sector": "Intelligence/AI", "weight_pct": 0.22},
        {"ticker": "TSM", "sector": "Intelligence/AI", "weight_pct": 0.18},
        {"ticker": "UEC", "sector": "Energy/Uranium", "weight_pct": 0.10},
    ]
    print(evaluate_portfolio(demo, cash_pct=0.03, drawdown_pct=0.17))
