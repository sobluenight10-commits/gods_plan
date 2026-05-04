"""
POINT A SCANNER — earliest reliable buy signal (macro-driven entry).

User's doctrine (May 4 2026):
    "A is the ideal point to buy. The earliest reliable signal that price
     is about to move BEFORE it moves. The challenge is defining it
     mechanically."

Adopted definition (3-of-3 = FIRED, 2-of-3 = WATCH):

    A1  LIQUIDITY REGIME EXPANDING
        Strike Radar state ∈ {STRIKE_PIVOT_EARLY, STRIKE_WINDOW_OPEN,
                              SELECTIVE_TAILWIND, DEPLOY_RIDING}
        OR (v_3d ≥ 0 AND v_7d ≥ 0)
        OR (accel_b_per_day2 > 0 AND v_3d ≥ 0)

    A2  FUNDING STRESS EASING
        Proxy stack — we don't have OFR FSI directly so we use:
        - VIX < 20  AND  VIX < VIX 5d ago  (volatility easing)
        - HYG drawdown from 60d high improving (credit fear easing)
        Either condition true counts as "easing".

    A3  PRICE BELOW 20-WEEK MA
        Stock close < 20W (≈ 100 trading days) simple moving average.
        This is the "price hasn't moved yet" guard. Once price crosses
        above the 20W MA, the A window has closed and we're in B-territory.

A is INDEPENDENT per ticker because A3 is per-stock. A1 + A2 are global.

Output:  data/point_a_scan.json
    {
      schema_version, generated_utc,
      a1_liquidity_expanding (bool, ev),
      a2_funding_easing (bool, ev),
      tickers: {
        TICKER: {
          a3_below_20w_ma (bool),
          last_close, ma_20w, dist_to_ma_pct,
          state: "FIRED" | "WATCH" | "INACTIVE",
          reasons: [...],
          conditions_met: 0..3
        }, ...
      },
      shortlist_fired: [tickers with state=FIRED, sorted by dist below MA],
      shortlist_watch: [tickers with state=WATCH]
    }
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

RADAR = os.path.join(BASE, "data", "strike_radar.json")
OUT = os.path.join(BASE, "data", "point_a_scan.json")
WEBROOT_OUT = "/var/www/html/point_a_scan.json"

LIQUIDITY_OK_STATES = {
    "STRIKE_PIVOT_EARLY", "STRIKE_WINDOW_OPEN",
    "SELECTIVE_TAILWIND", "DEPLOY_RIDING",
}


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _evaluate_a1(radar: Dict[str, Any]) -> Tuple[bool, str]:
    state = radar.get("state") or "UNKNOWN"
    v = radar.get("velocity_b_per_day") or {}
    v_3d = v.get("v_3d")
    v_7d = v.get("v_7d")
    accel = v.get("accel_b_per_day2")

    if state in LIQUIDITY_OK_STATES:
        return True, f"strike_radar.state={state}"
    if v_3d is not None and v_7d is not None and v_3d >= 0 and v_7d >= 0:
        return True, f"v_3d={v_3d} v_7d={v_7d} both ≥ 0"
    if accel is not None and v_3d is not None and accel > 0 and v_3d >= 0:
        return True, f"accel={accel} v_3d={v_3d}"
    return False, f"strike_radar.state={state} v_3d={v_3d} v_7d={v_7d}"


def _evaluate_a2() -> Tuple[bool, str, Dict[str, Any]]:
    """VIX easing OR HYG drawdown improving = funding stress easing."""
    try:
        import yfinance as yf
    except Exception:
        return False, "yfinance unavailable", {}

    detail: Dict[str, Any] = {}
    eases: List[str] = []

    # VIX
    try:
        h = yf.Ticker("^VIX").history(period="1mo", auto_adjust=False)
        if h is not None and not h.empty and "Close" in h.columns:
            vix_now = float(h["Close"].iloc[-1])
            vix_5d = float(h["Close"].iloc[-6]) if len(h) >= 6 else vix_now
            detail["vix_now"] = round(vix_now, 2)
            detail["vix_5d_ago"] = round(vix_5d, 2)
            detail["vix_5d_delta"] = round(vix_now - vix_5d, 2)
            if vix_now < 20 and vix_now < vix_5d:
                eases.append(f"VIX {vix_now:.1f} < 20 and falling")
    except Exception as exc:
        detail["vix_error"] = str(exc)

    # HYG drawdown vs 60d high
    try:
        h = yf.Ticker("HYG").history(period="3mo", auto_adjust=True)
        if h is not None and not h.empty and "Close" in h.columns:
            close = h["Close"].astype(float)
            hyg_now = float(close.iloc[-1])
            hyg_60d_high = float(close.tail(60).max())
            dd = (hyg_now - hyg_60d_high) / hyg_60d_high * 100
            hyg_5d = float(close.iloc[-6]) if len(close) >= 6 else hyg_now
            dd_5d = (hyg_5d - hyg_60d_high) / hyg_60d_high * 100
            detail["hyg_now"] = round(hyg_now, 2)
            detail["hyg_dd_60d_pct"] = round(dd, 2)
            detail["hyg_dd_60d_5d_ago_pct"] = round(dd_5d, 2)
            # Easing = drawdown is shallower than 5d ago, OR drawdown < -2.5%
            if dd > dd_5d:
                eases.append(f"HYG dd {dd:+.1f}% improving from {dd_5d:+.1f}%")
            elif dd > -2.5:
                eases.append(f"HYG dd {dd:+.1f}% only mild")
    except Exception as exc:
        detail["hyg_error"] = str(exc)

    if eases:
        return True, " · ".join(eases), detail
    return False, "neither VIX nor HYG showing easing", detail


def _evaluate_a3(ticker: str, period: str = "9mo") -> Dict[str, Any]:
    """Compute 20-week MA and current close vs MA distance."""
    out: Dict[str, Any] = {
        "ticker": ticker,
        "last_close": None,
        "ma_20w": None,
        "dist_to_ma_pct": None,
        "below_20w_ma": False,
        "error": None,
    }
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    except Exception as exc:
        out["error"] = f"yfinance: {exc}"
        return out
    if h is None or h.empty or "Close" not in h.columns:
        out["error"] = "no_history"
        return out
    close = h["Close"].astype(float)
    if len(close) < 60:
        out["error"] = f"insufficient_history len={len(close)}"
        return out

    last = float(close.iloc[-1])
    # 20-week MA ≈ 100 trading days. We use min(100, len-1) so emerging names
    # don't return None.
    window = min(100, len(close) - 1)
    ma = float(close.tail(window).mean())
    dist_pct = (last - ma) / ma * 100 if ma else 0.0
    out["last_close"] = round(last, 4)
    out["ma_20w"] = round(ma, 4)
    out["dist_to_ma_pct"] = round(dist_pct, 2)
    out["below_20w_ma"] = bool(last < ma)
    return out


def run(tickers: Optional[List[str]] = None) -> Dict[str, Any]:
    radar = _load(RADAR, {})
    a1, a1_reason = _evaluate_a1(radar)
    a2, a2_reason, a2_detail = _evaluate_a2()

    if tickers is None:
        try:
            from fetch_data import UNIVERSE
            tickers = list(UNIVERSE.keys())
        except Exception:
            tickers = []

    per_ticker: Dict[str, Any] = {}
    fired: List[Dict[str, Any]] = []
    watch: List[Dict[str, Any]] = []

    for tk in tickers:
        a3_doc = _evaluate_a3(tk)
        a3 = bool(a3_doc.get("below_20w_ma"))
        conds = sum([1 if a1 else 0, 1 if a2 else 0, 1 if a3 else 0])
        reasons = []
        if a1: reasons.append(f"A1 liq expanding ({a1_reason})")
        if a2: reasons.append(f"A2 funding easing ({a2_reason})")
        if a3: reasons.append(f"A3 below 20W MA (close {a3_doc.get('last_close')} vs MA {a3_doc.get('ma_20w')}, {a3_doc.get('dist_to_ma_pct')}%)")
        if not a1: reasons.append(f"~A1 ({a1_reason})")
        if not a2: reasons.append(f"~A2 ({a2_reason})")
        if not a3 and a3_doc.get("error"):
            reasons.append(f"~A3 error: {a3_doc['error']}")
        elif not a3:
            reasons.append(f"~A3 above 20W MA by {a3_doc.get('dist_to_ma_pct')}%")

        state = "FIRED" if conds == 3 else "WATCH" if conds == 2 else "INACTIVE"
        row = {
            "ticker": tk,
            "state": state,
            "conditions_met": conds,
            "a1": a1,
            "a2": a2,
            "a3": a3,
            "last_close": a3_doc.get("last_close"),
            "ma_20w": a3_doc.get("ma_20w"),
            "dist_to_ma_pct": a3_doc.get("dist_to_ma_pct"),
            "reasons": reasons,
        }
        per_ticker[tk] = row
        if state == "FIRED":
            fired.append(row)
        elif state == "WATCH":
            watch.append(row)

    fired.sort(key=lambda r: (r.get("dist_to_ma_pct") or 0))
    watch.sort(key=lambda r: -(r.get("conditions_met") or 0))

    out = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "a1_liquidity_expanding": {"value": a1, "reason": a1_reason},
        "a2_funding_easing": {"value": a2, "reason": a2_reason, "detail": a2_detail},
        "tickers": per_ticker,
        "shortlist_fired": fired[:15],
        "shortlist_watch": watch[:15],
        "n_fired": len(fired),
        "n_watch": len(watch),
        "doctrine": (
            "A = liquidity regime expanding + funding stress easing + price ≤ 20W MA. "
            "All 3 = FIRED (entry window open). 2/3 = WATCH (pre-condition forming). "
            "When price crosses above 20W MA, the A window closes and B-territory begins."
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
        print(f"[point_a] webroot mirror failed: {exc}")


if __name__ == "__main__":
    out = run()
    print(json.dumps({k: v for k, v in out.items() if k != "tickers"}, indent=2, ensure_ascii=False))
