"""
POST-MORTEM  —  OLYMPUS-SENTINEL Layer 6.

Every closed trade (or every horizon-realized forecast) leaves a
lesson card in `data/lessons/<id>.json`. This module:

  1. Ensures `data/model_weights.json` exists with sensible defaults.
  2. When lesson cards are present, re-weights forecaster voices by
     rolling Continuous Ranked Probability Score (CRPS, approximated
     via pinball loss on discrete quantiles). Weights are stored
     per (sector × horizon).
  3. Never overwrites human override sections in the weights file.

For Phase 2 we ship with defaults and the CRPS updater stub; the
universe-wide weights are used until lessons accumulate.

Default weights per ticker category:
    gem    : 0.50   (Heston Monte Carlo — our battle-tested main voice)
    analog : 0.30   (empirical same-ticker nearest neighbors)
    ml     : 0.20   (numpy OLS + bootstrap)

If GEM has no row for a ticker, analog and ml absorb GEM's weight
proportionally (→ 0.60 / 0.40).
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEIGHTS = os.path.join(BASE, "data", "model_weights.json")
LESSONS_DIR = os.path.join(BASE, "data", "lessons")

DEFAULTS = {
    "version": 1,
    "updated_utc": "",
    "universe_default": {
        "gem": 0.50,
        "analog": 0.30,
        "ml": 0.20,
    },
    "fallback_no_gem": {
        "analog": 0.60,
        "ml": 0.40,
    },
    "per_sector_overrides": {},
    "per_ticker_overrides": {},
    "calibration": {
        "n_lessons_seen": 0,
        "last_refit_utc": None,
        "method": "pinball_loss_exponential_decay",
    },
    "notes": [
        "Defaults seeded 2026-04-24. CRPS updater activates once >= 20 lessons accumulate.",
    ],
}


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_weights(w: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(WEIGHTS), exist_ok=True)
    w["updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(WEIGHTS, "w", encoding="utf-8") as f:
        json.dump(w, f, indent=2, ensure_ascii=False)


def _pinball(quantile: float, forecast_q: float, realized: float) -> float:
    """Pinball loss at level q. Lower is better."""
    if realized >= forecast_q:
        return (realized - forecast_q) * quantile
    return (forecast_q - realized) * (1.0 - quantile)


def _crps_discrete(forecast: Dict[str, Any], realized: float) -> float:
    """Approximate CRPS via sum of pinball losses at standard quantiles."""
    levels = [(0.05, "p05"), (0.25, "p25"), (0.50, "p50"), (0.75, "p75"), (0.95, "p95")]
    loss = 0.0
    for q, k in levels:
        if k in forecast:
            loss += _pinball(q, float(forecast[k]), realized)
    return loss / len(levels)


def ensure_weights() -> Dict[str, Any]:
    if not os.path.exists(WEIGHTS):
        w = dict(DEFAULTS)
        _save_weights(w)
        return w
    current = _load(WEIGHTS, dict(DEFAULTS))
    # Backfill missing keys from defaults
    for k, v in DEFAULTS.items():
        current.setdefault(k, v)
    _save_weights(current)
    return current


def _load_lessons() -> List[Dict[str, Any]]:
    if not os.path.isdir(LESSONS_DIR):
        return []
    lessons = []
    for p in sorted(glob.glob(os.path.join(LESSONS_DIR, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                lessons.append(json.load(f))
        except Exception:
            continue
    return lessons


def refit_weights() -> Dict[str, Any]:
    """
    Re-compute forecaster weights from accumulated lesson cards.
    Activates only once there are enough observations — until then,
    defaults stand.
    """
    w = ensure_weights()
    lessons = _load_lessons()
    if len(lessons) < 20:
        w["calibration"]["n_lessons_seen"] = len(lessons)
        w["calibration"]["last_refit_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _save_weights(w)
        return w

    # Aggregate CRPS per model (exponential decay over time)
    models = ("gem", "analog", "ml")
    agg: Dict[str, float] = {m: 0.0 for m in models}
    now = datetime.now(timezone.utc)
    for lesson in lessons:
        realized = lesson.get("realized_return_1y")
        if realized is None:
            continue
        ts = lesson.get("closed_utc")
        try:
            age_days = max(1, (now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).days)
        except Exception:
            age_days = 365
        decay = 0.5 ** (age_days / 180.0)  # half-life 6 months
        for m in models:
            fc = lesson.get("forecasts", {}).get(m)
            if fc:
                agg[m] += _crps_discrete(fc, float(realized)) * decay

    # Lower CRPS = better → invert for weight, softmax
    import math
    scores = {m: -agg[m] for m in models if agg[m] > 0}
    if not scores:
        return w
    mx = max(scores.values())
    exps = {m: math.exp(v - mx) for m, v in scores.items()}
    tot = sum(exps.values())
    w["universe_default"] = {m: round(exps.get(m, 0.0) / tot, 3) for m in models}

    w["calibration"]["n_lessons_seen"] = len(lessons)
    w["calibration"]["last_refit_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_weights(w)
    return w


def get_weights_for(ticker: Optional[str] = None, sector: Optional[str] = None,
                    has_gem: bool = True) -> Dict[str, float]:
    w = ensure_weights()
    if ticker and ticker in w.get("per_ticker_overrides", {}):
        base = dict(w["per_ticker_overrides"][ticker])
    elif sector and sector in w.get("per_sector_overrides", {}):
        base = dict(w["per_sector_overrides"][sector])
    elif has_gem:
        base = dict(w.get("universe_default") or {})
    else:
        base = dict(w.get("fallback_no_gem") or {})

    # Drop gem weight if no gem, renormalize to {analog, ml}
    if not has_gem:
        base.pop("gem", None)
    total = sum(base.values()) or 1.0
    return {k: v / total for k, v in base.items()}


if __name__ == "__main__":
    w = refit_weights()
    print(json.dumps(w, indent=2))
