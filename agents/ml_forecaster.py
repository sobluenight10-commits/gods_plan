"""
ML FORECASTER  —  OLYMPUS-SENTINEL Layer 2.

Numpy-only "tiny boosted trees by hand" replacement — avoids adding
sklearn / LightGBM as server dependencies. The combination of:

    1. linear regression of forward 252d return on features        (trend)
    2. bootstrap over residuals                                    (spread)
    3. monotone shrinkage toward sector / universe base-rate        (bias guard)

is a deliberately humble estimator. It is *not* meant to be smarter than
GEM Heston or the analog k-NN — its job is to contribute diversity to
the ensemble so Bayesian model averaging (Layer 6) can reward whichever
voice is currently right.

Features reused from analog_forecaster.

Output: { p05, p25, p50, p75, p95, mean, model }
all returns are fractions.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

try:
    import yfinance as yf
except Exception:
    yf = None

from agents.analog_forecaster import (  # reuse feature machinery
    _build_features,
    _forward_returns,
    HORIZON,
    MIN_HISTORY,
)

N_BOOT = 500
SHRINK_TO_BASE = 0.20  # 20% shrinkage toward historical mean


def forecast(ticker: str) -> Optional[Dict[str, Any]]:
    if yf is None:
        return None
    try:
        hist = yf.Ticker(ticker).history(period="10y", interval="1d", auto_adjust=True)
    except Exception:
        return None
    if hist is None or len(hist) < MIN_HISTORY:
        return None
    close = hist["Close"].dropna().to_numpy(dtype=float)
    if len(close) < MIN_HISTORY:
        return None

    X_raw = _build_features(close)
    y_raw = _forward_returns(close, HORIZON)
    valid = (~np.isnan(X_raw).any(axis=1)) & (~np.isnan(y_raw))
    X = X_raw[valid]
    y = y_raw[valid]
    if X.shape[0] < 400:
        return None

    # Add bias column
    X1 = np.hstack([X, np.ones((X.shape[0], 1))])
    # OLS
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    y_hat = X1 @ beta
    residuals = y - y_hat

    # Today's prediction
    last_idx = len(X_raw) - 1
    while last_idx >= 0 and np.isnan(X_raw[last_idx]).any():
        last_idx -= 1
    if last_idx < 0:
        return None
    q = np.concatenate([X_raw[last_idx], [1.0]])
    mu = float(q @ beta)

    # Shrink toward historical mean
    base = float(np.mean(y))
    mu = (1.0 - SHRINK_TO_BASE) * mu + SHRINK_TO_BASE * base

    # Bootstrap residuals → posterior predictive
    rng = np.random.default_rng(42)
    boots = rng.choice(residuals, size=N_BOOT, replace=True) + mu

    return {
        "model": "ols_bootstrap",
        "p05": float(np.percentile(boots, 5)),
        "p25": float(np.percentile(boots, 25)),
        "p50": float(np.percentile(boots, 50)),
        "p75": float(np.percentile(boots, 75)),
        "p95": float(np.percentile(boots, 95)),
        "mean": mu,
        "n_boot": N_BOOT,
        "n_train": int(X.shape[0]),
        "horizon_days": HORIZON,
        "r2_in_sample": float(1.0 - np.var(residuals) / (np.var(y) + 1e-12)),
    }


if __name__ == "__main__":
    import json
    import sys
    tk = sys.argv[1] if len(sys.argv) > 1 else "TSM"
    out = forecast(tk)
    print(json.dumps(out, indent=2))
