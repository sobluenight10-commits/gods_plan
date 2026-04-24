"""
STOP ENGINE  —  OLYMPUS-SENTINEL Layer 3, Ring 2.

One per-position "exit plan" computed every daily run. Designed to kill two
specific failure modes we learned in OLYMPUS:

    HOPE-HOLD TRAP   — position keeps bleeding because no hard stop exists.
    THESIS-DRIFT     — the exit price drifts DOWN with the market price
                       ("it's still a good story at $45... at $30... at $20").

Each position gets THREE stop candidates; we publish the TIGHTEST one.

    (1) ATR stop          entry - K_ATR * ATR(14)            volatility-aware
    (2) Hard % stop       entry * (1 - HARD_PCT)             tail-risk floor
    (3) Thesis stop       explicit price where thesis dies   user-supplied

For cores (do-not-sell-on-profit), the stop is only a THESIS-DEATH guard —
we raise it only if a thesis_price is provided and ignore the ATR and hard
floors (which are satellite defaults). This preserves the Buffett-hold while
still protecting against catastrophic thesis breaks.

Public:
    compute_stop(ticker, entry_price, current_price, is_core=False,
                 thesis_price=None) -> {
        "stop_price": 48.20,
        "distance_pct": -7.3,        # from current price
        "rule_fired": "ATR",         # or HARD or THESIS
        "atr14_pct": 0.028,
        "hard_floor_pct": 0.18,
        "notes": "ATR×2.0 stop below current — trailing allowed once +15%",
        "kind": "trailing|hard|thesis",
    }
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

try:
    import yfinance as yf
except Exception:
    yf = None


K_ATR = 2.0
HARD_PCT_SATELLITE = 0.18       # 18% below entry = absolute floor
HARD_PCT_CORE = 0.35            # core gets much more rope
TRAIL_ACTIVATE = 0.15           # after +15% start trailing from new high


def _atr(hist, period: int = 14) -> Optional[float]:
    try:
        high = hist["High"].to_numpy(dtype=float)
        low = hist["Low"].to_numpy(dtype=float)
        close = hist["Close"].to_numpy(dtype=float)
    except Exception:
        return None
    if len(close) < period + 2:
        return None
    prev = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    atr = float(np.mean(tr[-period:]))
    return atr


def _recent_high(hist, window: int = 60) -> Optional[float]:
    try:
        close = hist["Close"].to_numpy(dtype=float)
    except Exception:
        return None
    if len(close) == 0:
        return None
    return float(np.max(close[-min(window, len(close)):]))


def compute_stop(
    ticker: str,
    entry_price: Optional[float],
    current_price: Optional[float],
    is_core: bool = False,
    thesis_price: Optional[float] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ticker": ticker,
        "stop_price": None,
        "distance_pct": None,
        "rule_fired": None,
        "atr14_pct": None,
        "hard_floor_pct": HARD_PCT_CORE if is_core else HARD_PCT_SATELLITE,
        "kind": "none",
        "notes": "",
    }
    try:
        entry = float(entry_price) if entry_price else None
        cur = float(current_price) if current_price else None
    except (TypeError, ValueError):
        entry, cur = None, None
    if not entry or not cur or entry <= 0:
        out["notes"] = "entry/current missing — cannot size a stop"
        return out

    hist = None
    atr_val = None
    if yf is not None:
        try:
            hist = yf.Ticker(ticker).history(period="6mo", interval="1d", auto_adjust=True)
            atr_val = _atr(hist, 14) if hist is not None else None
        except Exception:
            hist = None

    candidates = []

    # Hard % floor
    hard_pct = HARD_PCT_CORE if is_core else HARD_PCT_SATELLITE
    hard_stop = entry * (1.0 - hard_pct)
    candidates.append(("HARD", hard_stop, "hard", f"{hard_pct*100:.0f}% below entry"))

    # ATR stop (below current / or trailing high once profitable)
    atr_pct = None
    if atr_val and cur > 0:
        atr_pct = atr_val / cur
        out["atr14_pct"] = round(float(atr_pct), 4)
        # If position is up enough, trail from recent high; else from current
        up = cur / entry - 1.0
        base = _recent_high(hist, 60) if up >= TRAIL_ACTIVATE else cur
        if base is None:
            base = cur
        atr_stop = base - K_ATR * atr_val
        kind = "trailing" if up >= TRAIL_ACTIVATE else "initial"
        candidates.append((
            "ATR",
            atr_stop,
            kind,
            f"{K_ATR:.1f}×ATR below {'60d high' if kind=='trailing' else 'spot'}",
        ))

    # Thesis-death stop (if given)
    if thesis_price:
        try:
            tp = float(thesis_price)
            if tp > 0:
                candidates.append(("THESIS", tp, "thesis",
                                   "User-declared thesis-invalidation price"))
        except Exception:
            pass

    # Core: only honour THESIS + HARD(core). Never the ATR stop — we hold winners.
    if is_core:
        candidates = [c for c in candidates if c[0] in ("HARD", "THESIS")]

    # Pick the TIGHTEST stop that is still ≤ current (otherwise it's already triggered)
    usable = [c for c in candidates if c[1] is not None]
    if not usable:
        out["notes"] = "no usable stop candidate"
        return out

    # Take the MAX (highest) valid stop below current price
    valid = [c for c in usable if c[1] < cur]
    if not valid:
        # All candidates are above current -> already triggered
        rule, stop, kind, note = max(usable, key=lambda x: x[1])
        out["stop_price"] = round(float(stop), 4)
        out["rule_fired"] = rule
        out["kind"] = "triggered"
        out["distance_pct"] = round((stop / cur - 1.0) * 100, 2)
        out["notes"] = f"STOP ALREADY TRIGGERED by {rule}: {note}"
        return out

    rule, stop, kind, note = max(valid, key=lambda x: x[1])
    out["stop_price"] = round(float(stop), 4)
    out["rule_fired"] = rule
    out["kind"] = kind
    out["distance_pct"] = round((stop / cur - 1.0) * 100, 2)
    out["notes"] = note
    return out


if __name__ == "__main__":
    import json, sys
    t = sys.argv[1] if len(sys.argv) > 1 else "KTOS"
    entry = float(sys.argv[2]) if len(sys.argv) > 2 else 85.50
    cur = float(sys.argv[3]) if len(sys.argv) > 3 else 63.0
    print(json.dumps(compute_stop(t, entry, cur, is_core=False, thesis_price=55.0), indent=2))
