"""
FORECASTER ORCHESTRATOR  —  OLYMPUS-SENTINEL Layer 2 runner.

Runs analog + ml forecasters for every ticker in the portfolio,
blends with GEM forecasts using post_mortem weights, and writes a
single `data/forecasts.json` consumed by `tools/build_active_actions`.

Cache: if `data/forecasts.json` is fresher than MAX_CACHE_HOURS and
`--force` is not passed, we skip the run. yfinance pulls are the
slow part; this makes the daily pipeline fast.

Output schema:
{
  "generated_utc": "...",
  "horizon_days": 252,
  "weights": {"gem": 0.5, "analog": 0.3, "ml": 0.2},
  "tickers": {
    "TSM": {
       "ensemble":  {"p05":..., "p25":..., "p50":..., "p75":..., "p95":...,
                     "ev_pct": ..., "es5_pct": ..., "p_win": ..., "source": "gem+analog+ml"},
       "models":    {"gem": {...}, "analog": {...}, "ml": {...}}
    }, ...
  }
}
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from agents.analog_forecaster import forecast as analog_forecast  # noqa: E402
from agents.ml_forecaster import forecast as ml_forecast  # noqa: E402
from reflection.post_mortem import ensure_weights, get_weights_for  # noqa: E402

PORTFOLIO = os.path.join(BASE, "gem_inputs", "portfolio_all.json")
BLOG_TICKERS_LIVE = os.path.join(BASE, "data", "blog_tickers.json")
BLOG_TICKERS_SEED = os.path.join(BASE, "gem_inputs", "blog_tickers.json")
GEM_DIR = os.path.join(BASE, "gem_results")
OUT = os.path.join(BASE, "data", "forecasts.json")
WEBROOT_OUT = "/var/www/html/forecasts.json"
MAX_CACHE_HOURS = 12


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _latest_gem() -> dict:
    try:
        files = sorted(glob.glob(os.path.join(GEM_DIR, "gem_*.json")))
        if not files:
            return {}
        data = _load(files[-1], {})
        out = {}
        for row in data.get("alerts", []) or []:
            tk = row.get("ticker")
            proj_1y = (row.get("projections") or {}).get("1y") or {}
            if not tk or not proj_1y:
                continue
            # GEM quantiles (worst ≈ p05, normal ≈ p50, bull ≈ p95 as fractions of return)
            worst = (proj_1y.get("worst_drop_pct") or -20.0) / 100.0
            normal = (proj_1y.get("upside_pct") or 5.0) / 100.0
            bull = (proj_1y.get("bull_gain_pct") or 30.0) / 100.0
            out[tk] = {
                "model": "gem_heston",
                "p05": worst,
                "p25": (worst + normal) / 2.0,
                "p50": normal,
                "p75": (normal + bull) / 2.0,
                "p95": bull,
                "mean": normal,
                "source_file": os.path.basename(files[-1]),
                "horizon_days": 252,
            }
        return out
    except Exception:
        return {}


EV_CAP = 0.80     # absolute EV cap — anything beyond is extrapolation
ES5_CAP = 0.70    # absolute ES5 cap (positive number — we clamp bottom tail)
ES5_CONSERVATIVE_FLOOR = -0.20  # replacement when model gives nonsensical positive p05


def _ensemble(parts: dict, weights: dict) -> dict:
    """Weighted average of quantiles across available models, with sanity clips."""
    keys = ["p05", "p25", "p50", "p75", "p95"]
    avail = {m: parts[m] for m in parts if parts[m]}
    if not avail:
        return {}
    w = {m: weights.get(m, 0.0) for m in avail}
    tot = sum(w.values()) or 1.0
    w = {m: v / tot for m, v in w.items()}
    out = {}
    for k in keys:
        out[k] = sum(w[m] * avail[m].get(k, 0.0) for m in avail)

    # Enforce quantile monotonicity
    q = [out["p05"], out["p25"], out["p50"], out["p75"], out["p95"]]
    for i in range(1, len(q)):
        q[i] = max(q[i], q[i - 1])
    out["p05"], out["p25"], out["p50"], out["p75"], out["p95"] = q

    # Sanity caps — flag when invoked
    clipped = []
    ev = sum(w[m] * avail[m].get("mean", avail[m].get("p50", 0.0)) for m in avail)
    if ev > EV_CAP:
        clipped.append("ev_high")
        ev = EV_CAP
    elif ev < -EV_CAP:
        clipped.append("ev_low")
        ev = -EV_CAP

    es = out["p05"]
    if es < -ES5_CAP:
        clipped.append("es5_low")
        es = -ES5_CAP
    elif es > 0:
        # A positive p05 is almost always overfit — replace with a conservative
        # floor (-20%) so the sizer never sees "no downside." Never report safety
        # we didn't actually measure.
        clipped.append("es5_nonneg_replaced_floor")
        es = ES5_CONSERVATIVE_FLOOR

    out["ev_pct"] = round(ev * 100.0, 2)
    out["es5_pct"] = round(es * 100.0, 2)

    # p_win from IQR spread via z
    import math
    mu = ev
    sigma = max(1e-3, (out["p75"] - out["p25"]) / 1.349)
    z = mu / sigma if sigma > 0 else 0.0
    out["p_win"] = round(0.5 + 0.5 * math.tanh(0.7978845608 * z), 3)

    out["source"] = "+".join(sorted(avail.keys()))
    out["weights_used"] = w
    if clipped:
        out["clipped"] = clipped
    return out


def _tactical_sleeve_tickers() -> list[str]:
    """Kiwoom / blog macro sleeve — merged from live data/ + committed gem_inputs seed."""
    merged: list[str] = []
    for path in (BLOG_TICKERS_LIVE, BLOG_TICKERS_SEED):
        for x in (_load(path, {}).get("tactical_sleeve") or []):
            if isinstance(x, dict):
                t = (x.get("ticker") or "").strip().upper()
                if t:
                    merged.append(t)
    out: list[str] = []
    seen: set[str] = set()
    for t in merged:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _is_cache_fresh(extra_tickers: list[str] | None = None) -> bool:
    try:
        if not os.path.exists(OUT):
            return False
        mt = datetime.fromtimestamp(os.path.getmtime(OUT), tz=timezone.utc)
        if (datetime.now(timezone.utc) - mt) >= timedelta(hours=MAX_CACHE_HOURS):
            return False
        if extra_tickers:
            blob = _load(OUT, {})
            have = set((blob.get("tickers") or {}).keys())
            if any(t not in have for t in extra_tickers):
                return False
        return True
    except Exception:
        return False


def run(force: bool = False, tickers: list | None = None) -> dict:
    portfolio = _load(PORTFOLIO, [])
    base = tickers if tickers is not None else [p.get("ticker") for p in portfolio if p.get("ticker")]
    sleeve = _tactical_sleeve_tickers()
    tks = list(dict.fromkeys([t for t in base if t] + sleeve))

    if _is_cache_fresh(sleeve) and not force:
        existing = _load(OUT, {})
        print(f"[forecasters] cache < {MAX_CACHE_HOURS}h — using {OUT}")
        return existing
    if sleeve and not force:
        print(f"[forecasters] full run (portfolio + {len(sleeve)} tactical-sleeve names)")
    gem_map = _latest_gem()
    ensure_weights()

    out = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizon_days": 252,
        "tickers": {},
    }

    for tk in tks:
        print(f"[forecasters] {tk} …", flush=True)
        # Heavy calls in try/except so one failure can't kill the run
        gem_fc = gem_map.get(tk)
        try:
            analog_fc = analog_forecast(tk)
        except Exception as e:
            print(f"   analog failed: {e}")
            analog_fc = None
        try:
            ml_fc = ml_forecast(tk)
        except Exception as e:
            print(f"   ml failed: {e}")
            ml_fc = None

        parts = {"gem": gem_fc, "analog": analog_fc, "ml": ml_fc}
        weights = get_weights_for(ticker=tk, has_gem=bool(gem_fc))
        ens = _ensemble(parts, weights)
        out["tickers"][tk] = {
            "ensemble": ens,
            "models": {k: v for k, v in parts.items() if v},
            "weights": weights,
        }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    try:
        import shutil
        os.makedirs(os.path.dirname(WEBROOT_OUT), exist_ok=True)
        shutil.copy2(OUT, WEBROOT_OUT)
    except Exception as e:
        print(f"[warn] webroot mirror failed: {e}")

    print(f"[forecasters] wrote {OUT} ({len(out['tickers'])} tickers)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--tickers", nargs="*")
    a = ap.parse_args()
    run(force=a.force, tickers=a.tickers)
