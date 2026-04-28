"""
STRIKE RADAR — multi-horizon liquidity vector pivot detector.

Doctrine (the user's insight):
    "Vector is more important than range. The moment direction of money
     flow flips from CONTRACTING to EXPANDING is the strike window. The
     system must be hyper-sensitive to that pivot."

Inputs:
    FRED series WRESBAL (reserves), WTREGEN (TGA), RRPONTSYD (RRP).
    We pull ~80 weekly/daily observations, build a daily net-liquidity
    series, then compute the velocity stack:

        v_3d   = (net_t - net_{t-3})  / 3   $B/day   (very sensitive)
        v_7d   = (net_t - net_{t-7})  / 7   $B/day   (current standard)
        v_14d  = (net_t - net_{t-14}) / 14  $B/day   (confirmation)
        v_28d  = (net_t - net_{t-28}) / 28  $B/day   (regime baseline)

    accel = v_3d - v_14d                 ($B/day²) positive = accelerating

State machine (priority — first match wins):

    DEPLOY_RIDING       net ≥ 2200 AND v_7d ≥ 0
    DEPLOY_TOPPING      net ≥ 2200 AND v_7d < 0
    SELECTIVE_TAILWIND  1900 ≤ net < 2200 AND v_7d ≥ 0
    SELECTIVE_FADING    1900 ≤ net < 2200 AND v_7d < 0
    STRIKE_WINDOW_OPEN  net < 1900 AND v_3d ≥ 0 AND v_7d ≥ 0   ← deploy
    STRIKE_PIVOT_EARLY  net < 1900 AND v_3d ≥ 0 AND v_7d < 0   ← arm tranche
    FROZEN_CONTRACTING  net < 1900 AND v_3d < 0                ← hold

Component decomposition tells us *what* drove the pivot:
    reserves_share  = Δreserves / |Δnet|
    tga_share       = -Δtga     / |Δnet|     (TGA fall = liquidity rises)
    rrp_share       = -Δrrp     / |Δnet|     (RRP drain = liquidity rises)

Quality of pivot (most → least credible):
    A. reserves_share ≥ 0.5  → real liquidity injection (Fed expansion)
    B. rrp_share ≥ 0.5       → RRP draining into reserves (mechanical)
    C. tga_share ≥ 0.5       → Treasury spending (transient)

Output:  data/strike_radar.json
    {
      schema_version, generated_utc,
      net_liq_b, zone, state, strike_score (0-100),
      velocity: {v_3d, v_7d, v_14d, v_28d, accel},
      components: {reserves_b, tga_b, rrp_b,
                   reserves_share, tga_share, rrp_share, dominant_driver},
      pivot: {detected, days_since_pivot, quality (A/B/C/None)},
      mandate: 1-line action ("HOLD POWDER" / "ARM TRANCHE 1" / "STRIKE NOW")
    }
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

OUT = os.path.join(BASE, "data", "strike_radar.json")
WEBROOT_OUT = "/var/www/html/strike_radar.json"

FRED_SERIES = {
    "reserves": "WRESBAL",
    "tga": "WTREGEN",
    "rrp": "RRPONTSYD",
}
FRED_KEY = os.environ.get("FRED_API_KEY", "0bc0ed228f83cb0853a6fa1f35b970d3")
N_OBS = 90  # ~90 daily observations covers all velocity windows


def _fetch_fred_series(sid: str, n: int = N_OBS) -> List[Tuple[str, float]]:
    """Return [(date, value_in_millions_usd), ...] descending then re-sorted asc."""
    import urllib.parse
    import urllib.request

    qs = urllib.parse.urlencode({
        "series_id": sid,
        "api_key": FRED_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": n,
    })
    url = f"https://api.stlouisfed.org/fred/series/observations?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"[strike_radar] FRED fetch {sid} failed: {exc}")
        return []
    rows: List[Tuple[str, float]] = []
    for o in data.get("observations") or []:
        v = o.get("value")
        if v in (None, "."):
            continue
        try:
            rows.append((o["date"], float(v)))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r[0])
    return rows


def _build_net_series() -> List[Tuple[str, float]]:
    """Forward-fill weekly series to a daily $B net-liquidity series."""
    raw = {k: _fetch_fred_series(sid) for k, sid in FRED_SERIES.items()}
    if not all(raw.values()):
        return []
    all_dates = sorted({d for rows in raw.values() for d, _ in rows})
    if not all_dates:
        return []

    def _ffill(rows: List[Tuple[str, float]]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        last = None
        idx = 0
        for d in all_dates:
            while idx < len(rows) and rows[idx][0] <= d:
                last = rows[idx][1]
                idx += 1
            if last is not None:
                out[d] = last
        return out

    res = _ffill(raw["reserves"])
    tga = _ffill(raw["tga"])
    rrp = _ffill(raw["rrp"])
    M = 1000.0  # millions → billions
    series: List[Tuple[str, float]] = []
    for d in all_dates:
        if d in res and d in tga and d in rrp:
            net_b = (res[d] - tga[d] - rrp[d]) / M
            series.append((d, round(net_b, 2)))
    return series


def _v(series: List[Tuple[str, float]], window: int) -> Optional[float]:
    if len(series) <= window:
        return None
    nt = series[-1][1]
    n0 = series[-1 - window][1]
    return round((nt - n0) / window, 2)


def _delta(rows: List[Tuple[str, float]], window: int) -> Optional[float]:
    if len(rows) <= window:
        return None
    return rows[-1][1] - rows[-1 - window][1]


def _classify_state(net: float, v_3d: float, v_7d: float) -> str:
    if net is None or v_3d is None or v_7d is None:
        return "UNKNOWN"
    if net >= 2200:
        return "DEPLOY_RIDING" if v_7d >= 0 else "DEPLOY_TOPPING"
    if net >= 1900:
        return "SELECTIVE_TAILWIND" if v_7d >= 0 else "SELECTIVE_FADING"
    if v_3d >= 0 and v_7d >= 0:
        return "STRIKE_WINDOW_OPEN"
    if v_3d >= 0 and v_7d < 0:
        return "STRIKE_PIVOT_EARLY"
    return "FROZEN_CONTRACTING"


# Strike score: 0 (do not deploy) → 100 (deploy aggressively, all-in window).
# Anchored on liquidity + pivot quality. 50 = neutral / wait.
_STATE_BASE = {
    "FROZEN_CONTRACTING": 5,
    "SELECTIVE_FADING": 30,
    "DEPLOY_TOPPING": 35,
    "STRIKE_PIVOT_EARLY": 65,
    "SELECTIVE_TAILWIND": 70,
    "DEPLOY_RIDING": 80,
    "STRIKE_WINDOW_OPEN": 90,
    "UNKNOWN": 50,
}


def _strike_score(state: str, accel: Optional[float],
                   reserves_share: Optional[float],
                   rrp_share: Optional[float]) -> int:
    base = _STATE_BASE.get(state, 50)
    bonus = 0
    # Acceleration bonus (max +5 / -5)
    if accel is not None:
        if accel >= 1.0:
            bonus += 5
        elif accel >= 0.3:
            bonus += 3
        elif accel <= -1.0:
            bonus -= 5
        elif accel <= -0.3:
            bonus -= 3
    # Driver-quality bonus (real Fed expansion > Treasury spending)
    if reserves_share is not None and reserves_share >= 0.5:
        bonus += 5
    elif rrp_share is not None and rrp_share >= 0.5:
        bonus += 2
    score = max(0, min(100, base + bonus))
    return int(score)


def _pivot_detect(series: List[Tuple[str, float]]) -> Dict[str, Any]:
    """Find the most recent day where v_7d crosses from negative to ≥ 0."""
    if len(series) < 30:
        return {"detected": False, "days_since_pivot": None}
    # Compute v_7d on a rolling basis for last 30 days.
    pivots: List[int] = []
    for i in range(7, len(series)):
        nt = series[i][1]
        n0 = series[i - 7][1]
        v = (nt - n0) / 7.0
        if i > 7:
            prev_nt = series[i - 1][1]
            prev_n0 = series[i - 8][1]
            prev_v = (prev_nt - prev_n0) / 7.0
            if prev_v < 0 and v >= 0:
                pivots.append(i)
    if not pivots:
        return {"detected": False, "days_since_pivot": None}
    last = pivots[-1]
    days_since = len(series) - 1 - last
    return {"detected": True, "days_since_pivot": days_since, "pivot_index": last}


def _mandate(state: str, score: int, pivot: Dict[str, Any]) -> str:
    if state == "STRIKE_WINDOW_OPEN":
        return ("STRIKE NOW — deploy Tranche 1. Vector flipped to expanding "
                "while net liq still in DANGER zone. Maximum-asymmetry window.")
    if state == "STRIKE_PIVOT_EARLY":
        return ("ARM TRANCHE 1 — 3-day vector turning positive but 7-day not yet "
                "confirmed. Place limit orders at current support; wait one day.")
    if state == "FROZEN_CONTRACTING":
        return ("HOLD ALL POWDER — DANGER + CONTRACTING. Do not deploy. "
                "Watch v_3d daily for the first sign of reversal.")
    if state == "SELECTIVE_TAILWIND":
        return "DEPLOY BROADLY — tailwind active in selective zone. Add to high-conviction CORE."
    if state == "SELECTIVE_FADING":
        return "SECURE PROFIT — selective zone fading. Trim winners, no new entries."
    if state == "DEPLOY_RIDING":
        return "RIDE + ARM — full exposure on intact theses; arm limits on bench."
    if state == "DEPLOY_TOPPING":
        return "PREPARE TO TRIM — deploy zone but vector turning. Tighten stops."
    return "HOLD — state unknown, manual review."


def run() -> Dict[str, Any]:
    series = _build_net_series()
    if not series:
        plan = {
            "schema_version": 1,
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "FRED_UNAVAILABLE",
            "state": "UNKNOWN",
            "strike_score": 50,
            "mandate": "HOLD — FRED feed unavailable. Retry after market close.",
        }
        _write(plan)
        return plan

    last_date, net_b = series[-1]
    v_3d = _v(series, 3)
    v_7d = _v(series, 7)
    v_14d = _v(series, 14)
    v_28d = _v(series, 28)
    accel = (v_3d - v_14d) if (v_3d is not None and v_14d is not None) else None

    # Component decomposition (last 7d delta in $B)
    raw_res = _fetch_fred_series(FRED_SERIES["reserves"])
    raw_tga = _fetch_fred_series(FRED_SERIES["tga"])
    raw_rrp = _fetch_fred_series(FRED_SERIES["rrp"])
    M = 1000.0
    d_res = (_delta(raw_res, 7) or 0.0) / M
    d_tga = (_delta(raw_tga, 7) or 0.0) / M
    d_rrp = (_delta(raw_rrp, 7) or 0.0) / M
    # liquidity contribution: + for reserves, - for tga & rrp
    d_net = d_res - d_tga - d_rrp
    if abs(d_net) > 0.01:
        reserves_share = round(d_res / abs(d_net), 2)
        tga_share = round(-d_tga / abs(d_net), 2)
        rrp_share = round(-d_rrp / abs(d_net), 2)
    else:
        reserves_share = tga_share = rrp_share = 0.0

    drivers = {
        "reserves": reserves_share,
        "rrp_drain": rrp_share,
        "tga_drain": tga_share,
    }
    dominant_driver = max(drivers, key=lambda k: drivers[k])
    if drivers[dominant_driver] >= 0.5:
        if dominant_driver == "reserves":
            quality = "A"
        elif dominant_driver == "rrp_drain":
            quality = "B"
        else:
            quality = "C"
    else:
        quality = None

    state = _classify_state(net_b, v_3d, v_7d)
    pivot = _pivot_detect(series)
    score = _strike_score(state, accel, reserves_share, rrp_share)

    if net_b < 1900:
        zone = "DANGER"
    elif net_b < 2200:
        zone = "SELECTIVE"
    else:
        zone = "DEPLOY"

    plan = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of_date": last_date,
        "net_liq_b": net_b,
        "zone": zone,
        "state": state,
        "strike_score": score,
        "velocity_b_per_day": {
            "v_3d": v_3d, "v_7d": v_7d, "v_14d": v_14d, "v_28d": v_28d,
            "accel_b_per_day2": round(accel, 2) if accel is not None else None,
        },
        "components_b_7d_delta": {
            "reserves_b": round(d_res, 2),
            "tga_b": round(d_tga, 2),
            "rrp_b": round(d_rrp, 2),
            "reserves_share": reserves_share,
            "tga_share": tga_share,
            "rrp_share": rrp_share,
            "dominant_driver": dominant_driver,
            "quality": quality,
        },
        "pivot": pivot,
        "mandate": _mandate(state, score, pivot),
        "thresholds": {
            "danger_below": 1900,
            "selective_below": 2200,
            "windows_days": [3, 7, 14, 28],
        },
    }
    _write(plan)
    return plan


def _write(plan: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    try:
        if os.path.isdir(os.path.dirname(WEBROOT_OUT)):
            shutil.copy2(OUT, WEBROOT_OUT)
    except Exception as exc:
        print(f"[strike_radar] webroot mirror failed: {exc}")


if __name__ == "__main__":
    p = run()
    print(json.dumps(p, indent=2))
