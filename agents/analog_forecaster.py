"""
ANALOG FORECASTER  —  OLYMPUS-SENTINEL Layer 2.

Empirical nearest-neighbors over the same ticker's own history.

Why this works:
  - A stock "knows its own character": volatility regime, momentum
    auto-correlation, drawdown recovery shape are ticker-specific.
  - For the latest feature vector (today) we find the K historical
    windows that *looked* most similar, then read off their realized
    forward 252-day return. That empirical distribution is the forecast.

Pure numpy + yfinance. No sklearn dependency.

Features (z-scored across the ticker's full history):
    [ mom_21d, mom_63d, mom_252d, vol_21d, dd_from_52wk_hi, rsi_14 ]

Output: { p05, p25, p50, p75, p95, n_neighbors, latest_features }
all returns are fractions (0.15 = +15%).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

try:
    import yfinance as yf
except Exception:
    yf = None

# How many neighbors — enough for stable quantiles, small enough for signal
K_NEIGHBORS = 40
# Minimum history in trading days (raised — 500 days = only 1 forward window;
# we need many forward windows for the quantile to stabilize).
MIN_HISTORY = 1000
# Minimum training rows after removing the no-forward-return tail
MIN_TRAIN = 400
# Horizon for forward realized return (≈ 1y)
HORIZON = 252


def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    d = np.diff(close, prepend=close[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    roll_up = np.convolve(up, np.ones(period) / period, mode="same")
    roll_dn = np.convolve(dn, np.ones(period) / period, mode="same")
    rs = roll_up / (roll_dn + 1e-9)
    return 100.0 - (100.0 / (1.0 + rs))


def _zscore(a: np.ndarray) -> np.ndarray:
    m, s = np.nanmean(a), np.nanstd(a)
    return (a - m) / (s + 1e-9)


def _build_features(close: np.ndarray) -> np.ndarray:
    """Returns (T, F) z-scored feature matrix."""
    close = np.asarray(close, dtype=float)

    def safe_ret(lag: int) -> np.ndarray:
        out = np.full_like(close, np.nan)
        out[lag:] = close[lag:] / close[:-lag] - 1.0
        return out

    mom_21 = safe_ret(21)
    mom_63 = safe_ret(63)
    mom_252 = safe_ret(252)

    logret = np.diff(np.log(close + 1e-12), prepend=np.log(close[0] + 1e-12))
    vol_21 = np.full_like(close, np.nan)
    for i in range(21, len(close)):
        vol_21[i] = np.std(logret[i - 21:i]) * np.sqrt(252)

    hi_252 = np.full_like(close, np.nan)
    for i in range(252, len(close)):
        hi_252[i] = np.max(close[i - 252:i + 1])
    dd_from_hi = close / (hi_252 + 1e-12) - 1.0  # ≤ 0

    rsi = _rsi(close, 14)

    feats = np.stack([mom_21, mom_63, mom_252, vol_21, dd_from_hi, rsi], axis=1)
    # z-score column-wise ignoring NaN
    zf = np.full_like(feats, np.nan)
    for j in range(feats.shape[1]):
        zf[:, j] = _zscore(feats[:, j])
    return zf


def _forward_returns(close: np.ndarray, horizon: int = HORIZON) -> np.ndarray:
    out = np.full_like(close, np.nan, dtype=float)
    out[:-horizon] = close[horizon:] / close[:-horizon] - 1.0
    return out


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

    feats = _build_features(close)
    fwd = _forward_returns(close, HORIZON)

    # Rows where features AND forward return are defined
    valid = (~np.isnan(feats).any(axis=1)) & (~np.isnan(fwd))
    X = feats[valid]
    y = fwd[valid]
    if X.shape[0] < MIN_TRAIN:
        return None

    # The "today" feature vector = the last row of feats (forward return is NaN
    # there, which is fine — we use it as the query, not as a training point).
    last_idx = len(feats) - 1
    # Walk backwards to the last non-NaN feature row
    while last_idx >= 0 and np.isnan(feats[last_idx]).any():
        last_idx -= 1
    if last_idx < 0:
        return None
    q = feats[last_idx]

    # Cosine distance in z-space
    num = X @ q
    dq = np.linalg.norm(q) + 1e-9
    dX = np.linalg.norm(X, axis=1) + 1e-9
    cos = num / (dq * dX)
    # Nearest = largest cosine similarity
    idx = np.argsort(-cos)[:K_NEIGHBORS]
    neighbors = y[idx]
    if len(neighbors) < 10:
        return None

    return {
        "model": "analog_knn",
        "p05": float(np.percentile(neighbors, 5)),
        "p25": float(np.percentile(neighbors, 25)),
        "p50": float(np.percentile(neighbors, 50)),
        "p75": float(np.percentile(neighbors, 75)),
        "p95": float(np.percentile(neighbors, 95)),
        "mean": float(np.mean(neighbors)),
        "n_neighbors": int(len(neighbors)),
        "n_train": int(X.shape[0]),
        "horizon_days": HORIZON,
        "latest_features": {
            "mom_21d_z": float(q[0]),
            "mom_63d_z": float(q[1]),
            "mom_252d_z": float(q[2]),
            "vol_21d_z": float(q[3]),
            "dd_from_hi_z": float(q[4]),
            "rsi_14_z": float(q[5]),
        },
    }


if __name__ == "__main__":
    import json
    import sys
    tk = sys.argv[1] if len(sys.argv) > 1 else "TSM"
    out = forecast(tk)
    print(json.dumps(out, indent=2))
