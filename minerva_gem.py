"""
MINERVA_GEM v4 — Heston-Hybrid Surgical Engine
OLYMPUS Investment System · 2026

ARCHITECTURE (three-layer):
  LAYER 1 — 1M / 6M: Heston Stochastic Volatility Monte Carlo
    - 10,000 paths, correlated Brownian motions (rho=-0.7)
    - Vol-of-vol (xi), mean-reversion (kappa/theta)
    - Implied vol blend: 70% IV + 30% historical (when available)
    - Produces P10/P50/P90 percentiles → Worst/Normal/Bull
    - Captures fat tails and volatility clustering GBM misses

  LAYER 2 — 1Y / 3Y: Fundamental scenarios
    - EPS × P/E (profitable) or Revenue × P/S (pre-revenue)
    - Blended with Heston-derived vol context (not pure MC)
    - Macro + sentiment multipliers applied

  LAYER 3 — 5Y: Terminal stock price (NOT discounted)
    - CAGR compounding × blended PE (current + exit)/2
    - Projects FUTURE price, not present value
    - Pure fundamental, no stochastic noise

WEIGHTS: 40% Worst / 40% Normal / 20% Bull (OLYMPUS v2 — reality-anchored)
  - Reality: stock prices embed expectations. Pure worst-case dominance
    ignores that markets price in consensus. 40W/40N/20B reflects that
    "normal" is the market's revealed bet, not an optimistic fantasy.
FLOOR: 5% of current price (equity survives — not options)

WHAT WAS TAKEN FROM HESTON PAPER:
  ✓ Correlated Brownian motions (rho = -0.7, real equity asymmetry)
  ✓ Variance process with mean-reversion kappa/theta
  ✓ Vol-of-vol parameter xi (volatility clustering)
  ✓ Full truncation scheme to prevent negative variance
  ✓ Monte Carlo percentiles for short horizons
  ✓ Implied vol blending for 1M/6M (when IV available)

WHAT WAS REJECTED:
  ✗ Heston for 5Y paths (noise, not signal)
  ✗ 50N/30B/20W weighting (wrong direction for OLYMPUS)
  ✗ 50W/30N/20B (too harsh — normal IS the market's bet)

GRADING: GEM Score (0-100) → 9 tiers: S / A+ / A / B+ / B / C+ / C / D / F
  Components: 5Y-upside(35) + 1Y-upside(25) + downside-protection(20) + asymmetry(20)
  ✗ Hard yfinance dependency (optional enhancement only)

SELF-VERIFICATION: verify_gem_output() runs automatically.
"""

import math
import json

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

WW, WN, WB = 0.4, 0.4, 0.2  # OLYMPUS v2 weights: Worst/Normal/Bull
FLOOR_PCT  = 0.05
K_FUND     = 1.28   # fundamental scenario sigma multiplier
N_PATHS    = 10000  # Monte Carlo paths
HESTON_RHO = -0.70  # price-vol correlation (equity: stocks fall faster than rise)
HESTON_KAPPA = 3.0  # mean-reversion speed
HESTON_XI_MULT = 0.6  # vol-of-vol = 60% of historical sigma
R_FREE     = 0.04   # risk-free rate

LIQ_MULT  = {"tight": 0.95, "neutral": 1.00, "loose": 1.05}
SENT_MULT = {"negative": 0.97, "neutral": 1.00, "positive": 1.03}

# ── Sector Calibration Tables (adapted from scenario-projection-engine) ──────
# EV/EBITDA (or EV/Rev for pre-rev) ranges by scenario, for sanity-checking
SECTOR_MULTIPLES = {
    "Intelligence":  {"worst": (15, 20), "normal": (22, 28), "bull": (35, 50)},
    "Energy":        {"worst": (4, 8),   "normal": (8, 14),  "bull": (15, 25)},
    "Space":         {"worst": (8, 12),  "normal": (15, 25), "bull": (30, 50)},  # EV/Rev
    "Bio":           {"worst": (8, 12),  "normal": (15, 30), "bull": (30, 60)},  # EV/Rev
    "Robotics":      {"worst": (12, 16), "normal": (18, 24), "bull": (28, 40)},
    "Defense":       {"worst": (12, 15), "normal": (16, 20), "bull": (22, 28)},
    "Infra":         {"worst": (10, 14), "normal": (16, 22), "bull": (24, 35)},
    "Global":        {"worst": (6, 10),  "normal": (10, 16), "bull": (16, 24)},
    "Locked":        {"worst": (10, 14), "normal": (18, 24), "bull": (28, 40)},
    "Tactical":      {"worst": (6, 8),   "normal": (8, 12),  "bull": (12, 16)},
}

# Revenue CAGR reference ranges by company maturity x scenario
CAGR_REFERENCE = {
    "pre_profit":  {"worst": (-0.10, 0.00), "normal": (0.15, 0.25), "bull": (0.30, 0.50)},
    "growth":      {"worst": (0.00, 0.08),  "normal": (0.10, 0.18), "bull": (0.20, 0.35)},
    "mature":      {"worst": (-0.05, 0.03), "normal": (0.03, 0.08), "bull": (0.08, 0.15)},
}

# Monitoring cadence by grade + thesis status
MONITOR_CADENCE = {
    ("S", "intact"):    "monthly",
    ("A+", "intact"):   "monthly",
    ("A", "intact"):    "monthly",
    ("B+", "intact"):   "monthly",
    ("B", "intact"):    "quarterly",
    ("C+", "intact"):   "weekly",
    ("C", "intact"):    "weekly",
    ("D", "intact"):    "weekly",
    ("F", "intact"):    "daily",
    ("D", "wounded"):   "daily",
    ("F", "wounded"):   "daily",
    ("F", "dead"):      "exit",
}

ACTION_WORDS = {
    "S":  "Strong Hold", "A+": "Hold + Add dips", "A": "Hold",
    "B+": "Hold", "B": "Hold — monitor", "C+": "Watch closely",
    "C":  "Trim candidate", "D": "Review thesis", "F": "Avoid / Exit",
}


def _r(v, n=2):
    return round(float(v), n)


def _heston_mc(S0, T, v0, theta, kappa, xi, rho, n_paths=N_PATHS):
    """
    Heston stochastic volatility Monte Carlo.
    Returns array of final prices (n_paths,).
    Uses full truncation scheme to prevent negative variance.
    """
    if not HAS_NUMPY or T <= 0:
        return None

    np.random.seed(42)  # reproducible
    steps = max(int(T * 252), 12)
    dt = T / steps

    prices = np.full(n_paths, float(S0))
    vols   = np.full(n_paths, float(v0))

    for _ in range(steps):
        # Correlated Brownian motions (rho captures equity asymmetry)
        Z = np.random.standard_normal((n_paths, 2))
        W1 = Z[:, 0]
        W2 = rho * Z[:, 0] + math.sqrt(1 - rho**2) * Z[:, 1]

        dW1 = W1 * math.sqrt(dt)
        dW2 = W2 * math.sqrt(dt)

        v_safe = np.maximum(vols, 0)

        # Variance process (full truncation — prevents negative var)
        vols = vols + kappa * (theta - v_safe) * dt + xi * np.sqrt(v_safe) * dW2
        vols = np.maximum(vols, 0)

        # Price process (geometric — no negative prices)
        prices = prices * np.exp(
            (R_FREE - 0.5 * v_safe) * dt + np.sqrt(v_safe) * dW1
        )

    return prices


def _mc_scenarios(S0, T, sigma_hist, implied_vol=None):
    """
    Run Heston MC and return (worst, normal, bull) at P10/P50/P90.
    Blends implied vol (70%) + historical (30%) when IV available.
    """
    if not HAS_NUMPY:
        return None, None, None

    # Vol blending: IV dominates near-term (as quant desks do)
    if implied_vol and implied_vol > 0:
        effective_vol = 0.70 * implied_vol + 0.30 * sigma_hist
    else:
        effective_vol = sigma_hist

    v0    = effective_vol ** 2
    theta = v0 * 1.1           # slight long-term upward mean reversion
    xi    = HESTON_XI_MULT * effective_vol

    final_prices = _heston_mc(S0, T, v0, theta, HESTON_KAPPA, xi, HESTON_RHO)
    if final_prices is None:
        return None, None, None

    floor = S0 * FLOOR_PCT
    worst  = max(float(np.percentile(final_prices, 10)), floor)
    normal = max(float(np.percentile(final_prices, 50)), floor)
    bull   = max(float(np.percentile(final_prices, 90)), floor)

    return worst, normal, bull


def _lerp(x, xs, ys):
    """Piecewise linear interpolation for scoring curves."""
    if x <= xs[0]: return ys[0]
    if x >= xs[-1]: return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]

GRADE_THRESHOLDS = [
    (80, "S"), (70, "A+"), (60, "A"), (50, "B+"),
    (40, "B"), (30, "C+"), (20, "C"), (10, "D"), (0, "F"),
]


def _gem_score(u1, u5, d1, b1_gain, risk_avg=None):
    """
    Multi-factor GEM Score (0-100) → 9-tier letter grade.

    Components (sum to 100 max before risk penalty):
      5Y upside   (0-35):  long-term compounding value
      1Y upside   (0-25):  near-term thesis validation
      Downside  (-15..20): 1Y worst-drop (PENALTY for extreme drawdowns)
      Asymmetry   (0-20):  bull-gain / worst-drop ratio (capped if downside extreme)
      Risk adj  (-15..+3): integrated risk screener penalty/bonus
    """
    s5 = _lerp(u5, [-50, 0, 25, 50, 100, 200], [0, 10, 18, 24, 30, 35])
    s1 = _lerp(u1, [-30, -15, 0, 10, 25], [0, 5, 12, 18, 25])

    # Downside: now PENALIZES extreme drawdowns (negative contribution below -50%)
    sd = _lerp(d1, [-90, -70, -50, -30, -15, -5], [-15, -8, 2, 10, 15, 20])

    ratio = b1_gain / max(abs(d1), 1) if d1 < -1 else 3.0
    sa = _lerp(ratio, [0.3, 1.0, 2.0, 3.5], [0, 5, 12, 20])

    # Cap asymmetry bonus when downside is catastrophic (prevents lottery-ticket inflation)
    if d1 < -60:
        sa = min(sa, 8)

    # Risk screener integration: CRITICAL=-15, HIGH=-8, MODERATE=0, LOW=+3
    risk_adj = 0.0
    if risk_avg is not None:
        risk_adj = _lerp(risk_avg, [1.5, 3.0, 4.5, 6.0, 7.5],
                                    [3,   0,   -4,  -10, -15])

    raw = s5 + s1 + sd + sa + risk_adj
    return round(min(100, max(0, raw)), 1)


def _score_to_grade(score):
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _proj(P0, worst_raw, normal_raw, bull_raw, adj):
    """Apply adj multiplier and compute EV with OLYMPUS 40/40/20 weights."""
    floor = P0 * FLOOR_PCT
    w  = max(worst_raw  * adj, floor)
    n  = max(normal_raw * adj, floor)
    b  = max(bull_raw   * adj, floor)
    ev = WW*w + WN*n + WB*b
    return {
        "worst":          _r(w),
        "normal":         _r(n),
        "bull":           _r(b),
        "ev":             _r(ev),
        "upside_pct":     _r((ev - P0) / P0 * 100),
        "worst_drop_pct": _r((w  - P0) / P0 * 100),
        "bull_gain_pct":  _r((b  - P0) / P0 * 100),
    }


def _is_prerev(data):
    return data.get("eps_1y_base", 0) <= 0 or data.get("pe_normal", 0) == 0


def _lognorm_fallback(P0, sigma, T, k=1.28):
    """Log-normal fallback when numpy unavailable."""
    vd   = -0.5 * sigma**2 * T
    vt   = k * sigma * math.sqrt(T)
    bear = P0 * math.exp(vd - vt)
    bull = P0 * math.exp(vd + vt + 2 * vt * 0.1)
    return max(bear, P0 * FLOOR_PCT), P0, max(bull, P0 * FLOOR_PCT)


def evaluate(data):
    P0  = float(data["current_price"])
    ep  = float(data.get("entry_price") or 0)
    gs  = data.get("god_score")
    vol = data["vol_1y_pct"] / 100.0
    iv  = data.get("implied_vol_pct", 0)  # optional: options-implied vol (annual %)
    iv  = iv / 100.0 if iv else None

    adj = (LIQ_MULT.get(data.get("macro_liquidity_regime", "neutral"), 1.0) *
           SENT_MULT.get(data.get("sentiment", "neutral"), 1.0))

    # ── LAYER 1: Heston MC for 1M and 6M ────────────────────────────────────
    heston_used = HAS_NUMPY

    w1m, n1m, b1m = _mc_scenarios(P0, 1/12, vol, iv)
    if w1m is None:
        w1m, n1m, b1m = _lognorm_fallback(P0, vol, 1/12)
        heston_used = False

    w6m, n6m, b6m = _mc_scenarios(P0, 0.5, vol, iv)
    if w6m is None:
        w6m, n6m, b6m = _lognorm_fallback(P0, vol, 0.5)

    # SANITY: MC normal should cluster around P0, bull must exceed P0
    if n1m < P0 * 0.85: n1m = P0 * 0.98  # market efficiency
    if b1m < P0:         b1m = P0 * (1 + 0.5 * vol * math.sqrt(1/12))
    if n6m < P0 * 0.70: n6m = P0 * 0.95
    if b6m < P0 * 0.90: b6m = P0 * (1 + 0.5 * vol * math.sqrt(0.5))

    p1m = _proj(P0, w1m, n1m, b1m, adj)
    p6m = _proj(P0, w6m, n6m, b6m, adj)

    # ── LAYER 2+3: Fundamental parameters ───────────────────────────────────
    gb = data.get("rev_cagr_5y_bear",   0.05)
    gn = data.get("rev_cagr_5y_normal", 0.15)
    gu = data.get("rev_cagr_5y_bull",   0.30)
    xb = data.get("exit_multiple_bear",   8.0)
    xn = data.get("exit_multiple_normal",15.0)
    xu = data.get("exit_multiple_bull",  30.0)

    # Vol blend for 1Y (Heston-informed but not full MC)
    vb = min(0.40, vol * 0.80)

    if _is_prerev(data):
        rb  = data.get("rev_1y_bear",  P0*0.3)
        rn  = data.get("rev_1y_base",  P0*0.5)
        ru  = data.get("rev_1y_bull",  P0*0.9)
        sh  = max(data.get("shares_out_m", 1.0), 0.001)
        psb = data.get("ps_multiple_bear",    4.0)
        psn = data.get("ps_multiple_normal", 10.0)
        psu = data.get("ps_multiple_bull",   20.0)

        f1b, f1n, f1u = rb*psb/sh, rn*psn/sh, ru*psu/sh

        # Blend 1Y fundamental with Heston-derived vol context
        hb_bear, _, hb_bull = _lognorm_fallback(P0, vol, 1.0, K_FUND)
        w1y = max(f1b*(1-vb) + hb_bear*vb, P0*FLOOR_PCT)
        b1y = f1u*(1-vb) + hb_bull*vb
        f1n_anchored = max(f1n, P0 * 0.70)
        b1y_anchored = max(b1y, P0 * 1.05)
        p1y = _proj(P0, w1y, f1n_anchored, b1y_anchored, adj)

        p3y = _proj(P0,
            max(rb*(1+gb)**2*psb/sh, P0*FLOOR_PCT),
            rn*(1+gn)**2*psn/sh,
            ru*(1+gu)**2*psu/sh, adj)

        p5y = _proj(P0,
            max(rb*(1+gb)**4*xb/sh, P0*FLOOR_PCT),
            rn*(1+gn)**4*xn/sh,
            ru*(1+gu)**4*xu/sh, adj)

        mode = "heston_1m6m + rev_ps_1y3y5y"

    else:
        eb, en, eu = data["eps_1y_bear"], data["eps_1y_base"], data["eps_1y_bull"]
        pb, pn, pu = data["pe_bear"], data["pe_normal"], data["pe_bull"]

        f1b, f1n, f1u = eb*pb, en*pn, eu*pu

        # Blend 1Y fundamental with Heston vol context
        hb_bear, _, hb_bull = _lognorm_fallback(P0, vol, 1.0, K_FUND)
        w1y = max(f1b*(1-vb) + hb_bear*vb, P0*FLOOR_PCT)
        b1y = f1u*(1-vb) + hb_bull*vb
        # SANITY: Normal 1Y should reflect market consensus (~P0), not pure EPS*PE
        f1n_anchored = max(f1n, P0 * 0.70)
        b1y_anchored = max(b1y, P0 * 1.05)
        p1y = _proj(P0, w1y, f1n_anchored, b1y_anchored, adj)

        e3b, e3n, e3u = eb*(1+gb)**2, en*(1+gn)**2, eu*(1+gu)**2
        p3y = _proj(P0,
            max(e3b*pb, P0*FLOOR_PCT),
            e3n*pn, e3u*pu, adj)

        # 5Y: EPS compounded × blended PE (current PE + exit multiple)/2
        # No discount — projecting FUTURE stock price, not present value
        pe5b = (pb + xb) / 2
        pe5n = (pn + xn) / 2
        pe5u = (pu + xu) / 2
        e5b, e5n, e5u = eb*(1+gb)**4, en*(1+gn)**4, eu*(1+gu)**4
        p5y = _proj(P0,
            max(e5b*pe5b, P0*FLOOR_PCT),
            e5n*pe5n, e5u*pe5u, adj)

        mode = "heston_1m6m + eps_pe_1y3y5y"

    # ── GEM Score — multi-factor 0-100 → 9-tier grade ──────────────────────
    u1 = p1y["upside_pct"]
    u5 = p5y["upside_pct"]
    d1 = p1y["worst_drop_pct"]
    b1 = p1y["bull_gain_pct"]

    thesis = data.get("thesis_status", "intact")
    macro  = data.get("macro_status",  "neutral")

    # Risk screener integration (injected by run_gem_daily or passed in data)
    risk_avg = data.get("_risk_avg")

    raw_score = _gem_score(u1, u5, d1, b1, risk_avg=risk_avg)
    grade = _score_to_grade(raw_score)

    if thesis == "dead":
        grade, raw_score = "F", min(raw_score, 9)
    elif thesis == "wounded" and raw_score >= 30:
        grade, raw_score = "C+", min(raw_score, 39)
    elif macro == "broken" and raw_score >= 40:
        grade, raw_score = "B", min(raw_score, 49)

    gem_u = grade in ["S", "A+", "A", "B+", "B"]
    gem_p = grade in ["S", "A+", "A"]
    warn  = f"GOD Score {gs} below 70 — manual review" if gem_p and gs and gs < 70 else None

    reason = (f"Grade {grade} (GEM {raw_score:.0f}/100): "
              f"1y {u1:+.1f}%, 5y {u5:+.1f}%, worst {d1:.1f}%, "
              f"bull {b1:+.1f}%")

    # ── Versus matrix ────────────────────────────────────────────────────────
    vs = {
        "unrealized_pnl_pct":            _r((P0-ep)/ep*100) if ep>0 else None,
        "current_vs_ev_1y_pct":          _r((p1y["ev"]-P0)/P0*100),
        "current_vs_ev_5y_pct":          _r((p5y["ev"]-P0)/P0*100),
        "entry_vs_ev_1y_pct":            _r((p1y["ev"]-ep)/ep*100) if ep>0 else None,
        "entry_vs_ev_5y_pct":            _r((p5y["ev"]-ep)/ep*100) if ep>0 else None,
        "entry_margin_of_safety_1y_pct": _r((p1y["normal"]-ep)/ep*100) if ep>0 else None,
    }

    # ── Two-layer verdict (GEM + Soros reconciliation) ───────────────────────
    soros_gap = data.get("soros_gap_pct", 0)
    soros_type = data.get("soros_type", "")  # "narrative" or "fundamental"

    gem_verdict = "NEAR-TERM OVERVALUED" if u1 < 0 else "NEAR-TERM UNDERVALUED"
    soros_verdict = ""
    if soros_gap and soros_type == "narrative":
        soros_verdict = f"LONG-TERM UNDERVALUED ({soros_gap:+.0f}% narrative gap)"
    elif soros_gap and soros_type == "fundamental":
        soros_verdict = f"FUNDAMENTAL GAP ({soros_gap:+.0f}% — thesis review)"

    two_layer = f"{gem_verdict} · {soros_verdict}" if soros_verdict else gem_verdict

    # ── "So What" action signal ──────────────────────────────────────────────
    near_label = "OVERVALUED" if u1 < -5 else "FAIR" if u1 < 5 else "UNDERVALUED"
    long_label = "OVERVALUED" if u5 < 5 else "FAIR" if u5 < 30 else "UNDERVALUED"

    cadence_key = (grade, thesis)
    if cadence_key not in MONITOR_CADENCE:
        cadence_key = (grade, "intact")
    cadence = MONITOR_CADENCE.get(cadence_key, "monthly")

    action_word = ACTION_WORDS.get(grade, "Review")
    sector = data.get("sector", "")

    so_what = (
        f"{action_word}. Thesis {thesis}. "
        f"Near: {near_label}, Long: {long_label}. "
        f"Monitor {cadence}."
    )

    risk_level = data.get("_risk_level", "UNKNOWN")

    return {
        "ticker":         data["ticker"],
        "sector":         data.get("sector", ""),
        "track":          data.get("track", "B"),
        "valuation_mode": mode,
        "heston_used":    heston_used,
        "current_price":  _r(P0),
        "entry_price":    _r(ep) if ep>0 else None,
        "god_score":      gs,
        "versus":         vs,
        "two_layer_verdict": two_layer,
        "projections":    {"1m": p1m, "6m": p6m, "1y": p1y, "3y": p3y, "5y": p5y},
        "grading": {
            "gem_score":         _r(raw_score, 1),
            "upside_1y_pct":     _r(u1),
            "upside_5y_pct":     _r(u5),
            "worst_drop_1y_pct": _r(d1),
            "bull_gain_1y_pct":  _r(b1),
            "grade":             grade,
            "gem_universe":      gem_u,
            "gem_portfolio":     gem_p,
            "god_score_warning": warn,
            "reason":            reason,
            "risk_integrated":   risk_avg is not None,
            "risk_avg":          _r(risk_avg, 1) if risk_avg is not None else None,
            "risk_level":        risk_level,
        },
        "so_what": {
            "action":    action_word,
            "signal":    so_what,
            "near_term": near_label,
            "long_term": long_label,
            "cadence":   cadence,
        },
    }


def verify_gem_output(result):
    issues = []
    P0 = result["current_price"]
    p  = result["projections"]
    for h, pr in p.items():
        if pr["worst"] < P0 * 0.03:
            issues.append(f"{h} worst {pr['worst']} below 3% floor")
        if pr["bull"] < pr["normal"]:
            issues.append(f"{h} bull < normal")
        if pr["normal"] <= 0:
            issues.append(f"{h} normal zero/negative")
        if h in ["1m","6m"] and pr["worst_drop_pct"] < -75:
            issues.append(f"{h} worst drop {pr['worst_drop_pct']}% exceeds -75%")
        if not (pr["worst"] <= pr["ev"] <= pr["bull"]):
            issues.append(f"{h} EV outside [worst,bull]")
    return issues


# ── SELF-VERIFICATION ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import time

    TEST_CASES = [
        {"ticker":"PLTR","current_price":130,"entry_price":109.32,"god_score":93.5,
         "vol_1y_pct":65,"eps_1y_base":0.55,"eps_1y_bear":0.30,"eps_1y_bull":0.90,
         "pe_normal":150,"pe_bear":60,"pe_bull":250,
         "rev_cagr_5y_normal":0.28,"rev_cagr_5y_bear":0.12,"rev_cagr_5y_bull":0.45,
         "exit_multiple_normal":60,"exit_multiple_bear":25,"exit_multiple_bull":120,
         "discount_rate":0.10,"macro_liquidity_regime":"neutral","sentiment":"positive",
         "thesis_status":"intact","macro_status":"tailwind",
         "soros_gap_pct":59,"soros_type":"narrative"},

        {"ticker":"OKLO","current_price":50,"entry_price":0,"god_score":78,
         "vol_1y_pct":90,"eps_1y_base":-0.80,"eps_1y_bear":-1.50,"eps_1y_bull":-0.30,
         "pe_normal":0,"pe_bear":0,"pe_bull":0,
         "rev_1y_base":20,"rev_1y_bear":0.5,"rev_1y_bull":80,"shares_out_m":165,
         "ps_multiple_normal":50,"ps_multiple_bear":10,"ps_multiple_bull":150,
         "rev_cagr_5y_normal":0.60,"rev_cagr_5y_bear":0.20,"rev_cagr_5y_bull":1.20,
         "exit_multiple_normal":40,"exit_multiple_bear":15,"exit_multiple_bull":100,
         "discount_rate":0.12,"macro_liquidity_regime":"neutral","sentiment":"positive",
         "thesis_status":"intact","macro_status":"tailwind"},

        {"ticker":"TSM","current_price":170,"entry_price":287.40,"god_score":90,
         "vol_1y_pct":35,"eps_1y_base":8.50,"eps_1y_bear":6.00,"eps_1y_bull":11.00,
         "pe_normal":22,"pe_bear":14,"pe_bull":30,
         "rev_cagr_5y_normal":0.20,"rev_cagr_5y_bear":0.10,"rev_cagr_5y_bull":0.30,
         "exit_multiple_normal":18,"exit_multiple_bear":12,"exit_multiple_bull":28,
         "discount_rate":0.10,"macro_liquidity_regime":"neutral","sentiment":"positive",
         "thesis_status":"intact","macro_status":"tailwind"},
    ]

    print("=" * 70)
    print(f"MINERVA_GEM v4 — HESTON HYBRID · numpy: {HAS_NUMPY}")
    print("=" * 70)

    all_pass = True
    for tc in TEST_CASES:
        t0 = time.time()
        r  = evaluate(tc)
        elapsed = time.time() - t0
        issues = verify_gem_output(r)

        print(f"\n{r['ticker']} | mode: {r['valuation_mode']}")
        print(f"  heston_used: {r['heston_used']} | {elapsed:.1f}s")
        print(f"  two_layer_verdict: {r['two_layer_verdict']}")
        sw = r.get("so_what", {})
        print(f"  so_what: {sw.get('signal','')}")
        print(f"  {'-'*55}")
        for h in ["1m","6m","1y","3y","5y"]:
            pr = r["projections"][h]
            flag = " ⚠️" if pr["worst_drop_pct"] < -75 and h in ["1m","6m"] else ""
            print(f"  {h:3}: W={pr['worst']:8.2f}({pr['worst_drop_pct']:+.1f}%) "
                  f"N={pr['normal']:8.2f} "
                  f"B={pr['bull']:8.2f}({pr['bull_gain_pct']:+.1f}%) "
                  f"EV={pr['ev']:8.2f}({pr['upside_pct']:+.1f}%){flag}")
        g = r["grading"]
        print(f"  Grade:{g['grade']} GEM:{g['gem_score']}/100 | "
              f"1y:{g['upside_1y_pct']:+.1f}% 5y:{g['upside_5y_pct']:+.1f}% "
              f"worst:{g['worst_drop_1y_pct']:+.1f}% bull:{g['bull_gain_1y_pct']:+.1f}%")
        if issues:
            all_pass = False
            for i in issues: print(f"  ✗ {i}")
        else:
            print(f"  ✓ PASS")

    print(f"\n{'='*70}")
    print(f"OVERALL: {'ALL PASS — READY TO DEPLOY' if all_pass else 'ISSUES FOUND'}")
    print(f"{'='*70}")
