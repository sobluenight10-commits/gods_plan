"""
CORRELATION AUDITOR  —  OLYMPUS-SENTINEL Layer 3, Ring 4.

Purpose
-------
Prevent the hidden killer of small-capital portfolios: concentration that LOOKS
diversified by ticker but is actually ONE factor bet. Three examples from the
current universe that would fool a naive "max 20% per name" rule:

    NVDA + TSM + COHR + VRT + AMAT   → one AI-capex bet
    UEC + URNM + CCJ + UUUU + OKLO   → one nuclear cycle bet
    KTOS + RKLB + PL + ASTS          → one defense/space bet

When PC1 of the return matrix already explains > 50% of portfolio variance,
adding another AI/defense/nuclear name does NOT diversify — it doubles down.
This auditor measures that and VETOES the add.

Math
----
  1. Download ~2y of daily closes for all holdings + the candidate.
  2. Compute daily log-returns, drop NaN rows.
  3. Correlation matrix C. Largest eigenvalue λ1 of C divided by trace(C)
     is the "PC1 share of variance" — how one-dimensional the book is.
  4. For a candidate c, the marginal correlation to the portfolio is
         ρ_c = mean(C[c, held])                       (simple, robust)
         β_c = Cov(r_c, r_port) / Var(r_port)         (portfolio beta)
     where r_port is the equal-weighted sum of held-ticker returns.
  5. Veto rules (TRIP = block add / downgrade BUY → WATCH):
        VETO_PC1          : PC1 share ≥ 0.55  → book is already one bet
        VETO_NEIGHBOR     : ρ_c ≥ 0.70        → candidate is a sibling
        VETO_DOUBLE       : PC1 share ≥ 0.45 AND ρ_c ≥ 0.55
     WARN (soft, leaves decision to human):
        WARN_PC1          : PC1 share ≥ 0.45
        WARN_NEIGHBOR     : ρ_c ≥ 0.60

Output schema
-------------
  audit_portfolio(held_tickers) -> {
      "pc1_share": 0.62,
      "pc2_share": 0.14,
      "eff_bets": 1.9,                # exp(H) of eigenvalue entropy
      "concentration_state": "RED|ORANGE|YELLOW|GREEN",
      "top_cluster": ["NVDA","TSM","COHR","VRT","AMAT"],
      "n_tickers": 14,
      "days": 498,
  }

  check_candidate(candidate, held_tickers) -> {
      "marginal_corr": 0.71,
      "portfolio_beta": 1.14,
      "verdict": "VETO|WARN|OK",
      "vetoes": ["VETO_NEIGHBOR"],
      "reason": "KTOS ρ=0.71 vs book — joins existing defense cluster",
  }

Pure numpy + yfinance; no sklearn, no scipy.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

import math

import numpy as np

try:
    import yfinance as yf
except Exception:
    yf = None


MIN_DAYS = 250                  # at least ~1y of overlap
LOOKBACK_PERIOD = "2y"
PC1_RED = 0.55
PC1_ORANGE = 0.45
PC1_YELLOW = 0.35

NEIGHBOR_VETO = 0.70
NEIGHBOR_WARN = 0.60
DOUBLE_PC1 = 0.45
DOUBLE_RHO = 0.55


# ─────────────────────────────────────────────────────────────────────────────
# Price loading
# ─────────────────────────────────────────────────────────────────────────────
def _load_returns(tickers: List[str]) -> Tuple[List[str], np.ndarray]:
    """Return (kept_tickers, RET) where RET is (T, N) log-returns."""
    if yf is None or not tickers:
        return [], np.zeros((0, 0))
    series: Dict[str, np.ndarray] = {}
    for t in tickers:
        try:
            h = yf.Ticker(t).history(period=LOOKBACK_PERIOD, interval="1d", auto_adjust=True)
        except Exception:
            continue
        if h is None or len(h) < MIN_DAYS:
            continue
        c = h["Close"].dropna().to_numpy(dtype=float)
        if len(c) < MIN_DAYS:
            continue
        r = np.diff(np.log(c + 1e-12))
        series[t] = r
    if not series:
        return [], np.zeros((0, 0))
    # Align by right-edge (latest ~MIN_DAYS overlap)
    L = min(len(v) for v in series.values())
    L = max(L, MIN_DAYS)
    L = min(L, min(len(v) for v in series.values()))
    kept = list(series.keys())
    RET = np.column_stack([series[t][-L:] for t in kept])
    return kept, RET


# ─────────────────────────────────────────────────────────────────────────────
# Linear algebra
# ─────────────────────────────────────────────────────────────────────────────
def _corr(RET: np.ndarray) -> np.ndarray:
    if RET.size == 0:
        return np.zeros((0, 0))
    # Column-wise z-score
    mu = RET.mean(axis=0, keepdims=True)
    sd = RET.std(axis=0, keepdims=True) + 1e-12
    Z = (RET - mu) / sd
    n = max(Z.shape[0] - 1, 1)
    C = (Z.T @ Z) / n
    np.fill_diagonal(C, 1.0)
    return C


def _eig_shares(C: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return (eigvals_desc, eigvecs_desc_columns). Robust to symmetric C."""
    if C.size == 0:
        return np.zeros((0,)), np.zeros((0, 0))
    w, V = np.linalg.eigh(C)
    order = np.argsort(-w)
    return w[order], V[:, order]


def _effective_bets(eigvals: np.ndarray) -> float:
    """exp(H) where H is Shannon entropy of normalized eigenvalues.
    1 = totally concentrated; N = perfectly diversified."""
    if eigvals.size == 0:
        return 0.0
    w = np.maximum(eigvals, 0.0)
    s = w.sum()
    if s <= 0:
        return 0.0
    p = w / s
    p = p[p > 1e-12]
    H = float(-np.sum(p * np.log(p)))
    return float(math.exp(H))


def _top_cluster(eigvecs: np.ndarray, tickers: List[str], k: int = 6) -> List[str]:
    if eigvecs.size == 0:
        return []
    v1 = np.abs(eigvecs[:, 0])
    order = np.argsort(-v1)[:k]
    return [tickers[i] for i in order]


def _state(pc1: float) -> str:
    if pc1 >= PC1_RED:
        return "RED"
    if pc1 >= PC1_ORANGE:
        return "ORANGE"
    if pc1 >= PC1_YELLOW:
        return "YELLOW"
    return "GREEN"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def audit_portfolio(held: Iterable[str]) -> Dict[str, Any]:
    held = [t for t in dict.fromkeys(held) if t]          # unique, keep order
    if not held:
        return {"pc1_share": None, "pc2_share": None, "eff_bets": None,
                "concentration_state": "UNKNOWN", "top_cluster": [],
                "n_tickers": 0, "days": 0, "note": "No tickers supplied"}

    kept, RET = _load_returns(held)
    if RET.size == 0 or len(kept) < 3:
        return {"pc1_share": None, "pc2_share": None, "eff_bets": None,
                "concentration_state": "UNKNOWN", "top_cluster": kept,
                "n_tickers": len(kept), "days": RET.shape[0] if RET.size else 0,
                "note": "Insufficient history for correlation audit"}

    C = _corr(RET)
    eigvals, eigvecs = _eig_shares(C)
    trace = float(np.trace(C)) or 1.0
    pc1 = float(eigvals[0]) / trace
    pc2 = float(eigvals[1]) / trace if len(eigvals) > 1 else 0.0
    eff = _effective_bets(eigvals)
    state = _state(pc1)
    return {
        "pc1_share": round(pc1, 3),
        "pc2_share": round(pc2, 3),
        "eff_bets": round(eff, 2),
        "concentration_state": state,
        "top_cluster": _top_cluster(eigvecs, kept, 6),
        "n_tickers": len(kept),
        "days": int(RET.shape[0]),
        "note": {
            "RED": f"PC1={pc1:.0%} — the book is essentially ONE bet. Freeze new adds; diversify.",
            "ORANGE": f"PC1={pc1:.0%} — heavy single-factor tilt. Only add uncorrelated sleeves.",
            "YELLOW": f"PC1={pc1:.0%} — normal-high concentration; watch cluster growth.",
            "GREEN": f"PC1={pc1:.0%} — diversified across factors.",
        }[state],
    }


def check_candidate(candidate: str, held: Iterable[str]) -> Dict[str, Any]:
    held = [t for t in dict.fromkeys(held) if t and t != candidate]
    if not candidate:
        return {"verdict": "OK", "vetoes": [], "marginal_corr": None,
                "portfolio_beta": None, "reason": "empty candidate"}
    if not held:
        return {"verdict": "OK", "vetoes": [], "marginal_corr": None,
                "portfolio_beta": None, "reason": "empty portfolio (no sibling risk)"}

    kept, RET = _load_returns(held + [candidate])
    if candidate not in kept or len(kept) < 3:
        return {"verdict": "OK", "vetoes": ["DATA_MISSING"],
                "marginal_corr": None, "portfolio_beta": None,
                "reason": "Insufficient history for correlation check"}

    cidx = kept.index(candidate)
    hidx = [i for i, t in enumerate(kept) if t != candidate]
    rc = RET[:, cidx]
    rp = RET[:, hidx].mean(axis=1)      # equal-weight portfolio proxy

    # Correlation of candidate to portfolio (simple)
    rho = float(np.corrcoef(rc, rp)[0, 1])
    # Mean pairwise corr of candidate to each holding
    rho_neighbors = float(np.mean([np.corrcoef(rc, RET[:, i])[0, 1] for i in hidx]))
    # Beta to portfolio
    var_p = float(np.var(rp)) or 1e-12
    beta = float(np.cov(rc, rp, ddof=1)[0, 1]) / var_p

    # Portfolio concentration (without candidate)
    C = _corr(RET[:, hidx])
    eigvals, _ = _eig_shares(C)
    trace = float(np.trace(C)) or 1.0
    pc1 = float(eigvals[0]) / trace if eigvals.size else 0.0

    vetoes: List[str] = []
    if rho_neighbors >= NEIGHBOR_VETO:
        vetoes.append("VETO_NEIGHBOR")
    if pc1 >= PC1_RED:
        vetoes.append("VETO_PC1")
    if pc1 >= DOUBLE_PC1 and rho_neighbors >= DOUBLE_RHO:
        vetoes.append("VETO_DOUBLE")

    warn: List[str] = []
    if not vetoes:
        if rho_neighbors >= NEIGHBOR_WARN:
            warn.append("WARN_NEIGHBOR")
        if pc1 >= PC1_ORANGE:
            warn.append("WARN_PC1")

    verdict = "VETO" if vetoes else ("WARN" if warn else "OK")
    reason_parts = []
    if vetoes:
        reason_parts.append("VETO: " + ", ".join(vetoes))
    if warn:
        reason_parts.append("WARN: " + ", ".join(warn))
    reason_parts.append(f"ρ_book={rho_neighbors:.2f} · β={beta:.2f} · PC1={pc1:.0%}")
    return {
        "verdict": verdict,
        "vetoes": vetoes,
        "warnings": warn,
        "marginal_corr": round(rho_neighbors, 3),
        "portfolio_corr": round(rho, 3),
        "portfolio_beta": round(beta, 3),
        "pc1_without_me": round(pc1, 3),
        "reason": " · ".join(reason_parts),
    }


if __name__ == "__main__":
    import json, sys
    held = ["NVDA", "TSM", "COHR", "VRT", "AMAT", "PLTR", "UEC", "CCJ"]
    print("--- audit ---")
    print(json.dumps(audit_portfolio(held), indent=2))
    cand = sys.argv[1] if len(sys.argv) > 1 else "ASML"
    print(f"--- candidate {cand} ---")
    print(json.dumps(check_candidate(cand, held), indent=2))
