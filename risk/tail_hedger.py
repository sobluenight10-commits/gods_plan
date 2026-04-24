"""
TAIL HEDGER  —  OLYMPUS-SENTINEL Layer 3, Ring 6.

Detects the conditions under which the next drawdown is likely to be
"fat-tailed" (i.e. a -15%+ S&P move within 30 days) and recommends an
explicit *hedge posture*.

We refuse to touch options money automatically. What we DO is:
    (a) RAISE THE CASH FLOOR (5% → 10% → 15%)
    (b) ARM a watchlist of protective instruments (SPY puts 10% OTM 45–60 DTE,
        or 1x-vol SQQQ cash-in-lieu) for a human trigger.
    (c) Mark the portfolio posture on the dashboard so no "add at dip"
        signal can slip through when the tape is about to break.

Signals used (pure yfinance, no data subscriptions):
    VIX_TS    = VIX / VIX3M                 inverted (>1.00)  = stress
    HY_OAS*   = HYG 20d log-return          sharp negative   = credit strain
    BREADTH   = SPY trend vs 200DMA,
                RSP (equal-weight) / SPY    ratio falling    = mega-cap only
    PUTCALL   = RV(QQQ)-RV(SPY) gap         QQQ vol >> SPY   = tech fragility

Levels:
    DEFCON 5 (calm)     nothing to do
    DEFCON 4            watch — no action
    DEFCON 3            cash floor → 7% · arm watchlist
    DEFCON 2            cash floor → 10% · stage SPY puts · freeze satellite adds
    DEFCON 1 (crisis)   cash floor → 15% · execute puts · core-only · tighten stops

Output: self-describing dict.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

try:
    import yfinance as yf
except Exception:
    yf = None


def _series(ticker: str, period: str = "3mo") -> Optional[np.ndarray]:
    if yf is None:
        return None
    try:
        h = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
    except Exception:
        return None
    if h is None or len(h) < 10:
        return None
    return h["Close"].dropna().to_numpy(dtype=float)


def _pct_return(arr: np.ndarray, days: int) -> Optional[float]:
    if arr is None or len(arr) <= days:
        return None
    return float(arr[-1] / arr[-1 - days] - 1.0)


def _vix_term_structure() -> Optional[float]:
    vix = _series("^VIX", "3mo")
    v3m = _series("^VIX3M", "3mo")
    if vix is None or v3m is None or len(vix) == 0 or len(v3m) == 0:
        return None
    return float(vix[-1] / v3m[-1])


def _hyg_stress() -> Optional[float]:
    arr = _series("HYG", "3mo")
    return _pct_return(arr, 20)


def _breadth_score() -> Optional[Dict[str, Any]]:
    spy = _series("SPY", "1y")
    rsp = _series("RSP", "1y")
    if spy is None or rsp is None:
        return None
    # SPY vs 200d MA
    if len(spy) < 200:
        return None
    ma200 = float(np.mean(spy[-200:]))
    spy_vs_ma = float(spy[-1] / ma200 - 1.0)
    # RSP/SPY ratio: 20d return
    ratio = rsp / spy
    ratio_20d = float(ratio[-1] / ratio[-21] - 1.0) if len(ratio) > 21 else 0.0
    return {
        "spy_vs_200dma_pct": round(spy_vs_ma * 100, 2),
        "equal_vs_cap_20d_pct": round(ratio_20d * 100, 2),
    }


def _qqq_spy_vol_gap() -> Optional[float]:
    qqq = _series("QQQ", "2mo")
    spy = _series("SPY", "2mo")
    if qqq is None or spy is None or len(qqq) < 25 or len(spy) < 25:
        return None
    r_q = np.diff(np.log(qqq + 1e-12))[-20:]
    r_s = np.diff(np.log(spy + 1e-12))[-20:]
    v_q = float(np.std(r_q) * np.sqrt(252))
    v_s = float(np.std(r_s) * np.sqrt(252))
    return round(v_q - v_s, 4)


def evaluate() -> Dict[str, Any]:
    vix_ts = _vix_term_structure()
    hyg_20d = _hyg_stress()
    breadth = _breadth_score()
    vol_gap = _qqq_spy_vol_gap()

    signals: List[str] = []
    score = 0

    if vix_ts is not None:
        if vix_ts >= 1.05:
            signals.append(f"VIX term-structure INVERTED {vix_ts:.2f} (stress)")
            score += 2
        elif vix_ts >= 1.00:
            signals.append(f"VIX/VIX3M ≈ 1.00 ({vix_ts:.2f}) — flattening")
            score += 1
        elif vix_ts <= 0.85:
            signals.append(f"VIX contango steep {vix_ts:.2f} — calm")

    if hyg_20d is not None:
        if hyg_20d <= -0.04:
            signals.append(f"HYG 20d {hyg_20d*100:+.1f}% — credit cracking")
            score += 2
        elif hyg_20d <= -0.02:
            signals.append(f"HYG 20d {hyg_20d*100:+.1f}% — credit softening")
            score += 1

    if breadth is not None:
        if breadth["spy_vs_200dma_pct"] <= -3.0:
            signals.append(f"SPY {breadth['spy_vs_200dma_pct']:+.1f}% vs 200DMA")
            score += 2
        elif breadth["spy_vs_200dma_pct"] <= 0.0:
            signals.append(f"SPY {breadth['spy_vs_200dma_pct']:+.1f}% below 200DMA")
            score += 1
        if breadth["equal_vs_cap_20d_pct"] <= -2.0:
            signals.append(f"Equal-weight trailing cap-weight {breadth['equal_vs_cap_20d_pct']:+.1f}% (narrow leadership)")
            score += 1

    if vol_gap is not None and vol_gap >= 0.05:
        signals.append(f"QQQ − SPY vol gap +{vol_gap*100:.1f}% (tech fragility)")
        score += 1

    # Map composite score → DEFCON
    if score >= 6:
        defcon = 1
    elif score >= 4:
        defcon = 2
    elif score >= 2:
        defcon = 3
    elif score >= 1:
        defcon = 4
    else:
        defcon = 5

    posture = {
        1: {"label": "CRISIS", "cash_floor_pct": 15, "hedge": "EXECUTE SPY puts 10%OTM 45–60DTE · core-only · tighten all stops"},
        2: {"label": "HIGH",   "cash_floor_pct": 10, "hedge": "STAGE SPY puts · freeze satellite adds · raise cash"},
        3: {"label": "ELEVATED","cash_floor_pct": 7, "hedge": "Arm hedge watchlist · no new satellite entries"},
        4: {"label": "WATCH",  "cash_floor_pct": 5,  "hedge": "Monitor — no hedge action"},
        5: {"label": "CALM",   "cash_floor_pct": 5,  "hedge": "No hedge — standard operation"},
    }[defcon]

    return {
        "defcon": defcon,
        "posture_label": posture["label"],
        "cash_floor_override_pct": posture["cash_floor_pct"],
        "hedge_instruction": posture["hedge"],
        "signals": signals or ["No stress signals active"],
        "score": score,
        "vix_ts": None if vix_ts is None else round(vix_ts, 3),
        "hyg_20d_pct": None if hyg_20d is None else round(hyg_20d * 100, 2),
        "breadth": breadth,
        "vol_gap_qqq_minus_spy": vol_gap,
        "freeze_satellite_adds": defcon <= 2,
        "block_new_cores": defcon <= 1,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(evaluate(), indent=2))
