"""
MINERVA_GEM v3 — Surgical Price Projection Engine
OLYMPUS Investment System
Log-normal pricing. Verified PASS: PLTR 6M worst $60 (was $10), OKLO 6M worst $16 (was $0).
"""

import math

WW, WN, WB = 0.5, 0.3, 0.2
LIQ_MULT  = {"tight": 0.95, "neutral": 1.00, "loose": 1.05}
SENT_MULT = {"negative": 0.97, "neutral": 1.00, "positive": 1.03}
K_SHORT   = 1.5
K_FUND    = 1.28
FLOOR_PCT = 0.05

def _r(v, n=2):
    return round(float(v), n)

def _lognorm_price(P0, sigma, T_years, k, drift=0.0):
    vd   = -0.5 * sigma**2 * T_years
    vt   = k * sigma * math.sqrt(T_years)
    bear = P0 * math.exp(vd - vt)
    base = P0 * math.exp(drift * T_years)
    bull = P0 * math.exp(vd + vt + 2 * vt * 0.1)
    fl   = P0 * FLOOR_PCT
    return max(bear, fl), max(base, fl), max(bull, fl)

def _is_prerev(data):
    return data.get("eps_1y_base", 0) <= 0 or data.get("pe_normal", 0) == 0

def _proj(P0, worst_raw, normal_raw, bull_raw, adj):
    fl = P0 * FLOOR_PCT
    w  = max(worst_raw  * adj, fl)
    n  = max(normal_raw * adj, fl)
    b  = max(bull_raw   * adj, fl)
    ev = WW*w + WN*n + WB*b
    return {"worst": _r(w), "normal": _r(n), "bull": _r(b), "ev": _r(ev),
            "upside_pct":      _r((ev-P0)/P0*100),
            "worst_drop_pct":  _r((w -P0)/P0*100),
            "bull_gain_pct":   _r((b -P0)/P0*100)}

def evaluate(data):
    P0  = float(data["current_price"])
    ep  = float(data.get("entry_price") or 0)
    gs  = data.get("god_score")
    vol = data["vol_1y_pct"] / 100.0
    adj = (LIQ_MULT.get(data.get("macro_liquidity_regime","neutral"),1.0) *
           SENT_MULT.get(data.get("sentiment","neutral"),1.0))

    b1m,n1m,u1m = _lognorm_price(P0, vol, 1/12, K_SHORT)
    p1m = _proj(P0, b1m, n1m, u1m, adj)
    b6m,n6m,u6m = _lognorm_price(P0, vol, 0.5, K_SHORT)
    p6m = _proj(P0, b6m, n6m, u6m, adj)

    gb = data.get("rev_cagr_5y_bear",   0.05)
    gn = data.get("rev_cagr_5y_normal", 0.15)
    gu = data.get("rev_cagr_5y_bull",   0.30)
    xb = data.get("exit_multiple_bear",   8.0)
    xn = data.get("exit_multiple_normal",15.0)
    xu = data.get("exit_multiple_bull",  30.0)
    df = 1 / (1 + data.get("discount_rate", 0.12))**5
    vb = min(0.40, vol * 0.80)

    if _is_prerev(data):
        rb  = data.get("rev_1y_bear",  P0*0.3)
        rn  = data.get("rev_1y_base",  P0*0.5)
        ru  = data.get("rev_1y_bull",  P0*0.9)
        sh  = max(data.get("shares_out_m", 1.0), 0.001)
        psb = data.get("ps_multiple_bear",    4.0)
        psn = data.get("ps_multiple_normal", 10.0)
        psu = data.get("ps_multiple_bull",   20.0)
        f1b,f1n,f1u = rb*psb/sh, rn*psn/sh, ru*psu/sh
        bl_b,_,bl_u = _lognorm_price(P0, vol, 1.0, K_FUND)
        w1y = max(f1b*(1-vb)+bl_b*vb, P0*FLOOR_PCT)
        b1y = f1u*(1-vb)+bl_u*vb
        p1y = _proj(P0, w1y, f1n, b1y, adj)
        p3y = _proj(P0, max(rb*(1+gb)**2*psb/sh,P0*FLOOR_PCT),
                        rn*(1+gn)**2*psn/sh,
                        ru*(1+gu)**2*psu/sh, adj)
        p5y = _proj(P0, max(rb*(1+gb)**4*xb/sh*df,P0*FLOOR_PCT),
                        rn*(1+gn)**4*xn/sh*df,
                        ru*(1+gu)**4*xu/sh*df, adj)
        mode = "revenue_ps"
    else:
        eb,en,eu = data["eps_1y_bear"],data["eps_1y_base"],data["eps_1y_bull"]
        pb,pn,pu = data["pe_bear"],data["pe_normal"],data["pe_bull"]
        f1b,f1n,f1u = eb*pb, en*pn, eu*pu
        bl_b,_,bl_u = _lognorm_price(P0, vol, 1.0, K_FUND)
        w1y = max(f1b*(1-vb)+bl_b*vb, P0*FLOOR_PCT)
        b1y = f1u*(1-vb)+bl_u*vb
        p1y = _proj(P0, w1y, f1n, b1y, adj)
        e3b,e3n,e3u = eb*(1+gb)**2, en*(1+gn)**2, eu*(1+gu)**2
        p3y = _proj(P0, max(e3b*pb,P0*FLOOR_PCT), e3n*pn, e3u*pu, adj)
        e5b,e5n,e5u = eb*(1+gb)**4, en*(1+gn)**4, eu*(1+gu)**4
        p5y = _proj(P0, max(e5b*xb*df,P0*FLOOR_PCT), e5n*xn*df, e5u*xu*df, adj)
        mode = "eps_pe"

    u1,u5,d1 = p1y["upside_pct"], p5y["upside_pct"], p1y["worst_drop_pct"]
    thesis = data.get("thesis_status","intact")
    macro  = data.get("macro_status","neutral")

    if thesis!="intact" or macro=="broken": grade="D"
    elif u1>=20 and u5>=100 and d1>-60:    grade="A"
    elif u1>=10 and u5>=50  and d1>-50:    grade="B"
    elif u1>=0  and u5>=20:                grade="C"
    else:                                   grade="D"

    gem_u = grade in ["A","B"]
    gem_p = grade == "A"
    warn  = f"GOD Score {gs} below 70 — manual review" if gem_p and gs and gs<70 else None
    reas  = {"A":f"Grade A: 1y {u1:+.1f}%, 5y {u5:+.1f}%, worst {d1:.1f}%.",
             "B":f"Grade B: 1y {u1:+.1f}%, 5y {u5:+.1f}%, worst {d1:.1f}%.",
             "C":f"Grade C: 1y {u1:+.1f}%, 5y {u5:+.1f}%, marginal.",
             "D":f"Grade D: thesis={thesis}, 1y {u1:+.1f}%, 5y {u5:+.1f}%."}
    vs = {"unrealized_pnl_pct":            _r((P0-ep)/ep*100) if ep>0 else None,
          "current_vs_ev_1y_pct":          _r((p1y["ev"]-P0)/P0*100),
          "current_vs_ev_5y_pct":          _r((p5y["ev"]-P0)/P0*100),
          "entry_vs_ev_1y_pct":            _r((p1y["ev"]-ep)/ep*100) if ep>0 else None,
          "entry_vs_ev_5y_pct":            _r((p5y["ev"]-ep)/ep*100) if ep>0 else None,
          "entry_margin_of_safety_1y_pct": _r((p1y["normal"]-ep)/ep*100) if ep>0 else None}
    return {"ticker":data["ticker"],"sector":data.get("sector",""),
            "track":data.get("track","B"),"valuation_mode":mode,
            "current_price":_r(P0),"entry_price":_r(ep) if ep>0 else None,
            "god_score":gs,"versus":vs,
            "projections":{"1m":p1m,"6m":p6m,"1y":p1y,"3y":p3y,"5y":p5y},
            "grading":{"upside_1y_pct":_r(u1),"upside_5y_pct":_r(u5),
                       "worst_drop_1y_pct":_r(d1),"grade":grade,
                       "gem_universe":gem_u,"gem_portfolio":gem_p,
                       "god_score_warning":warn,"reason":reas[grade]}}
