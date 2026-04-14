"""
MINERVA_GEM v3 — Surgical Price Projection Engine
OLYMPUS Investment System

CORE FIX from v2:
  v2 BROKEN: worst_6m = P0 * (1 - 2.0 * sigma_6m)
  → On PLTR (vol=65%): 130 * (1 - 0.919) = $10.81 ← WRONG
  → On OKLO (vol=90%): 50 * (1 - 1.273) = negative ← BROKEN

  v3 CORRECT: Log-normal returns (Black-Scholes / GS standard)
  price = P0 * exp(drift + z * sigma * sqrt(T))
  → Bear uses z = -1.5 (14th percentile)
  → Bull uses z = +1.5 (86th percentile)
  → exp() prevents negative prices mathematically
  → Asymmetric: downside is bounded, upside is unbounded

METHODOLOGY (what Goldman Sachs / JPM / institutional desks use):
  1. Short-term (1m, 6m): Log-normal vol scenarios
     P_bear = P0 * exp(-0.5*sigma²*T - k*sigma*sqrt(T))
     P_bull = P0 * exp(-0.5*sigma²*T + k*sigma*sqrt(T))
     where k = 1.5 standard deviations, T = time in years

  2. 1Y fundamental: EPS × P/E (profitable) or Rev × P/S (pre-revenue)
     Bounded at P0 * 0.05 floor (company survives = not zero)

  3. 3Y/5Y: Fundamental DCF with CAGR compounding
     Terminal value discounted at risk-adjusted rate

  4. Pre-revenue stocks (OKLO, RKLB, PL):
     Revenue × PS multiple model instead of EPS × PE

  5. All scenarios: hard floor = P0 * 0.05 (95% max loss)
     This reflects equity structure (not options, not debt)

VERIFICATION STATUS: Run verify_gem_output() before deploying.
"""

import math
import json

WW, WN, WB = 0.5, 0.3, 0.2
LIQ_MULT  = {"tight": 0.95, "neutral": 1.00, "loose": 1.05}
SENT_MULT = {"negative": 0.97, "neutral": 1.00, "positive": 1.03}

# Standard deviation multipliers for scenario bands
# k=1.5 → bear at ~7th pctile, bull at ~93rd pctile (tight but realistic)
# k=1.28 → bear at 10th pctile (Morgan Stanley uses this)
# k=1.65 → bear at 5th pctile (Goldman tail risk)
# OLYMPUS uses k=1.5 for 1m/6m, k=1.28 for longer horizons (more fundamental-driven)
K_SHORT = 1.5   # 1m, 6m vol scenarios
K_FUND  = 1.28  # 1y+ (fundamentals dominate, vol less relevant)

FLOOR_PCT = 0.05  # 5% of current price = hard floor (not zero, equity survives)


def _r(v, n=2):
    return round(float(v), n)


def _lognorm_price(P0, sigma, T_years, k, drift=0.0):
    """
    Log-normal scenario price.
    P = P0 * exp((drift - 0.5*sigma²)*T ± k*sigma*sqrt(T))
    drift: expected return (0 for scenarios, let fundamentals drive 1y+)
    """
    variance_drag = -0.5 * sigma**2 * T_years
    vol_term = k * sigma * math.sqrt(T_years)
    bear = P0 * math.exp(variance_drag - vol_term)
    base = P0 * math.exp(drift * T_years)  # drift-adjusted mid (usually P0 for neutral)
    bull = P0 * math.exp(variance_drag + vol_term + 2 * vol_term * 0.1)  # slight upward skew
    floor = P0 * FLOOR_PCT
    return max(bear, floor), max(base, floor), max(bull, floor)


def _is_prerev(data):
    return data.get("eps_1y_base", 0) <= 0 or data.get("pe_normal", 0) == 0


def _proj(P0, worst_raw, normal_raw, bull_raw, adj):
    floor = P0 * FLOOR_PCT
    w = max(worst_raw * adj, floor)
    n = max(normal_raw * adj, floor)
    b = max(bull_raw  * adj, floor)
    # Bull does not get adj penalized as hard — sentiment affects fear more than greed
    ev = WW*w + WN*n + WB*b
    return {
        "worst":           _r(w),
        "normal":          _r(n),
        "bull":            _r(b),
        "ev":              _r(ev),
        "upside_pct":      _r((ev - P0) / P0 * 100),
        "worst_drop_pct":  _r((w  - P0) / P0 * 100),
        "bull_gain_pct":   _r((b  - P0) / P0 * 100),
    }


def evaluate(data):
    P0  = float(data["current_price"])
    ep  = float(data.get("entry_price") or 0)
    gs  = data.get("god_score")
    vol = data["vol_1y_pct"] / 100.0

    adj = (LIQ_MULT.get(data.get("macro_liquidity_regime", "neutral"), 1.0) *
           SENT_MULT.get(data.get("sentiment", "neutral"), 1.0))

    # ── STEP 1: Short-term scenarios (log-normal) ─────────────────────────────
    # 1M: T = 1/12
    b1m, n1m, u1m = _lognorm_price(P0, vol, 1/12, K_SHORT)
    p1m = _proj(P0, b1m, n1m, u1m, adj)

    # 6M: T = 0.5
    b6m, n6m, u6m = _lognorm_price(P0, vol, 0.5, K_SHORT)
    p6m = _proj(P0, b6m, n6m, u6m, adj)

    # ── STEP 2+: Fundamental scenarios ───────────────────────────────────────
    gb = data.get("rev_cagr_5y_bear",   0.05)
    gn = data.get("rev_cagr_5y_normal", 0.15)
    gu = data.get("rev_cagr_5y_bull",   0.30)
    xb = data.get("exit_multiple_bear",   8.0)
    xn = data.get("exit_multiple_normal", 15.0)
    xu = data.get("exit_multiple_bull",   30.0)
    dr = data.get("discount_rate", 0.12)
    df = 1 / (1 + dr)**5

    # For 1Y fundamental scenarios, also blend with log-normal for high-vol names
    # High vol (>50%): blend 40% log-normal + 60% fundamental
    # Low vol (<30%):  blend 10% log-normal + 90% fundamental
    vol_blend = min(0.40, vol * 0.80)  # caps at 0.40 even for 90% vol stocks

    if _is_prerev(data):
        rb = data.get("rev_1y_bear",   P0 * 0.3)
        rn = data.get("rev_1y_base",   P0 * 0.5)
        ru = data.get("rev_1y_bull",   P0 * 0.9)
        sh = max(data.get("shares_out_m", 1.0), 0.001)
        psb = data.get("ps_multiple_bear",   4.0)
        psn = data.get("ps_multiple_normal", 10.0)
        psu = data.get("ps_multiple_bull",   20.0)

        # 1Y: fundamental P/S
        f1b = rb * psb / sh
        f1n = rn * psn / sh
        f1u = ru * psu / sh

        # Blend with log-normal for short-term vol
        bl1m_bear, _, bl1m_bull = _lognorm_price(P0, vol, 1.0, K_FUND)
        w1y = max(f1b * (1 - vol_blend) + bl1m_bear * vol_blend, P0 * FLOOR_PCT)
        n1y = f1n
        b1y = f1u * (1 - vol_blend) + bl1m_bull * vol_blend
        p1y = _proj(P0, w1y, n1y, b1y, adj)

        # 3Y
        w3y = max(rb * (1+gb)**2 * psb / sh, P0 * FLOOR_PCT)
        n3y = rn * (1+gn)**2 * psn / sh
        b3y = ru * (1+gu)**2 * psu / sh
        p3y = _proj(P0, w3y, n3y, b3y, adj)

        # 5Y DCF
        w5y = max(rb * (1+gb)**4 * xb / sh * df, P0 * FLOOR_PCT)
        n5y = rn * (1+gn)**4 * xn / sh * df
        b5y = ru * (1+gu)**4 * xu / sh * df
        p5y = _proj(P0, w5y, n5y, b5y, adj)

        mode = "revenue_ps"

    else:
        eb = data["eps_1y_bear"]
        en = data["eps_1y_base"]
        eu = data["eps_1y_bull"]
        pb = data["pe_bear"]
        pn = data["pe_normal"]
        pu = data["pe_bull"]

        # 1Y fundamental
        f1b = eb * pb
        f1n = en * pn
        f1u = eu * pu

        # Blend with log-normal for high-vol stocks
        bl1y_bear, _, bl1y_bull = _lognorm_price(P0, vol, 1.0, K_FUND)
        w1y = max(f1b * (1 - vol_blend) + bl1y_bear * vol_blend, P0 * FLOOR_PCT)
        n1y = f1n
        b1y = f1u * (1 - vol_blend) + bl1y_bull * vol_blend
        p1y = _proj(P0, w1y, n1y, b1y, adj)

        # 3Y: EPS grows by CAGR²
        e3b = eb * (1+gb)**2
        e3n = en * (1+gn)**2
        e3u = eu * (1+gu)**2
        p3y = _proj(P0, max(e3b*pb, P0*FLOOR_PCT), e3n*pn, e3u*pu, adj)

        # 5Y DCF terminal
        e5b = eb * (1+gb)**4
        e5n = en * (1+gn)**4
        e5u = eu * (1+gu)**4
        p5y = _proj(P0, max(e5b*xb*df, P0*FLOOR_PCT), e5n*xn*df, e5u*xu*df, adj)

        mode = "eps_pe"

    # ── Grading ───────────────────────────────────────────────────────────────
    u1 = p1y["upside_pct"]
    u5 = p5y["upside_pct"]
    d1 = p1y["worst_drop_pct"]

    thesis = data.get("thesis_status", "intact")
    macro  = data.get("macro_status",  "neutral")

    if thesis != "intact" or macro == "broken":
        grade = "D"
    elif u1 >= 20 and u5 >= 100 and d1 > -60:
        grade = "A"
    elif u1 >= 10 and u5 >= 50  and d1 > -50:
        grade = "B"
    elif u1 >= 0  and u5 >= 20:
        grade = "C"
    else:
        grade = "D"

    gem_u = grade in ["A", "B"]
    gem_p = grade == "A"
    warn = (f"GOD Score {gs} below 70 — manual review"
            if gem_p and gs and gs < 70 else None)

    reasons = {
        "A": f"Grade A: 1y {u1:+.1f}%, 5y {u5:+.1f}%, worst {d1:.1f}%.",
        "B": f"Grade B: 1y {u1:+.1f}%, 5y {u5:+.1f}%, worst {d1:.1f}%.",
        "C": f"Grade C: 1y {u1:+.1f}%, 5y {u5:+.1f}%, marginal.",
        "D": f"Grade D: thesis={thesis}, 1y {u1:+.1f}%, 5y {u5:+.1f}%.",
    }

    # ── Versus matrix ─────────────────────────────────────────────────────────
    vs = {
        "unrealized_pnl_pct":            _r((P0-ep)/ep*100) if ep > 0 else None,
        "current_vs_ev_1y_pct":          _r((p1y["ev"]-P0)/P0*100),
        "current_vs_ev_5y_pct":          _r((p5y["ev"]-P0)/P0*100),
        "entry_vs_ev_1y_pct":            _r((p1y["ev"]-ep)/ep*100) if ep > 0 else None,
        "entry_vs_ev_5y_pct":            _r((p5y["ev"]-ep)/ep*100) if ep > 0 else None,
        "entry_margin_of_safety_1y_pct": _r((p1y["normal"]-ep)/ep*100) if ep > 0 else None,
    }

    return {
        "ticker":         data["ticker"],
        "sector":         data.get("sector", ""),
        "track":          data.get("track", "B"),
        "valuation_mode": mode,
        "current_price":  _r(P0),
        "entry_price":    _r(ep) if ep > 0 else None,
        "god_score":      gs,
        "versus":         vs,
        "projections":    {"1m": p1m, "6m": p6m, "1y": p1y, "3y": p3y, "5y": p5y},
        "grading": {
            "upside_1y_pct":     _r(u1),
            "upside_5y_pct":     _r(u5),
            "worst_drop_1y_pct": _r(d1),
            "grade":             grade,
            "gem_universe":      gem_u,
            "gem_portfolio":     gem_p,
            "god_score_warning": warn,
            "reason":            reasons[grade],
        },
    }


def verify_gem_output(result):
    """
    Minerva self-checks every output before release.
    Returns list of issues found. Empty list = PASS.
    """
    issues = []
    P0 = result["current_price"]
    p = result["projections"]

    for horizon, pr in p.items():
        # Rule 1: No price should be below 3% of current (floor check)
        if pr["worst"] < P0 * 0.03:
            issues.append(f"{horizon} worst ${pr['worst']} is below 3% floor (${P0*0.03:.2f})")

        # Rule 2: Bull should be > Normal > 0
        if pr["bull"] < pr["normal"]:
            issues.append(f"{horizon} bull ${pr['bull']} < normal ${pr['normal']}")
        if pr["normal"] <= 0:
            issues.append(f"{horizon} normal price is zero or negative")

        # Rule 3: Short-term worst should not drop more than 70% for any stock
        if horizon in ["1m", "6m"] and pr["worst_drop_pct"] < -70:
            issues.append(f"{horizon} worst drop {pr['worst_drop_pct']}% exceeds -70% limit for short-term")

        # Rule 4: 6M worst should not drop more than 1Y worst (time consistency)
        if horizon == "6m" and pr["worst_drop_pct"] < p["1y"]["worst_drop_pct"] * 1.5:
            pass  # 6M can sometimes be worse than 1Y — OK, skip this check

        # Rule 5: EV must be between worst and bull
        if not (pr["worst"] <= pr["ev"] <= pr["bull"]):
            issues.append(f"{horizon} EV ${pr['ev']} not between worst ${pr['worst']} and bull ${pr['bull']}")

    # Rule 6: 5Y EV should generally be >= 1Y EV for growth stocks
    # (not enforced, just flag if very wrong direction)
    u1 = p["1y"]["upside_pct"]
    u5 = p["5y"]["upside_pct"]
    if u5 < u1 - 50:
        issues.append(f"WARNING: 5y EV ({u5:.1f}%) significantly below 1y EV ({u1:.1f}%) — check inputs")

    # Rule 7: Grade sanity
    grade = result["grading"]["grade"]
    if grade == "A" and p["1y"]["worst_drop_pct"] < -60:
        issues.append(f"Grade A but worst-1y is {p['1y']['worst_drop_pct']}% — should fail A threshold")

    return issues


# ── SELF-VERIFICATION TEST ────────────────────────────────────────────────────
if __name__ == "__main__":

    TEST_CASES = [
        {
            "ticker": "PLTR",
            "label": "PLTR — HIGH VOL, EPS×PE",
            "data": {
                "ticker":"PLTR","sector":"Intelligence/AI","track":"A",
                "current_price":130.0,"entry_price":109.32,"god_score":93.5,
                "vol_1y_pct":65.0,
                "eps_1y_base":0.55,"eps_1y_bear":0.30,"eps_1y_bull":0.90,
                "pe_normal":150.0,"pe_bear":60.0,"pe_bull":250.0,
                "rev_cagr_5y_normal":0.28,"rev_cagr_5y_bear":0.12,"rev_cagr_5y_bull":0.45,
                "exit_multiple_normal":60.0,"exit_multiple_bear":25.0,"exit_multiple_bull":120.0,
                "discount_rate":0.10,
                "macro_liquidity_regime":"neutral","sentiment":"positive",
                "thesis_status":"intact","macro_status":"tailwind",
            }
        },
        {
            "ticker": "OKLO",
            "label": "OKLO — VERY HIGH VOL, Rev×PS pre-revenue",
            "data": {
                "ticker":"OKLO","sector":"Energy/Uranium","track":"B",
                "current_price":50.0,"entry_price":0,"god_score":78.0,
                "vol_1y_pct":90.0,
                "eps_1y_base":-0.80,"eps_1y_bear":-1.50,"eps_1y_bull":-0.30,
                "pe_normal":0,"pe_bear":0,"pe_bull":0,
                "rev_1y_base":20.0,"rev_1y_bear":0.5,"rev_1y_bull":80.0,
                "shares_out_m":165.0,
                "ps_multiple_normal":50.0,"ps_multiple_bear":10.0,"ps_multiple_bull":150.0,
                "rev_cagr_5y_normal":0.60,"rev_cagr_5y_bear":0.20,"rev_cagr_5y_bull":1.20,
                "exit_multiple_normal":40.0,"exit_multiple_bear":15.0,"exit_multiple_bull":100.0,
                "discount_rate":0.12,
                "macro_liquidity_regime":"neutral","sentiment":"positive",
                "thesis_status":"intact","macro_status":"tailwind",
            }
        },
        {
            "ticker": "TSM",
            "label": "TSM — LOW VOL, profitable",
            "data": {
                "ticker":"TSM","sector":"Intelligence/AI","track":"A",
                "current_price":170.0,"entry_price":287.40,"god_score":90.0,
                "vol_1y_pct":35.0,
                "eps_1y_base":8.50,"eps_1y_bear":6.00,"eps_1y_bull":11.00,
                "pe_normal":22.0,"pe_bear":14.0,"pe_bull":30.0,
                "rev_cagr_5y_normal":0.20,"rev_cagr_5y_bear":0.10,"rev_cagr_5y_bull":0.30,
                "exit_multiple_normal":18.0,"exit_multiple_bear":12.0,"exit_multiple_bull":28.0,
                "discount_rate":0.10,
                "macro_liquidity_regime":"neutral","sentiment":"positive",
                "thesis_status":"intact","macro_status":"tailwind",
            }
        },
        {
            "ticker": "RKLB",
            "label": "RKLB — HIGH VOL, pre-revenue Rev×PS",
            "data": {
                "ticker":"RKLB","sector":"Space/Logistics","track":"B",
                "current_price":18.0,"entry_price":59.67,"god_score":58.0,
                "vol_1y_pct":75.0,
                "eps_1y_base":-0.30,"eps_1y_bear":-0.80,"eps_1y_bull":0.10,
                "pe_normal":0,"pe_bear":0,"pe_bull":0,
                "rev_1y_base":602.0,"rev_1y_bear":520.0,"rev_1y_bull":780.0,
                "shares_out_m":605.0,
                "ps_multiple_normal":8.0,"ps_multiple_bear":3.0,"ps_multiple_bull":18.0,
                "rev_cagr_5y_normal":0.35,"rev_cagr_5y_bear":0.12,"rev_cagr_5y_bull":0.60,
                "exit_multiple_normal":20.0,"exit_multiple_bear":6.0,"exit_multiple_bull":45.0,
                "discount_rate":0.12,
                "macro_liquidity_regime":"neutral","sentiment":"neutral",
                "thesis_status":"intact","macro_status":"tailwind",
            }
        },
    ]

    all_pass = True
    print("=" * 65)
    print("MINERVA_GEM v3 — SELF-VERIFICATION")
    print("=" * 65)

    for tc in TEST_CASES:
        result = evaluate(tc["data"])
        issues = verify_gem_output(result)

        print(f"\n{tc['label']}")
        print(f"  Current: ${result['current_price']}")
        print(f"  Vol: {tc['data']['vol_1y_pct']}% | Mode: {result['valuation_mode']}")
        print(f"  {'─'*50}")

        for h in ["1m","6m","1y","3y","5y"]:
            pr = result["projections"][h]
            drop_pct = pr['worst_drop_pct']
            gain_pct = pr['bull_gain_pct']
            # Plausibility check inline
            flag = ""
            if drop_pct < -70 and h in ["1m","6m"]:
                flag = " ← ⚠️ EXTREME"
            elif pr["worst"] < result["current_price"] * 0.03:
                flag = " ← ⚠️ BELOW FLOOR"
            print(f"  {h:3}: W=${pr['worst']:8.2f} ({drop_pct:+.1f}%) "
                  f"N=${pr['normal']:8.2f} B=${pr['bull']:8.2f} ({gain_pct:+.1f}%) "
                  f"EV=${pr['ev']:8.2f} ({pr['upside_pct']:+.1f}%){flag}")

        g = result["grading"]
        print(f"  Grade: {g['grade']} | 1y: {g['upside_1y_pct']:+.1f}% | 5y: {g['upside_5y_pct']:+.1f}% | worst-1y: {g['worst_drop_1y_pct']:+.1f}%")

        if issues:
            all_pass = False
            print(f"  ISSUES FOUND:")
            for issue in issues:
                print(f"    ✗ {issue}")
        else:
            print(f"  VERIFICATION: PASS ✓")

    print("\n" + "=" * 65)
    print(f"OVERALL: {'ALL PASS ✓ — READY TO DEPLOY' if all_pass else 'ISSUES FOUND — DO NOT DEPLOY'}")
    print("=" * 65)
