"""
POINT B SCANNER — Soros gap formalised. The "buy the dip" execution layer.

User's doctrine:
    "If A is unclear, B is the practical fallback. -15% from previous peak.
     Ideally rebound — my experience says stocks meeting the major premise
     normally rebound when price pulls back -15 to -20%."

Adopted definition (per Minerva's recommendation):

    high_20d        = highest CLOSE in trailing 20 trading days
    breakout_base   = lowest CLOSE in trailing 60 trading days
                      (proxy for the most recent consolidation low)
    dist_pct        = (close − high_20d) / high_20d × 100

    States (priority — first match wins):

    THESIS_REVIEW       dist ≤ −15% AND close ≤ breakout_base × 1.02
                        ↳  base broken, this is NOT a B entry, this is
                           a thesis event requiring written justification.
    POINT_B_EXECUTE     dist ≤ −15% AND close > breakout_base × 1.02
                        ↳  textbook -15% pullback held above the base.
    POINT_B_WARNING     −15% < dist ≤ −10%
                        ↳  approaching the strike zone, get ready.
    RIDING              −10% < dist ≤ 0
                        ↳  trend intact, no action.
    ABOVE_HIGH          dist > 0
                        ↳  fresh 20d high, A-window already closed.

    Two-tier alerts (heads-up.py reads this):
        Tier B1 (warning) → -10% level
        Tier B2 (execute) → -15% level
        Tier B3 (review)  → base broken

Output:  data/point_b_scan.json
    {
      schema_version, generated_utc,
      tickers: {
        TICKER: {
          last_close, high_20d, dist_pct,
          breakout_base, base_intact (bool),
          state, soros_gap_pct (= -dist_pct, positive = how far below),
          buy_zone_b: {warning: -10% level, execute: -15% level},
          stop_below_base: float (= breakout_base × 0.97 — thesis-review trigger)
        }
      },
      shortlist_execute, shortlist_warning, shortlist_review
    }
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

OUT = os.path.join(BASE, "data", "point_b_scan.json")
WEBROOT_OUT = "/var/www/html/point_b_scan.json"

WARN_PCT = -10.0
EXEC_PCT = -15.0
BASE_BROKEN_BUFFER = 0.02   # within 2% above base counts as broken
WINDOW_HIGH = 20
WINDOW_BASE = 60


def _scan_one(ticker: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ticker": ticker,
        "last_close": None, "high_20d": None, "high_20d_date": None,
        "breakout_base": None, "base_intact": None,
        "dist_pct": None, "soros_gap_pct": None,
        "state": "UNKNOWN", "error": None,
    }
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="6mo", auto_adjust=True)
    except Exception as exc:
        out["error"] = f"yfinance: {exc}"
        out["state"] = "ERROR"
        return out
    if h is None or h.empty or "Close" not in h.columns:
        out["error"] = "no_history"
        out["state"] = "ERROR"
        return out

    close = h["Close"].astype(float)
    n = len(close)
    if n < 25:
        out["error"] = f"insufficient_history len={n}"
        out["state"] = "ERROR"
        return out

    last = float(close.iloc[-1])
    win_h = min(WINDOW_HIGH, n - 1)
    win_b = min(WINDOW_BASE, n - 1)
    high_window = close.tail(win_h)
    base_window = close.tail(win_b)
    high_20d = float(high_window.max())
    high_20d_idx = high_window.idxmax()
    breakout_base = float(base_window.min())
    dist_pct = (last - high_20d) / high_20d * 100 if high_20d else 0.0
    base_intact = bool(last > breakout_base * (1 + BASE_BROKEN_BUFFER))

    if dist_pct <= EXEC_PCT and not base_intact:
        state = "THESIS_REVIEW"
    elif dist_pct <= EXEC_PCT and base_intact:
        state = "POINT_B_EXECUTE"
    elif WARN_PCT >= dist_pct > EXEC_PCT:
        state = "POINT_B_WARNING"
    elif 0 >= dist_pct > WARN_PCT:
        state = "RIDING"
    else:
        state = "ABOVE_HIGH"

    out.update({
        "last_close": round(last, 4),
        "high_20d": round(high_20d, 4),
        "high_20d_date": str(high_20d_idx)[:10] if high_20d_idx is not None else None,
        "breakout_base": round(breakout_base, 4),
        "base_intact": base_intact,
        "dist_pct": round(dist_pct, 2),
        "soros_gap_pct": round(-dist_pct, 2) if dist_pct < 0 else 0.0,
        "state": state,
        "buy_zone_b": {
            "warning_at": round(high_20d * (1 + WARN_PCT / 100), 4),
            "execute_at": round(high_20d * (1 + EXEC_PCT / 100), 4),
        },
        "stop_below_base": round(breakout_base * 0.97, 4),
    })
    return out


def run(tickers: Optional[List[str]] = None) -> Dict[str, Any]:
    if tickers is None:
        try:
            from fetch_data import UNIVERSE
            tickers = list(UNIVERSE.keys())
        except Exception:
            tickers = []

    per_ticker: Dict[str, Any] = {}
    execute: List[Dict[str, Any]] = []
    warning: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    riding: List[Dict[str, Any]] = []
    above: List[Dict[str, Any]] = []

    for tk in tickers:
        row = _scan_one(tk)
        per_ticker[tk] = row
        st = row.get("state")
        if st == "POINT_B_EXECUTE":
            execute.append(row)
        elif st == "POINT_B_WARNING":
            warning.append(row)
        elif st == "THESIS_REVIEW":
            review.append(row)
        elif st == "RIDING":
            riding.append(row)
        elif st == "ABOVE_HIGH":
            above.append(row)

    # Sort by depth of pullback (most extreme first)
    execute.sort(key=lambda r: r.get("dist_pct") or 0)
    warning.sort(key=lambda r: r.get("dist_pct") or 0)
    review.sort(key=lambda r: r.get("dist_pct") or 0)

    out = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tickers": per_ticker,
        "shortlist_execute": execute,
        "shortlist_warning": warning,
        "shortlist_review": review,
        "n_execute": len(execute),
        "n_warning": len(warning),
        "n_review": len(review),
        "n_riding": len(riding),
        "n_above": len(above),
        "thresholds": {
            "warning_pct": WARN_PCT,
            "execute_pct": EXEC_PCT,
            "base_broken_buffer_pct": BASE_BROKEN_BUFFER * 100,
            "window_high_days": WINDOW_HIGH,
            "window_base_days": WINDOW_BASE,
        },
        "doctrine": (
            "B = -15% from highest close in trailing 20 trading days, AS LONG AS "
            "that level holds above the breakout base (lowest close in trailing 60 days). "
            "If -15% breaks below the base it is THESIS_REVIEW, not a B entry. "
            "Two-tier alerts: -10% (warning, get ready) → -15% (execute, fire orders)."
        ),
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
        print(f"[point_b] webroot mirror failed: {exc}")


if __name__ == "__main__":
    out = run()
    print(json.dumps({k: v for k, v in out.items() if k != "tickers"}, indent=2, ensure_ascii=False))
