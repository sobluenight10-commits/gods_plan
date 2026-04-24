"""
POSITION SIZER  —  OLYMPUS-SENTINEL Layer 3, Ring 1.

Turns a forecast distribution + book context into the smallest set
of numbers that actually matter for a trade decision:

    ev_pct       expected return over horizon (base case / GEM ev)
    es5_pct      expected shortfall  — left-tail return (GEM worst)
    p_win        probability of positive return over horizon
    kelly_frac   fractional Kelly (safety-scaled)
    size_pct_nav suggested size as % of NAV (clamped by kernel)
    conviction   0..10 blended score
    stop_price   thesis/ATR-aware stop
    vetoes       list of reasons position should NOT be opened/added

Design choices:
  - Fractional Kelly (×0.25) — full Kelly is for gamblers with no drawdown aversion.
  - CVaR penalty — Kelly gets shrunk further if es5 is worse than −25%.
  - Loss aversion λ = 1.5 — losses count 1.5× in the utility function.
  - Ambiguity shrinkage — if p_win uncertainty is high (confidence < 0.4),
    we halve the size. This is the "disagreement → shrink" rule.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

SAFETY_FRACTION = 0.25      # fractional Kelly
LOSS_AVERSION = 1.5         # losses count this much more than gains
CVAR_PENALTY_THRESHOLD = 0.25   # es5 worse than this starts penalizing size
CVAR_PENALTY_MAX = 0.50         # es5 this bad or worse → size × 0.5

# Priors when GEM has no line for this ticker
DEFAULT_EV_PCT = 0.04
DEFAULT_ES5_PCT = -0.20


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _prob_win_from_gem(upside_pct: float, worst_drop_pct: float, bull_gain_pct: float) -> float:
    """
    GEM gives ev (≈ mean), worst (≈ 5th pctile), bull (≈ 95th pctile).
    Approximate σ ≈ (bull − worst) / (2·1.645) from normal-tail spacing.
    Then p(price > entry) assumes the distribution is centered at upside_pct.
    """
    try:
        mu = float(upside_pct) / 100.0
        worst = float(worst_drop_pct) / 100.0
        bull = float(bull_gain_pct) / 100.0
    except (TypeError, ValueError):
        return 0.5
    spread = max(1e-6, (bull - worst) / (2.0 * 1.645))
    # Probability that terminal return > 0 ≈ Φ(mu / σ)
    z = mu / spread if spread > 0 else 0.0
    # Approximate Φ with a smooth sigmoid to avoid scipy dependency.
    return _clamp(0.5 + 0.5 * math.tanh(0.7978845608 * z), 0.02, 0.98)


def _cvar_penalty(es5_pct: float) -> float:
    """Multiplier 0.5..1.0 — worse ES → smaller size."""
    es = abs(es5_pct)
    if es <= CVAR_PENALTY_THRESHOLD:
        return 1.0
    if es >= CVAR_PENALTY_MAX:
        return 0.5
    # Linear taper from 1.0 → 0.5
    span = CVAR_PENALTY_MAX - CVAR_PENALTY_THRESHOLD
    return 1.0 - 0.5 * ((es - CVAR_PENALTY_THRESHOLD) / span)


def _kelly(p_win: float, avg_gain: float, avg_loss: float) -> float:
    """
    Fractional Kelly with loss aversion.
      f* = (p·b − q) / b ,  b = avg_gain/avg_loss, q = 1−p
    Loss aversion substitutes avg_loss × λ in the denominator-equivalent.
    """
    g = max(1e-4, float(avg_gain))
    l = max(1e-4, float(avg_loss)) * LOSS_AVERSION
    b = g / l
    q = 1.0 - p_win
    f = (p_win * b - q) / b if b > 0 else -1.0
    return max(0.0, f) * SAFETY_FRACTION


def size_position(
    ticker: str,
    verb: str,
    gem_row: Optional[Dict[str, Any]],
    portfolio_row: Optional[Dict[str, Any]],
    ops: Optional[float],
    thesis: str,
    liq_freeze: bool,
    dd_state: Dict[str, Any],
    kernel_headroom_pct: float,
) -> Dict[str, Any]:
    """
    Produce the sizer payload for a single ticker.
    Does NOT decide the verb — only enriches it with size/ev/es/vetoes.
    """
    vetoes: List[str] = []

    # --- Forecast numbers --------------------------------------------------
    proj_1y = (gem_row or {}).get("projections", {}).get("1y") or {}
    ev_pct = proj_1y.get("upside_pct")
    worst_pct = proj_1y.get("worst_drop_pct")
    bull_pct = proj_1y.get("bull_gain_pct")

    if ev_pct is None:
        ev_frac = DEFAULT_EV_PCT
    else:
        ev_frac = float(ev_pct) / 100.0
    if worst_pct is None:
        es5_frac = DEFAULT_ES5_PCT
    else:
        es5_frac = float(worst_pct) / 100.0

    # p_win
    if ev_pct is not None and worst_pct is not None and bull_pct is not None:
        p_win = _prob_win_from_gem(ev_pct, worst_pct, bull_pct)
    else:
        p_win = _clamp(0.5 + ev_frac * 2.0, 0.2, 0.85)

    # Expected gain / loss magnitudes
    avg_gain = max(0.02, (bull_pct or 30.0) / 100.0)
    avg_loss = max(0.05, abs(worst_pct or -20.0) / 100.0)

    # --- Kelly + CVaR penalty ---------------------------------------------
    kelly_f = _kelly(p_win, avg_gain, avg_loss)
    kelly_f *= _cvar_penalty(es5_frac)

    # --- Conviction blend --------------------------------------------------
    god = float((gem_row or {}).get("god_score") or (portfolio_row or {}).get("god_score") or 70.0)
    god_n = _clamp(god / 100.0, 0.3, 1.0)
    thesis_n = {"intact": 1.0, "wounded": 0.6, "drifting": 0.5, "dead": 0.0}.get(thesis, 0.7)
    ops_n = 1.0
    if ops is not None:
        try:
            o = float(ops)
            if o >= 180:
                ops_n = 0.3
            elif o >= 120:
                ops_n = 0.7
            elif o < 80:
                ops_n = 1.1  # slight bonus for OPS-cheap
            ops_n = _clamp(ops_n, 0.0, 1.1)
        except (TypeError, ValueError):
            pass

    conv_raw = 10.0 * god_n * thesis_n * min(ops_n, 1.0)
    conviction = round(_clamp(conv_raw, 0.0, 10.0), 1)

    # Disagreement shrinkage (proxy: low conviction → shrink)
    if conviction < 5:
        kelly_f *= 0.5

    # --- Vetoes ------------------------------------------------------------
    if liq_freeze:
        vetoes.append("liquidity_freeze")
    if dd_state.get("state") == "RED":
        vetoes.append("dd_red")
    if dd_state.get("state") == "ORANGE" and verb in ("BUY", "ADD"):
        vetoes.append("dd_orange_no_satellite")
    if thesis == "dead":
        vetoes.append("thesis_dead")
    if ops is not None:
        try:
            if float(ops) >= 180:
                vetoes.append("ops_extreme")
        except (TypeError, ValueError):
            pass
    if p_win < 0.45 and verb in ("BUY", "ADD"):
        vetoes.append("p_win_low")

    # --- Size clamp -------------------------------------------------------
    dd_mult = float(dd_state.get("risk_budget_multiplier", 1.0))
    size_unclamped = kelly_f * dd_mult
    size = _clamp(size_unclamped, 0.0, kernel_headroom_pct)
    if vetoes:
        size = 0.0

    # --- Stop price -------------------------------------------------------
    current = (gem_row or {}).get("current_price") or (portfolio_row or {}).get("current_price")
    entry = (gem_row or {}).get("entry_price") or (portfolio_row or {}).get("entry_price")
    vol_1y = (portfolio_row or {}).get("vol_1y_pct") or 40.0
    stop_price = None
    if current:
        try:
            cur_f = float(current)
            vol_stop = cur_f * (1.0 - 2.0 * float(vol_1y) / 100.0 * 0.25)  # 2σ × 0.25 (quarter scaling)
            entry_stop = float(entry) * 0.85 if entry else None
            candidates = [vol_stop]
            if entry_stop:
                candidates.append(entry_stop)
            # Thesis invalidation stops (from state.json kill_criteria) can be plugged in here.
            stop_price = round(max(candidates[-1], min(candidates)), 2)
        except (TypeError, ValueError):
            stop_price = None

    return {
        "ev_pct": round(ev_frac * 100.0, 2),
        "es5_pct": round(es5_frac * 100.0, 2),
        "p_win": round(p_win, 3),
        "kelly_frac": round(kelly_f, 4),
        "size_pct_nav": round(size * 100.0, 2),
        "conviction": conviction,
        "stop_price": stop_price,
        "vetoes": vetoes,
        "dd_state": dd_state.get("state"),
        "risk_budget_multiplier": dd_mult,
    }


if __name__ == "__main__":
    fake_gem = {
        "current_price": 123.38,
        "entry_price": 55.0,
        "god_score": 62,
        "projections": {
            "1y": {
                "upside_pct": 5.12,
                "worst_drop_pct": -44.83,
                "bull_gain_pct": 98.81,
                "ev": 129.69,
            }
        },
    }
    print(size_position(
        "ARKQ", "HOLD", fake_gem,
        portfolio_row={"vol_1y_pct": 35},
        ops=95, thesis="intact", liq_freeze=False,
        dd_state={"state": "GREEN", "risk_budget_multiplier": 1.0},
        kernel_headroom_pct=0.10,
    ))
